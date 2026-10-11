using System;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Windowing;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Graphics;

namespace BeatricePC;
public partial class MainWindow
{
    private StartupWindow? startupWindow;
    private int mainWidth, mainHeight;
    private System.Diagnostics.ProcessStartInfo? relaunch;
    private async Task RestartApp()
    {
        if (closing || relaunch is not null || demo || busy) return;
        try {
            relaunch = AppRelaunch.Prepare();
            AppWindow.Hide();
            await ShutdownApp();
        }
        catch (Exception error) { relaunch=null; Activate(); SetFailure("앱 재실행 실패: " + error.Message); }
    }
    private async Task ShutdownApp()
    {
        if (closing) return;
        closing=true; recordsView.Dispose(); weeklySummaryView.Dispose(); rewardCooldownTimer?.Stop();
        startupWindow?.Complete(); startupWindow=null; Root.IsHitTestVisible=false; SetBackgroundEnabled(false);
        try {
            await engine.StopAsync().ConfigureAwait(false);
            if (relaunch is not null) AppRelaunch.Start(relaunch);
        }
        catch (Exception error) { File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"native-shutdown-error.log"),error.ToString()); }
        DispatcherQueue.TryEnqueue(() => {
            try { Application.Current.Exit(); }
            catch (Exception error) { File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"native-exit-error.log"),error.ToString()); }
        });
    }
    private void BeginSplash(int width, int height)
    {
        finishingSplash = false;
        AppWindow.Hide();
        mainWidth = width; mainHeight = height;
        startupWindow = new StartupWindow(Brush("hover"), WinRT.Interop.WindowNative.GetWindowHandle(this));
        startupWindow.ReadyToStart += async () => {
            try { if (demo) await CheckSplash(); else engine.Start(); }
            catch (Exception error) { SetFailure(error.Message); }
        };
        startupWindow.CancelStartup += () => Close();
    }
    public void ActivateStartup()
    {
        if (startupWindow is not null) startupWindow.Activate(); else Activate();
    }
    private Task WaitForMainFrame()
    {
        var frame = new TaskCompletionSource<bool>();
        EventHandler<object>? rendered = null;
        rendered = (_, _) => {
            if (!Root.IsLoaded || Root.ActualWidth <= 0 || Root.ActualHeight <= 0) return;
            Microsoft.UI.Xaml.Media.CompositionTarget.Rendering -= rendered;
            DispatcherQueue.TryEnqueue(Microsoft.UI.Dispatching.DispatcherQueuePriority.Low, () => frame.TrySetResult(true));
        };
        Microsoft.UI.Xaml.Media.CompositionTarget.Rendering += rendered;
        return frame.Task;
    }
    private async Task VerifyRepeatSplash()
    {
        for (var attempt = 0; attempt < 2; attempt++)
        {
            BeginSplash(AppWindow.Size.Width,AppWindow.Size.Height);
            if (finishingSplash) throw new InvalidOperationException("초기화 스플래시 종료 상태가 초기화되지 않았습니다.");
            EndSplash();
            await WaitForMainFrame();
            if (startupWindow is not null) throw new InvalidOperationException("반복 초기화 스플래시가 종료되지 않았습니다.");
        }
    }
    private bool verifyingStartup;
    private async Task VerifyStartupTransition()
    {
        if (verifyingStartup) return;
        verifyingStartup = true;
        await WaitForMainFrame();
        var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(Root);
        var pixels = await bitmap.GetPixelsAsync();
        var data = new byte[pixels.Length];
        using (var reader = Windows.Storage.Streams.DataReader.FromBuffer(pixels)) reader.ReadBytes(data);
        var darkPixels = 0;
        for (var i = 0; i < data.Length; i += 4)
            if (data[i+3] > 200 && data[i] < 100 && data[i+1] < 100 && data[i+2] < 100) darkPixels++;
        if (darkPixels < bitmap.PixelWidth * bitmap.PixelHeight / 2)
            throw new InvalidOperationException("메인 UI가 흰 화면이거나 비어 있습니다.");
        var directory = Path.Combine(AppContext.BaseDirectory, "startup-review");
        Directory.CreateDirectory(directory);
        var folder = await Windows.Storage.StorageFolder.GetFolderFromPathAsync(directory);
        var file = await folder.CreateFileAsync("main-native.png", Windows.Storage.CreationCollisionOption.ReplaceExisting);
        using (var stream = await file.OpenAsync(Windows.Storage.FileAccessMode.ReadWrite))
        {
            var encoder = await Windows.Graphics.Imaging.BitmapEncoder.CreateAsync(Windows.Graphics.Imaging.BitmapEncoder.PngEncoderId, stream);
            encoder.SetPixelData(Windows.Graphics.Imaging.BitmapPixelFormat.Bgra8, Windows.Graphics.Imaging.BitmapAlphaMode.Premultiplied,
                (uint)bitmap.PixelWidth, (uint)bitmap.PixelHeight, 96, 96, data);
            await encoder.FlushAsync();
        }
        var peer = new Microsoft.UI.Xaml.Automation.Peers.ButtonAutomationPeer(settingsButton!);
        ((Microsoft.UI.Xaml.Automation.Provider.IInvokeProvider)peer.GetPattern(Microsoft.UI.Xaml.Automation.Peers.PatternInterface.Invoke)).Invoke();
        await WaitForMainFrame();
        if (!settingsOpen || PageViewport.IsEnabled) throw new InvalidOperationException("설정 버튼 동작 실패");
        DismissSettings();
        await WaitForMainFrame();
        if (!mainContentLoaded || !ReferenceEquals(Content, Root) || bitmap.PixelWidth < 1000)
            throw new InvalidOperationException("메인 화면 전환 확인 실패");
        File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"startup-check.txt"),
            $"PASS: YOLO/OCR/OBS/public data ready; main painted and settings button invoked; {bitmap.PixelWidth}x{bitmap.PixelHeight}, {records.Count} records, in {startupWatch.Elapsed.TotalSeconds:F2}s");
        if (Environment.GetCommandLineArgs().Contains("--restart-check")) {
            var restartPeer = new Microsoft.UI.Xaml.Automation.Peers.ButtonAutomationPeer(engineRestart!);
            ((Microsoft.UI.Xaml.Automation.Provider.IInvokeProvider)restartPeer.GetPattern(Microsoft.UI.Xaml.Automation.Peers.PatternInterface.Invoke)).Invoke();
        }
        else Close();
    }
    private void UpdateSplash(JsonElement value)
    {
        if (startupWindow is null) return;
        if (value.TryGetProperty("startupStep", out var step)) startupWindow.Progress.Value = step.GetInt32();
        if ((value.TryGetProperty("startupReady", out var ready) && ready.GetBoolean()) ||
            (value.TryGetProperty("error", out var error) && !string.IsNullOrEmpty(error.GetString()))) EndSplash(true);
    }
    private bool finishingSplash;
    private void EndSplash(bool animate = false)
    {
        if (startupWindow is null || finishingSplash) return;
        finishingSplash = true;
        var previous = startupWindow;
        var ready = animate ? previous.WaitForProgressAsync() : Task.CompletedTask;
        _ = ready.ContinueWith(_ => DispatcherQueue.TryEnqueue(() => {
            if (closing) return;
            startupWindow = null;
            Activate();
            previous.Complete();
        }), TaskScheduler.Default);
    }
    private async Task CheckSplash()
    {
        await Task.Delay(300);
        startupWindow!.Progress.Value = 2;
        var moving = System.Diagnostics.Stopwatch.StartNew();
        await Task.Delay(80);
        if (new Windows.UI.ViewManagement.UISettings().AnimationsEnabled && moving.ElapsedMilliseconds < 240 &&
            (startupWindow.RenderedProgress <= 0 || startupWindow.RenderedProgress >= 2.0/3))
            throw new InvalidOperationException("진행 바가 중간 상태를 그리지 않았습니다.");
        await startupWindow.WaitForProgressAsync();
        var directory = Environment.GetCommandLineArgs().FirstOrDefault(x => x.StartsWith("--capture-dir="))?[14..]
            ?? Path.Combine(AppContext.BaseDirectory, "splash-check");
        Directory.CreateDirectory(directory);
        var folder = await Windows.Storage.StorageFolder.GetFolderFromPathAsync(Path.GetFullPath(directory));
        await startupWindow.SaveCaptureAsync(folder);
        startupWindow.Progress.Value = 3;
        await startupWindow.WaitForProgressAsync();
        await startupWindow.SaveCaptureAsync(folder,"splash-complete-native.png");
        EndSplash(); await WaitForMainFrame();
        if (!ReferenceEquals(Content, Root) || AppWindow.Size.Width != mainWidth || AppWindow.Size.Height != mainHeight)
            throw new InvalidOperationException("Splash transition failed");
        File.WriteAllText(Path.Combine(directory, "splash-status.txt"), "PASS: 256x256 splash, 128px bottom-up image fill, 32px per-pixel alpha corners, animated progress, main size restored");
        Close();
    }
}
