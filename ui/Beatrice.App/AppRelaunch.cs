using System;
using System.Diagnostics;
using System.IO;
using System.Linq;

namespace BeatricePC;

/// <summary>Launch a fresh app process after the current engine has stopped.</summary>
internal static class AppRelaunch
{
    internal static ProcessStartInfo CreateStartInfo(string executable,string[] arguments)
    {
        var start = new ProcessStartInfo(executable) {
            UseShellExecute=false, WorkingDirectory=Path.GetDirectoryName(executable)!,
            CreateNoWindow=true
        };
        // Retain installation/data lookup; start on the normal default page.
        foreach (var argument in arguments.Where(arg => arg.StartsWith("--app-root=",StringComparison.Ordinal)))
            start.ArgumentList.Add(argument);
        return start;
    }

    public static ProcessStartInfo Prepare()
    {
        var executable = Environment.ProcessPath;
        if (string.IsNullOrEmpty(executable) || !File.Exists(executable))
            throw new FileNotFoundException("앱 실행 파일을 찾지 못했습니다.");
        return CreateStartInfo(executable,Environment.GetCommandLineArgs());
    }

    public static void Start(ProcessStartInfo start)
    {
        using var process = Process.Start(start) ?? throw new InvalidOperationException("앱을 재실행하지 못했습니다.");
    }
}
