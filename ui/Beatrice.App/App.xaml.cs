using Microsoft.UI.Xaml;
using System;
using System.IO;

namespace BeatricePC;
public partial class App : Application
{
    private Window? window;
    public App()
    {
        InitializeComponent();
        UnhandledException += (_, args) => Log(args.Exception);
    }
    protected override void OnLaunched(LaunchActivatedEventArgs args)
    {
        try { var main = new MainWindow(); window = main; main.ActivateStartup(); }
        catch (Exception error) { Log(error); throw; }
    }
    private static void Log(Exception error)
    {
        var directory = Environment.GetEnvironmentVariable("BEATRICE_DATA_DIR") ?? AppContext.BaseDirectory;
        Directory.CreateDirectory(directory);
        File.AppendAllText(Path.Combine(directory,"winui-error.log"),DateTime.Now + "\n" + error + "\n");
    }
}
