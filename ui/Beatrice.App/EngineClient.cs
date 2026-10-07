using System;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;

namespace BeatricePC;

/// <summary>One headless analysis process; pipe messages never touch the UI thread directly.</summary>
internal sealed class EngineClient
{
    private Process? process;
    private readonly SemaphoreSlim writes = new(1, 1);
    private Task? stopTask;
    private bool stopping;
    public event Action<JsonElement>? Message;
    public event Action<string>? Failed;
    public bool IsRunning => process is not null && !process.HasExited;

    public void Start()
    {
        if (IsRunning) return;
        process?.Dispose(); process = null; stopping = false; stopTask = null;
        var rootArg = Environment.GetCommandLineArgs().FirstOrDefault(arg => arg.StartsWith("--app-root="));
        var root = rootArg is null ? FindRoot() : Path.GetFullPath(rootArg[11..]);
        var python = new[] { Path.Combine(root,"runtime","python.exe"), Path.Combine(root,".venv-win","Scripts","python.exe") }.FirstOrDefault(File.Exists);
        if (python is null) throw new FileNotFoundException("분석용 Python 런타임을 찾지 못했습니다.");
        var start = new ProcessStartInfo(python) {
            WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            StandardInputEncoding = new UTF8Encoding(false), StandardOutputEncoding = Encoding.UTF8, StandardErrorEncoding = Encoding.UTF8
        };
        start.ArgumentList.Add("-u");
        start.ArgumentList.Add(Path.Combine(root,"app_launcher.py"));
        start.ArgumentList.Add("--engine");
        if (Environment.GetCommandLineArgs().Contains("--startup-check"))
        {
            start.ArgumentList.Add("--engine-startup-check");
            start.Environment["BEATRICE_DATA_DIR"] = Path.Combine(root,"outputs","native-startup-check",Guid.NewGuid().ToString("N"));
        }
        start.Environment["PYTHONIOENCODING"] = "utf-8";
        var child = Process.Start(start) ?? throw new InvalidOperationException("분석 작업자를 시작하지 못했습니다.");
        process = child;
        _ = Task.Run(() => ReadAsync(child));
    }

    private static string FindRoot()
    {
        for (var directory = new DirectoryInfo(AppContext.BaseDirectory); directory is not null; directory = directory.Parent)
            if (File.Exists(Path.Combine(directory.FullName,"app_launcher.py"))) return directory.FullName;
        throw new DirectoryNotFoundException("앱 폴더를 찾지 못했습니다.");
    }

    private async Task ReadAsync(Process child)
    {
        var stderr = child.StandardError.ReadToEndAsync();
        try
        {
            while (await child.StandardOutput.ReadLineAsync() is string line)
            {
                using var document = JsonDocument.Parse(line);
                Message?.Invoke(document.RootElement.Clone());
            }
            await child.WaitForExitAsync();
            var error = await stderr;
            if (!stopping) Failed?.Invoke(string.IsNullOrWhiteSpace(error) ? "분석 작업자가 종료되었습니다. 앱을 다시 실행해주세요." : error);
        }
        catch (Exception error) { if (!stopping) Failed?.Invoke(error.Message); }
    }

    public async Task SendAsync(object command)
    {
        await writes.WaitAsync();
        try
        {
            if (process is null || process.HasExited) throw new InvalidOperationException("분석 작업자가 실행 중이 아닙니다.");
            await process.StandardInput.WriteLineAsync(JsonSerializer.Serialize(command));
            await process.StandardInput.FlushAsync();
        }
        finally { writes.Release(); }
    }

    public Task StopAsync() => stopTask ??= StopCoreAsync();
    private async Task StopCoreAsync()
    {
        stopping = true;
        if (process is null) return;
        if (!process.HasExited)
        {
            try { await SendAsync(new { type = "shutdown" }); }
            catch (IOException) { }
            catch (InvalidOperationException) { }
            process.StandardInput.Close();
            await process.WaitForExitAsync(); // OBS/model cleanup must finish before the window exits.
        }
        process.Dispose();
    }
}
