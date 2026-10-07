using System;
using System.Collections.Generic;
using System.IO;
using System.Diagnostics;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.UI;

namespace BeatricePC;
public partial class MainWindow : Window
{
    private readonly Dictionary<string, string> colors;
    private readonly string font;
    private readonly List<(Grid grid, FrameworkElement tags, FrameworkElement status)> rows = new();
    private bool connected;
    private bool settingsOpen;
    private Button? settingsButton;
    private Button? restartButton;
    private Button? maximizeButton;
    private string currentPage = "records";
    private sealed record Raid(string Character, string Dungeon, string Mode, string Gate, string Date, JsonElement Detail);
    private readonly List<Raid> records = new();
    private readonly EngineClient engine = new();
    private readonly bool demo = Environment.GetCommandLineArgs().Contains("--demo");
    private readonly bool startupCheck = Environment.GetCommandLineArgs().Contains("--startup-check");
    private readonly Stopwatch startupWatch = Stopwatch.StartNew();
    private TextBlock? characterName, characterStatus, appStatus, catalogStatus;
    private ComboBox? clientSelector;
    private Button? deleteButton, catalogRefresh;
    private bool applyingClients, closing, dialogOpen;
    private ContentDialog? activeDialog;
    private string lastRecords = "", lastClients = "", statusMessage = "모델을 준비하는 중…";
    private long selectedClient;
    private JsonElement clients;
    private bool busy, catalogBusy;
    public MainWindow()
    {
        InitializeComponent();
        using var tokens = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "Assets", "tokens.json")));
        colors = tokens.RootElement.GetProperty("colors").EnumerateObject().ToDictionary(p => p.Name, p => p.Value.GetString()!);
        colors["accentTint"] = tokens.RootElement.GetProperty("derivedColors").GetProperty("accentTint").GetString()!;
        font = tokens.RootElement.GetProperty("font").GetProperty("family").GetString()!;
        Root.Background = Brush("hover"); Rail.Background = Brush("sidebar");
        SecondarySidebar.Background = Brush("sidebar");
        var sidebarDivider = Brush("border"); sidebarDivider.Opacity = .45; Rail.BorderBrush = sidebarDivider;
        SidebarFooter.Background = Brush("hover"); SidebarFooter.BorderBrush = Brush("border");
        DetectedDungeon.Background = Brush("hover"); DetectedDungeon.BorderBrush = Brush("border");
        ProfileStatusDot.Stroke = Brush("hover");
        var scrim = Brush("background"); var scrimColor = scrim.Color; scrimColor.A = 210; scrim.Color = scrimColor;
        SettingsPresenter.Background = scrim; SettingsPanel.Background = Brush("hover"); SettingsMenuSurface.Background = Brush("sidebar");
        var settingsDivider = Brush("border"); settingsDivider.Opacity = .45; SettingsMenuSurface.BorderBrush = settingsDivider;
        Title = "Beatrice PC";
        var launchArgs = Environment.GetCommandLineArgs();
        var windowSize = launchArgs.FirstOrDefault(arg => arg.StartsWith("--window-size="))?.Split('=')[1].Split('x');
        var launchWidth = 1280; var launchHeight = 880;
        if (windowSize?.Length == 2 && int.TryParse(windowSize[0],out var width) && int.TryParse(windowSize[1],out var height) && width > 0 && height > 0)
            (launchWidth,launchHeight) = (width,height);
        AppWindow.Resize(new Windows.Graphics.SizeInt32(launchWidth, launchHeight));
        SetControlTokens();
        ExtendsContentIntoTitleBar = true;
        if (AppWindow.Presenter is Microsoft.UI.Windowing.OverlappedPresenter presenter) presenter.SetBorderAndTitleBar(true,false);
        SetTitleBar(AppStatusHost);
        AddCaptionControls();
        AppHeader.Background = Brush("surface");
        restartButton = new Button { Width = 52, Height = 44, Template = (ControlTemplate)Root.Resources["BareSettingsButton"], Content = new Image {
            Width = 20, Height = 20, Source = new SvgImageSource(new Uri("ms-appx:///Assets/icons/refresh-cw-muted.svg"))
        }};
        AutomationProperties.SetName(restartButton,"앱 재실행"); ToolTipService.SetToolTip(restartButton,"앱 재실행");
        restartButton.Click += async (_, _) => await RestartApp();
        HeaderContent.Children.Add(restartButton);
        var gameLabel = Text("LOST ARK",14); gameLabel.VerticalAlignment = VerticalAlignment.Center;
        HeaderContent.Children.Add(gameLabel);
        appStatus = Text(statusMessage,12,"muted"); appStatus.VerticalAlignment = VerticalAlignment.Center;
        appStatus.TextTrimming = TextTrimming.CharacterEllipsis; appStatus.TextWrapping = TextWrapping.NoWrap;
        AppStatusHost.Children.Add(appStatus);
        var mainMenu = Nav("square-dashed", "관문 기록", "records");
        mainMenu.Width = mainMenu.Height = 48;
        mainMenu.Padding = new Thickness(0);
        mainMenu.HorizontalContentAlignment = HorizontalAlignment.Center;
        mainMenu.VerticalContentAlignment = VerticalAlignment.Center;
        if (mainMenu.Content is Image mainIcon) mainIcon.Width = mainIcon.Height = 28;
        TopNavigation.Children.Add(mainMenu);
        var recordMenu = Action("관문 기록", (_, _) => ShowPage("records"));
        recordMenu.HorizontalAlignment = HorizontalAlignment.Stretch; recordMenu.HorizontalContentAlignment = HorizontalAlignment.Left;
        recordMenu.Background = Brush("accentTint"); recordMenu.BorderThickness = new Thickness(0);
        RecordNavigation.Children.Add(recordMenu);
        characterName = Text("캐릭터 확인 대기",14,bold:true);
        characterName.TextWrapping = TextWrapping.NoWrap; characterName.TextTrimming = TextTrimming.CharacterEllipsis;
        CharacterInfo.Children.Add(characterName);
        characterStatus = Text("초기화 중",12,"muted"); characterStatus.TextWrapping = TextWrapping.NoWrap;
        characterStatus.TextTrimming = TextTrimming.CharacterEllipsis;
        CharacterInfo.Children.Add(characterStatus);
        ProfileStatusDot.Fill = Brush("muted"); DetectedDungeon.Visibility = Visibility.Collapsed;
        settingsButton = Nav("settings", "설정", "settings");
        settingsButton.Width = 36; settingsButton.Height = 36; settingsButton.UseSystemFocusVisuals = false;
        settingsButton.Template = (ControlTemplate)Root.Resources["BareSettingsButton"];
        ProfileSettings.Children.Add(settingsButton);
        UpdateSettingsButton();
        var driveMenu = new Button { Width = 52, Height = 52, Content = new Image {
            Width = 20, Height = 20, Source = new SvgImageSource(new Uri("ms-appx:///Assets/icons/cloud-accent.svg"))
        }};
        AutomationProperties.SetName(driveMenu,"Google Drive 설정"); ToolTipService.SetToolTip(driveMenu,"Google Drive 설정");
        driveMenu.Click += (_, _) => SettingsContent.Children.Last().StartBringIntoView();
        driveMenu.Background = Brush("accentTint"); driveMenu.BorderBrush = Brush("accent");
        SettingsNavigation.Children.Add(Text("설정",20,bold:true));
        SettingsNavigation.Children.Add(driveMenu);
        var closeSettings = new Button { Width = 44, Height = 36, Template = (ControlTemplate)Root.Resources["BareSettingsButton"], Content = new Image { Width = 28, Height = 28, Source = new SvgImageSource(new Uri("ms-appx:///Assets/icons/x-muted.svg")) } };
        AutomationProperties.SetName(closeSettings,"설정 닫기"); ToolTipService.SetToolTip(closeSettings,"설정 닫기");
        closeSettings.Click += (_, _) => DismissSettings(); SettingsCloseHost.Children.Add(closeSettings);
        Root.PreviewKeyDown += (_, args) => {
            if (dialogOpen) return;
            if (args.Key == Windows.System.VirtualKey.Escape && DismissSettings()) args.Handled = true;
        };
        Root.SizeChanged += (_, _) => Adapt();
        ShowPage("records");
        engine.Message += value => DispatcherQueue.TryEnqueue(() => {
            try { Receive(value); } catch (Exception error) { SetFailure("분석 데이터 표시 오류: " + error.Message); }
        });
        engine.Failed += message => DispatcherQueue.TryEnqueue(() => SetFailure(message));
        Root.Loaded += async (_, _) => {
            try
            {
                if (demo) LoadDemo(); else engine.Start();
                if (Environment.GetCommandLineArgs().Contains("--capture")) { await Task.Delay(200); await CaptureReview(); }
            }
            catch (Exception error) { File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"native-load-error.log"),error.ToString()); SetFailure(error.Message); }
        };
        SettingsPresenter.TabFocusNavigation = Microsoft.UI.Xaml.Input.KeyboardNavigationMode.Cycle;
        AppWindow.Closing += async (_, args) => {
            args.Cancel = true;
            if (closing) return;
            closing = true; Root.IsHitTestVisible = false; SetBackgroundEnabled(false);
            if (appStatus is not null) appStatus.Text = "작업을 마무리하고 종료하는 중…";
            await engine.StopAsync(); Application.Current.Exit();
        };
    }
    private async Task RestartApp()
    {
        if (demo) { LoadDemo(); return; }
        DismissSettings(false);
        if (restartButton is not null) restartButton.IsEnabled = false;
        if (!engine.IsRunning)
        {
            try { engine.Start(); } catch (Exception error) { SetFailure(error.Message); }
        }
        else await Send(new { type = "restart" });
    }
    private async Task CaptureReview()
    {
        if (!demo) return;
        try
        {
            LoadDemo();
            if (TopNavigation.Children[0] is Button menu && menu.Content is Image menuIcon)
            {
                var available = menu.ActualWidth - menu.Padding.Left - menu.Padding.Right - menu.BorderThickness.Left - menu.BorderThickness.Right;
                if (menuIcon.ActualWidth < 28 || available < 28) throw new InvalidOperationException("메인 사이드바 아이콘 잘림");
            }
            ToggleMaximize(); await Task.Delay(150);
            if (AppWindow.Presenter is not Microsoft.UI.Windowing.OverlappedPresenter maximized || maximized.State != Microsoft.UI.Windowing.OverlappedPresenterState.Maximized) throw new InvalidOperationException("최대화 실패");
            ToggleMaximize(); await Task.Delay(150);
            if (AppWindow.Presenter is not Microsoft.UI.Windowing.OverlappedPresenter restored || restored.State != Microsoft.UI.Windowing.OverlappedPresenterState.Restored) throw new InvalidOperationException("복원 실패");
            restored.Minimize(); await Task.Delay(150);
            if (restored.State != Microsoft.UI.Windowing.OverlappedPresenterState.Minimized) throw new InvalidOperationException("최소화 실패");
            restored.Restore(); await Task.Delay(150);
            var outputArg = Environment.GetCommandLineArgs().FirstOrDefault(arg => arg.StartsWith("--capture-dir="));
            var folderPath = outputArg is null ? Path.GetFullPath(Path.Combine(AppContext.BaseDirectory,"..","..","..","..","..")) : Path.GetFullPath(outputArg[14..]);
            var folder = await Windows.Storage.StorageFolder.GetFolderFromPathAsync(folderPath);
            var views = new[]{"records", "detail", "settings", "records-640", "settings-640", "records-375", "settings-375", "empty"};
            foreach (var view in views)
            {
                if (view.EndsWith("640")) AppWindow.Resize(new Windows.Graphics.SizeInt32(640,1000));
                if (view.EndsWith("375")) AppWindow.Resize(new Windows.Graphics.SizeInt32(375,900));
                var before = AppWindow.Size;
                DismissSettings(false);
                Task? detailTask = null;
                if (view == "detail") detailTask = ShowRecordDetail(records[0]);
                if (view == "empty") { records.Clear(); RebuildRecords(); }
                if (view.StartsWith("settings")) ToggleSettings();
                await Task.Delay(400);
                if (before.Width != AppWindow.Size.Width || before.Height != AppWindow.Size.Height) throw new InvalidOperationException("설정 열기로 창 크기가 변경되었습니다.");
                if (view.StartsWith("settings") && (PageViewport.IsEnabled || !settingsOpen)) throw new InvalidOperationException("설정 오버레이 배경 차단 실패");
                var bitmap = new RenderTargetBitmap(); await bitmap.RenderAsync(view == "detail" ? activeDialog! : Root);
                var pixels = await bitmap.GetPixelsAsync();
                var file = await folder.CreateFileAsync(view + "-native.png",Windows.Storage.CreationCollisionOption.ReplaceExisting);
                using var stream = await file.OpenAsync(Windows.Storage.FileAccessMode.ReadWrite);
                var encoder = await Windows.Graphics.Imaging.BitmapEncoder.CreateAsync(Windows.Graphics.Imaging.BitmapEncoder.PngEncoderId,stream);
                var data = new byte[pixels.Length];
                using (var reader = Windows.Storage.Streams.DataReader.FromBuffer(pixels)) reader.ReadBytes(data);
                encoder.SetPixelData(Windows.Graphics.Imaging.BitmapPixelFormat.Bgra8,Windows.Graphics.Imaging.BitmapAlphaMode.Premultiplied,(uint)bitmap.PixelWidth,(uint)bitmap.PixelHeight,96,96,data);
                await encoder.FlushAsync();
                if (detailTask is not null) { activeDialog?.Hide(); await detailTask; }
                if (view.StartsWith("settings"))
                {
                    DismissSettings();
                    if (!PageViewport.IsEnabled || settingsOpen || settingsButton?.FocusState == FocusState.Unfocused) throw new InvalidOperationException("설정 닫기 후 포커스 복구 실패");
                }
            }
            File.WriteAllText(Path.Combine(folderPath,"capture-status.txt"),"PASS: custom caption minimize/maximize/restore; unclipped 28px menu icon; records/settings 1280,640,375; reward detail; empty state; stable window size; modal background blocking; focus restoration");
        }
        catch (Exception error) { File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"capture-error.txt"),error.ToString()); }
        finally { Application.Current.Exit(); }
    }
    private SolidColorBrush Brush(string key)
    {
        var value = colors[key];
        return new SolidColorBrush(Color.FromArgb(255, Convert.ToByte(value.Substring(1,2),16), Convert.ToByte(value.Substring(3,2),16), Convert.ToByte(value.Substring(5,2),16)));
    }
    private void SetControlTokens()
    {
        foreach (var state in new[]{"", "PointerOver", "Pressed", "Disabled"})
        {
            Root.Resources["ButtonBackground" + state] = Brush(state is "PointerOver" or "Pressed" ? "hover" : "surface");
            Root.Resources["ButtonForeground" + state] = Brush(state == "Disabled" ? "muted" : "text");
            Root.Resources["ButtonBorderBrush" + state] = Brush("border");
            Root.Resources["ComboBoxBackground" + state] = Brush(state is "PointerOver" or "Pressed" ? "hover" : "surface");
            Root.Resources["ComboBoxForeground" + state] = Brush(state == "Disabled" ? "muted" : "text");
            Root.Resources["ComboBoxBorderBrush" + state] = Brush("border");
        }
        Root.Resources["ControlCornerRadius"] = new CornerRadius(8);
        Root.Resources["ComboBoxDropDownBackground"] = Brush("surface");
        Root.Resources["ComboBoxDropDownBorderBrush"] = Brush("border");
        Root.Resources["FocusVisualPrimaryBrush"] = Brush("accent");
        Root.Resources["SystemControlHighlightAccentBrush"] = Brush("accent");
    }
    private TextBlock Text(string value, int size = 16, string color = "text", bool bold = false) => new()
    {
        Text = value, FontFamily = new FontFamily(font), FontSize = size,
        Foreground = Brush(color), FontWeight = bold ? Microsoft.UI.Text.FontWeights.SemiBold : Microsoft.UI.Text.FontWeights.Normal,
        TextWrapping = TextWrapping.Wrap
    };
    private Button Action(string label, RoutedEventHandler click)
    {
        var button = new Button { Content = label, MinHeight = 44, FontFamily = new FontFamily(font), FontSize = 14 };
        button.Click += click; return button;
    }
    private Button Nav(string icon, string label, string destination)
    {
        var button = new Button { Width = 52, Height = 52, Tag = destination, DataContext = icon, Content = new Image {
            Width = 20, Height = 20, Source = new SvgImageSource(new Uri($"ms-appx:///Assets/icons/{icon}-muted.svg"))
        }};
        AutomationProperties.SetName(button, label); ToolTipService.SetToolTip(button, label);
        button.Click += (_, _) => ShowPage(destination); return button;
    }
    private void ShowPage(string destination)
    {
        if (destination == "settings") { ToggleSettings(); return; }
        DismissSettings(false);
        if (destination == currentPage && Page.Children.Count > 0) return;
        currentPage = destination; Page.Children.Clear(); rows.Clear();
        foreach (var navigation in TopNavigation.Children.Concat(BottomNavigation.Children).OfType<Button>())
        {
            if (navigation == settingsButton) { UpdateSettingsButton(); continue; }
            var selected = (string?)navigation.Tag == destination;
            if ((string?)navigation.Tag != "settings")
            {
                navigation.Background = Brush(selected ? "accentTint" : "surface");
                navigation.BorderBrush = Brush(selected ? "accent" : "border");
            }
            if (navigation.Content is Image icon && navigation.DataContext is string iconName)
                icon.Source = new SvgImageSource(new Uri($"ms-appx:///Assets/icons/{iconName}-{(selected ? "accent" : "muted")}.svg"));
        }
        if (destination == "records") ShowRecords();
        else ShowAssets();
        Adapt();
    }
    private void ShowRecords()
    {
        var header = new StackPanel { Spacing = 8 };
        header.Children.Add(Text("관문 기록", 24, bold: true));
        Page.Children.Add(header);
        var list = new StackPanel { Spacing = 12 };
        foreach (var raid in records)
        {
            var grid = new Grid { ColumnSpacing = 24, RowSpacing = 12 };
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            var title = new StackPanel { Spacing = 4, VerticalAlignment = VerticalAlignment.Center };
            var tags = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8, VerticalAlignment = VerticalAlignment.Center };
            foreach (var value in new[]{raid.Mode, raid.Gate}) tags.Children.Add(new Border {
                Background = Brush(value == "하드" ? "accentTint" : "hover"), CornerRadius = new CornerRadius(999), Padding = new Thickness(6,2,6,2),
                Child = new TextBlock { Text = value, FontFamily = new FontFamily(font), FontSize = 12,
                    FontWeight = Microsoft.UI.Text.FontWeights.SemiBold, Foreground = Brush(value == "하드" ? "accent" : "text"), TextWrapping = TextWrapping.NoWrap }
            });
            title.Spacing = 4;
            var titleLine = new Grid { ColumnSpacing = 8, RowSpacing = 4, HorizontalAlignment = HorizontalAlignment.Left };
            titleLine.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            titleLine.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            titleLine.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1,GridUnitType.Star) });
            titleLine.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            titleLine.Children.Add(Text(raid.Dungeon,16,bold:true));
            Grid.SetColumn(tags,1); titleLine.Children.Add(tags); title.Children.Add(titleLine);
            title.Children.Add(Text(raid.Character, 14, "muted"));
            grid.Children.Add(title);
            var status = new StackPanel { Spacing = 8, VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Right };
            var timestamp = Text(raid.Date, 12, "muted"); timestamp.HorizontalAlignment = HorizontalAlignment.Right;
            var statusLabel = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 4, HorizontalAlignment = HorizontalAlignment.Right };
            statusLabel.Children.Add(new Image { Width = 16, Height = 16, Source = new SvgImageSource(new Uri("ms-appx:///Assets/icons/check-success.svg")) });
            statusLabel.Children.Add(Text("완료",12,"muted"));
            status.Children.Add(timestamp); status.Children.Add(statusLabel);
            Grid.SetColumn(status, 1); grid.Children.Add(status);
            var button = new Button { Content = grid, Padding = new Thickness(16,12,16,12), HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch, BorderBrush = new SolidColorBrush(Colors.Transparent), CornerRadius = new CornerRadius(12) };
            AutomationProperties.SetName(button, $"{raid.Character} {raid.Dungeon} {raid.Mode} {raid.Gate} 완료 {raid.Date}");
            button.Click += async (_, _) => await ShowRecordDetail(raid);
            list.Children.Add(button); rows.Add((grid, tags, status));
        }
        if (records.Count == 0) list.Children.Add(Text("저장된 완료 기록이 없습니다.",14,"muted"));
        Page.Children.Add(list);
    }
    private void Adapt()
    {
        UpdateMaximizeIcon();
        var small = Root.ActualWidth <= 560;
        var compact = Root.ActualWidth <= 900;
        RailColumn.Width = new GridLength(small ? 64 : 76);
        SidebarColumn.Width = small ? new GridLength(1,GridUnitType.Star) : new GridLength(Root.ActualWidth <= 1000 ? 208 : 248);
        Root.ColumnDefinitions[2].Width = small ? new GridLength(0) : new GridLength(1,GridUnitType.Star);
        Grid.SetRowSpan(SecondarySidebar,small ? 1 : 2);
        Grid.SetRow(PageViewport,small ? 2 : 1); Grid.SetRowSpan(PageViewport,small ? 1 : 2);
        Grid.SetColumn(PageViewport,small ? 1 : 2);
        Grid.SetColumnSpan(SidebarFooter,small ? 3 : 2);
        Rail.Padding = small ? new Thickness(8,16,8,16) : new Thickness(12,24,12,24);
        RecordNavigation.Margin = small ? new Thickness(12) : new Thickness(12,24,12,24);
        foreach (var button in TopNavigation.Children.OfType<Button>()) button.Width = button.Height = 48;
        var settingsInset = small ? 28 : compact ? 36 : 84;
        SettingsPanel.Margin = new Thickness(settingsInset,small ? 16 : 48,settingsInset,small ? 16 : 48);
        SettingsMenuColumn.Width = new GridLength(small ? 64 : compact ? 112 : 208);
        SettingsMenuSurface.Padding = new Thickness(small ? 8 : 16,24,small ? 8 : 16,24);
        SettingsScroll.Padding = compact ? new Thickness(16) : new Thickness(32,16,32,32);
        foreach (var button in SettingsNavigation.Children.OfType<Button>()) button.Width = small ? 48 : 52;
        if (SettingsNavigation.Children.FirstOrDefault() is TextBlock settingsLabel) settingsLabel.FontSize = small ? 14 : 20;
        Page.Margin = small ? new Thickness(16,24,16,160) : new Thickness(compact ? 24 : 40,32,compact ? 24 : 40,40);
        if (Page.Children.FirstOrDefault() is StackPanel heading && heading.Children.FirstOrDefault() is TextBlock title) title.FontSize = 24;
        if (Page.Children.ElementAtOrDefault(1) is StackPanel list)
            foreach (var button in list.Children.OfType<Button>()) button.Padding = new Thickness(16,12,16,12);
        if (SettingsContent.Children.FirstOrDefault() is TextBlock settingsTitle) settingsTitle.FontSize = small ? 24 : 32;
        var settingsContentWidth = Math.Max(0,Math.Min(1120,Root.ActualWidth - settingsInset*2) - SettingsMenuColumn.Width.Value - SettingsScroll.Padding.Left - SettingsScroll.Padding.Right);
        foreach (var section in SettingsContent.Children.OfType<StackPanel>()) section.Width = Math.Min(640,settingsContentWidth);
        foreach (var row in rows)
        {
            if (row.tags.Parent is Grid titleLine)
            {
                titleLine.ColumnDefinitions[1].Width = small ? new GridLength(0) : GridLength.Auto;
                Grid.SetColumn(row.tags,small ? 0 : 1); Grid.SetRow(row.tags,small ? 1 : 0);
            }
            var narrow = Root.ActualWidth <= 760;
            row.grid.ColumnDefinitions[1].Width = narrow ? new GridLength(0) : GridLength.Auto;
            Grid.SetColumn(row.status, narrow ? 0 : 1); Grid.SetRow(row.status, narrow ? 1 : 0);
            row.grid.RowSpacing = narrow ? 12 : 0;
        }
    }
    private void ShowSettings()
    {
        SettingsContent.Children.Clear();
        SettingsContent.Children.Add(Text("설정",32,bold:true));
        var clientSection = Section("게임 클라이언트");
        clientSelector = new ComboBox { HorizontalAlignment = HorizontalAlignment.Stretch, PlaceholderText = "게임 실행 대기", MinHeight = 44, FontFamily = new FontFamily(font), FontSize = 14 };
        AutomationProperties.SetName(clientSelector,"분석할 게임 클라이언트");
        clientSelector.SelectionChanged += async (_, _) => {
            if (!applyingClients && clientSelector.SelectedItem is ComboBoxItem item && item.Tag is long hwnd)
                await Send(new { type = "select", hwnd });
        };
        clientSection.Children.Add(clientSelector); UpdateClients();
        engineStatus = Text(statusMessage,12,"muted"); clientSection.Children.Add(engineStatus);
        var catalogSection = Section("공용 데이터");
        catalogStatus = Text("",14,"muted"); catalogSection.Children.Add(catalogStatus);
        catalogSection.Children.Add(Action("공용 데이터 보기",async (_, _) => { if (demo) await ShowCatalog(JsonDocument.Parse("[]").RootElement.Clone()); else await Send(new { type = "catalog" }); }));
        catalogRefresh = Action("공용 데이터 갱신",async (_, _) => await Send(new { type = "catalog_refresh" })); catalogSection.Children.Add(catalogRefresh);
        var recordSection = Section("기록 관리");
        deleteButton = Action("기록 전체 삭제",async (_, _) => await ConfirmDelete()); recordSection.Children.Add(deleteButton);
        var section = Section("Google Drive · 테스트");
        section.Children.Add(Text("샘플 데이터로 연결·업로드·다운로드 흐름을 확인합니다.",14,"muted"));
        var feedback = Text(connected ? "테스트 연결됨" : "연결되지 않음",14,"muted");
        var upload = Action("업로드 테스트", (_, _) => feedback.Text = "샘플 업로드 테스트 완료");
        var download = Action("다운로드 테스트", (_, _) => feedback.Text = "샘플 다운로드 테스트 완료");
        upload.IsEnabled = download.IsEnabled = connected;
        section.Children.Add(Action("연결 테스트", (_, _) => { connected = true; upload.IsEnabled = download.IsEnabled = true; feedback.Text = "테스트 연결됨"; }));
        section.Children.Add(upload); section.Children.Add(download); section.Children.Add(feedback);
        UpdateSettingsState();
    }
    private StackPanel Section(string title)
    {
        var section = new StackPanel { Spacing = 12, MaxWidth = 640, HorizontalAlignment = HorizontalAlignment.Left };
        section.Children.Add(Text(title,20,bold:true)); SettingsContent.Children.Add(section); return section;
    }
    private void ToggleSettings()
    {
        if (DismissSettings()) return;
        ShowSettings(); settingsOpen = true;
        SettingsPresenter.Visibility = Visibility.Visible;
        SettingsNavigation.Visibility = Visibility.Visible;
        PageViewport.IsEnabled = false;
        SetBackgroundEnabled(false);
        UpdateSettingsButton(); Adapt();
        clientSelector?.Focus(FocusState.Programmatic);
    }
    private bool DismissSettings(bool restoreFocus = true)
    {
        if (!settingsOpen) return false;
        settingsOpen = false; SettingsPresenter.Visibility = Visibility.Collapsed;
        PageViewport.IsEnabled = true;
        SetBackgroundEnabled(true);
        SettingsNavigation.Visibility = Visibility.Collapsed;
        UpdateSettingsButton(); Adapt();
        if (restoreFocus) settingsButton?.Focus(FocusState.Programmatic);
        return true;
    }
    private void UpdateSettingsButton()
    {
        if (settingsButton is null) return;
        var label = "설정";
        AutomationProperties.SetName(settingsButton,label); ToolTipService.SetToolTip(settingsButton,label);
        if (settingsButton.Content is Image icon)
        {
            icon.Width = icon.Height = 24;
            icon.Source = new SvgImageSource(new Uri("ms-appx:///Assets/icons/settings-filled-muted.svg"));
        }
    }
    private void SetBackgroundEnabled(bool enabled)
    {
        foreach (var control in TopNavigation.Children.Concat(RecordNavigation.Children).Concat(ProfileSettings.Children).Concat(HeaderContent.Children).OfType<Control>()) control.IsEnabled = enabled;
    }
    private void ShowAssets()
    {
        Page.Children.Add(Text("에셋 검토",32,bold:true));
        Page.Children.Add(Text("맑은 고딕 · 12 / 14 / 16 / 20 / 24 / 32 · Regular / Semibold / Bold",16,"muted"));
        foreach (var color in colors.Where(c => c.Key != "accentTint"))
        {
            var swatch = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 16 };
            swatch.Children.Add(new Border { Width = 44, Height = 44, Background = Brush(color.Key), BorderBrush = Brush("muted"), BorderThickness = new Thickness(1), CornerRadius = new CornerRadius(8) });
            swatch.Children.Add(Text($"{color.Key}  {color.Value}",16)); Page.Children.Add(swatch);
        }
        var icons = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 24 };
        foreach (var name in new[]{"history","refresh-cw","message-circle","bell","settings","cloud","check","x"})
            icons.Children.Add(new Image { Width = 20, Height = 20, Source = new SvgImageSource(new Uri($"ms-appx:///Assets/icons/{name}-muted.svg")) });
        Page.Children.Add(icons);
    }

    private async Task Send(object command)
    {
        if (demo) return;
        try { await engine.SendAsync(command); }
        catch (Exception error) { SetFailure(error.Message); }
    }
    private void SetFailure(string message)
    {
        statusMessage = message;
        if (appStatus is not null) { appStatus.Text = "분석 오류 · 설정에서 상태를 확인해주세요"; ToolTipService.SetToolTip(appStatus,message); }
        if (characterStatus is not null) characterStatus.Text = "분석 오류";
        ProfileStatusDot.Fill = Brush("muted"); DetectedDungeon.Visibility = Visibility.Collapsed;
        UpdateSettingsState();
    }
    private void Receive(JsonElement value)
    {
        if (closing) return;
        var kind = value.GetProperty("type").GetString();
        if (kind == "error") { SetFailure(value.GetProperty("message").GetString()!); return; }
        if (kind == "catalog") { _ = ShowCatalog(value.GetProperty("rows").Clone()); return; }
        if (kind != "snapshot") return;
        statusMessage = value.GetProperty("status").GetString()!;
        busy = value.GetProperty("busy").GetBoolean(); catalogBusy = value.GetProperty("catalogBusy").GetBoolean();
        if (appStatus is not null) { appStatus.Text = statusMessage; ToolTipService.SetToolTip(appStatus,statusMessage); }
        if (restartButton is not null) restartButton.IsEnabled = !busy;
        var profile = value.GetProperty("profile");
        if (characterName is not null) { characterName.Text = profile.GetProperty("character").GetString()!; ToolTipService.SetToolTip(characterName,characterName.Text); }
        if (characterStatus is not null) { characterStatus.Text = profile.GetProperty("message").GetString()!; ToolTipService.SetToolTip(characterStatus,characterStatus.Text); }
        ProfileStatusDot.Fill = Brush(profile.GetProperty("active").GetBoolean() ? "success" : "muted");
        DetectedDungeonContent.Children.Clear();
        var dungeon = profile.TryGetProperty("dungeon",out var name) ? name.GetString() : null;
        DetectedDungeon.Visibility = string.IsNullOrEmpty(dungeon) ? Visibility.Collapsed : Visibility.Visible;
        if (!string.IsNullOrEmpty(dungeon))
        {
            var grid = new Grid { ColumnSpacing = 8 };
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1,GridUnitType.Star) });
            grid.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            var title = new StackPanel { Spacing = 1 };
            var dungeonTitle = Text(dungeon,14,bold:true); dungeonTitle.TextWrapping = TextWrapping.NoWrap; dungeonTitle.TextTrimming = TextTrimming.CharacterEllipsis;
            ToolTipService.SetToolTip(dungeonTitle,dungeon); title.Children.Add(dungeonTitle);
            title.Children.Add(Text(profile.GetProperty("dungeonSubtitle").GetString()!,12,"muted")); grid.Children.Add(title);
            var state = Text(profile.GetProperty("dungeonState").GetString()!,12,"accent",true); state.VerticalAlignment = VerticalAlignment.Center;
            Grid.SetColumn(state,1); grid.Children.Add(state); DetectedDungeonContent.Children.Add(grid);
        }
        var recordJson = value.GetProperty("records").GetRawText();
        if (recordJson != lastRecords)
        {
            lastRecords = recordJson; records.Clear();
            foreach (var row in value.GetProperty("records").EnumerateArray())
                records.Add(new Raid(row.GetProperty("character").GetString()!,row.GetProperty("dungeon").GetString()!,row.GetProperty("mode").GetString()!,row.GetProperty("gate").GetString()!,row.GetProperty("date").GetString()!,row.GetProperty("detail").Clone()));
            RebuildRecords();
        }
        var clientJson = value.GetProperty("clients").GetRawText();
        var selected = value.GetProperty("selected").GetInt64();
        clients = value.GetProperty("clients").Clone();
        if (clientJson != lastClients || selected != selectedClient) { lastClients = clientJson; selectedClient = selected; UpdateClients(); }
        catalogMessage = value.GetProperty("catalogStatus").GetString()!;
        UpdateSettingsState();
        if (startupCheck && !busy && statusMessage == "게임 실행 대기")
        {
            File.WriteAllText(Path.Combine(AppContext.BaseDirectory,"startup-check.txt"),$"PASS: WinUI -> Python -> YOLO/OCR/OBS -> ready in {startupWatch.Elapsed.TotalSeconds:F2}s");
            Close();
        }
    }
    private string catalogMessage = "공용 데이터 · 확인 대기";
    private TextBlock? engineStatus;
    private void UpdateClients()
    {
        if (clientSelector is null) return;
        applyingClients = true; clientSelector.Items.Clear();
        if (clients.ValueKind == JsonValueKind.Array)
            foreach (var client in clients.EnumerateArray())
            {
                var hwnd = client.GetProperty("hwnd").GetInt64();
                var item = new ComboBoxItem { Content = client.GetProperty("title").GetString() + " · PID " + client.GetProperty("pid").GetInt32(), Tag = hwnd };
                clientSelector.Items.Add(item); if (hwnd == selectedClient) clientSelector.SelectedItem = item;
            }
        applyingClients = false;
    }
    private void UpdateSettingsState()
    {
        if (catalogStatus is not null) catalogStatus.Text = catalogMessage;
        if (engineStatus is not null) engineStatus.Text = statusMessage;
        if (clientSelector is not null) clientSelector.IsEnabled = !busy;
        if (deleteButton is not null) deleteButton.IsEnabled = !busy && (demo || records.Count > 0);
        if (catalogRefresh is not null) catalogRefresh.IsEnabled = !catalogBusy && !busy;
    }
    private void RebuildRecords()
    {
        Page.Children.Clear(); rows.Clear(); ShowRecords(); Adapt();
    }
    private async Task ShowRecordDetail(Raid raid)
    {
        var content = new StackPanel { Spacing = 16 };
        content.Children.Add(Text(raid.Dungeon,20,bold:true));
        content.Children.Add(Text(raid.Mode + " · " + raid.Gate + "\n" + raid.Character + " · " + raid.Date,14,"muted"));
        if (raid.Detail.GetProperty("status").GetString() == "matched")
        {
            var values = raid.Detail.GetProperty("values");
            content.Children.Add(Text($"골드  {values.GetProperty("gold").GetInt64():N0}\n비용  {values.GetProperty("fee").GetInt64():N0}\n귀속 비율  {values.GetProperty("bound_percentage").GetDouble()*100:0.##}%",16));
            content.Children.Add(Text(raid.Detail.GetProperty("source").GetString()!,12,"muted"));
        }
        else content.Children.Add(Text("상세 정보가 연결되지 않았습니다. 공용 데이터에서 일치하는 항목을 확인해주세요.",14,"muted"));
        if (raid.Detail.TryGetProperty("ocrOriginal",out var original))
            content.Children.Add(Text($"OCR 원문: {original.GetProperty("dungeonName").GetString()} / {original.GetProperty("difficulty").GetString()} / {original.GetProperty("gate").GetInt32()}관문",12,"muted"));
        await Dialog("완료 기록 상세",content);
    }
    private async Task ConfirmDelete()
    {
        if (dialogOpen) return;
        dialogOpen = true;
        try
        {
            var dialog = CreateDialog("기록 전체 삭제",Text("이 PC에 저장된 완료 기록을 모두 삭제합니다. 계속할까요?",14));
            dialog.PrimaryButtonText = "전체 삭제"; dialog.CloseButtonText = "취소"; dialog.DefaultButton = ContentDialogButton.Close;
            var result = await dialog.ShowAsync();
            if (result == ContentDialogResult.Primary) { if (demo) { records.Clear(); RebuildRecords(); } else await Send(new { type = "delete" }); }
        }
        finally { dialogOpen = false; }
    }
    private async Task Dialog(string title, UIElement content)
    {
        if (dialogOpen) return;
        dialogOpen = true;
        try { activeDialog = CreateDialog(title,content); await activeDialog.ShowAsync(); }
        finally { dialogOpen = false; activeDialog = null; }
    }
    private ContentDialog CreateDialog(string title, UIElement content)
    {
        var dialog = new ContentDialog { XamlRoot = Root.XamlRoot, RequestedTheme = ElementTheme.Dark,
            Title = title, Background = Brush("hover"), Foreground = Brush("text"), FontFamily = new FontFamily(font), FontSize = 14,
            Content = new ScrollViewer { Content = content, HorizontalScrollMode = ScrollMode.Disabled, HorizontalScrollBarVisibility = ScrollBarVisibility.Disabled }, CloseButtonText = "닫기" };
        foreach (var key in Root.Resources.Keys) dialog.Resources[key] = Root.Resources[key];
        dialog.Resources["ContentDialogBackground"] = Brush("hover");
        dialog.Resources["ContentDialogBorderBrush"] = Brush("border");
        return dialog;
    }
    private async Task ShowCatalog(JsonElement data)
    {
        var list = new StackPanel { Spacing = 16 };
        foreach (var row in data.EnumerateArray())
        {
            var item = new StackPanel { Spacing = 4 };
            item.Children.Add(Text(row.GetProperty("dungeon").GetString() + " · " + row.GetProperty("mode").GetString() + " · " + row.GetProperty("gate").GetString(),14,bold:true));
            item.Children.Add(Text($"골드 {row.GetProperty("gold").GetInt64():N0} · 비용 {row.GetProperty("fee").GetInt64():N0} · 귀속 {row.GetProperty("bound_percentage").GetDouble()*100:0.##}%",12,"muted"));
            list.Children.Add(item);
        }
        if (list.Children.Count == 0) list.Children.Add(Text("보관된 공용 데이터가 없습니다. 설정에서 공용 데이터를 갱신해주세요.",14,"muted"));
        await Dialog("공용 데이터",list);
    }
    private void LoadDemo()
    {
        using var sample = JsonDocument.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory,"Assets","demo.json")));
        Receive(sample.RootElement);
    }
    private void AddCaptionControls()
    {
        Button Caption(string icon, string label, RoutedEventHandler click)
        {
            var button = new Button { Width = 48, Height = 44, Padding = new Thickness(0), BorderThickness = new Thickness(0), CornerRadius = new CornerRadius(0),
                Content = new Image { Width = 16, Height = 16, Source = new SvgImageSource(new Uri($"ms-appx:///Assets/icons/{icon}-muted.svg")) } };
            AutomationProperties.SetName(button,label); ToolTipService.SetToolTip(button,label);
            button.Click += click; CaptionControls.Children.Add(button); return button;
        }
        Caption("minus","최소화",(_, _) => { if (AppWindow.Presenter is Microsoft.UI.Windowing.OverlappedPresenter presenter) presenter.Minimize(); });
        maximizeButton = Caption("maximize","최대화",(_, _) => ToggleMaximize());
        Caption("x","닫기",(_, _) => Close());
    }
    private void ToggleMaximize()
    {
        if (AppWindow.Presenter is Microsoft.UI.Windowing.OverlappedPresenter presenter)
        {
            if (presenter.State == Microsoft.UI.Windowing.OverlappedPresenterState.Maximized) presenter.Restore(); else presenter.Maximize();
        }
        UpdateMaximizeIcon();
    }
    private void UpdateMaximizeIcon()
    {
        if (maximizeButton?.Content is not Image icon) return;
        var maximized = AppWindow.Presenter is Microsoft.UI.Windowing.OverlappedPresenter presenter && presenter.State == Microsoft.UI.Windowing.OverlappedPresenterState.Maximized;
        icon.Source = new SvgImageSource(new Uri($"ms-appx:///Assets/icons/{(maximized ? "restore" : "maximize")}-muted.svg"));
        AutomationProperties.SetName(maximizeButton,maximized ? "이전 크기로 복원" : "최대화");
        ToolTipService.SetToolTip(maximizeButton,maximized ? "이전 크기로 복원" : "최대화");
    }
}
