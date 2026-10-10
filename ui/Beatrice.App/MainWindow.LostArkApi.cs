using System;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace BeatricePC;
public partial class MainWindow
{
    private JsonElement lostArkApi;
    private PasswordBox? lostArkApiInput;
    private TextBlock? lostArkApiStatus;
    private bool lostArkApiSaving, lostArkApiResetting, lostArkApiFeedback;
    private Button? lostArkApiVerify, lostArkApiReset;

    private void AddLostArkApiSettings()
    {
        var section = Section("로스트아크");
        section.Children.Add(Text("API Key",14,bold:true));
        lostArkApiInput = new PasswordBox {
            PlaceholderText = Flag(lostArkApi,"configured") ? "새 키를 입력하면 기존 키를 변경합니다" : "API Key 입력",
            PasswordRevealMode = PasswordRevealMode.Hidden, MaxLength = 16384, MinHeight = 44, Height = 44, Padding = new Thickness(12,0,12,0),
            VerticalContentAlignment = VerticalAlignment.Center,
            HorizontalAlignment = HorizontalAlignment.Stretch, FontFamily = new FontFamily(font), FontSize = 14,
            Background = Brush("surface"), Foreground = Brush("text"), BorderBrush = Brush("border")
        };
        foreach (var state in new[]{"", "PointerOver", "Focused", "Disabled"}) {
            lostArkApiInput.Resources["TextControlBackground" + state] = Brush(state == "PointerOver" ? "hover" : "surface");
            lostArkApiInput.Resources["TextControlForeground" + state] = Brush("text");
            lostArkApiInput.Resources["TextControlBorderBrush" + state] = Brush(state == "Focused" ? "accent" : "border");
            lostArkApiInput.Resources["TextControlPlaceholderForeground" + state] = Brush("muted");
        }
        lostArkApiInput.Loaded += (_,_) => CenterLostArkApiInput(lostArkApiInput);
        AutomationProperties.SetName(lostArkApiInput,"로스트아크 API Key");
        lostArkApiInput.PasswordChanged += (_,_) => UpdateLostArkApiSettings();
        lostArkApiInput.LostFocus += async (_,_) => await SaveLostArkApiKey();
        lostArkApiInput.KeyDown += async (_,args) => {
            if (args.Key != Windows.System.VirtualKey.Enter) return;
            args.Handled = true; await SaveLostArkApiKey();
        };
        section.Children.Add(lostArkApiInput);
        var actions = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 8 };
        lostArkApiVerify = Action("검증",(_,_) => {});
        lostArkApiVerify.IsEnabled = false;
        lostArkApiReset = Action("초기화",async (_,_) => {
            lostArkApiResetting = lostArkApiFeedback = true;
            lostArkApiInput.Password = ""; UpdateLostArkApiSettings();
            await SendLostArkApiAction("lostark_api_clear");
        });
        actions.Children.Add(lostArkApiVerify); actions.Children.Add(lostArkApiReset); section.Children.Add(actions);
        lostArkApiStatus = Text("",14,"muted");
        AutomationProperties.SetLiveSetting(lostArkApiStatus,AutomationLiveSetting.Polite);
        section.Children.Add(lostArkApiStatus);
    }

    private static void CenterLostArkApiInput(DependencyObject parent)
    {
        for (var i = 0; i < VisualTreeHelper.GetChildrenCount(parent); i++) {
            var child = VisualTreeHelper.GetChild(parent,i);
            // WinUI's default PasswordBox does not bind VerticalContentAlignment to these parts.
            if (child is FrameworkElement element && (element.Name == "ContentElement" || element.Name == "PlaceholderTextContentPresenter"))
                element.VerticalAlignment = VerticalAlignment.Center;
            CenterLostArkApiInput(child);
        }
    }

    private async Task SaveLostArkApiKey()
    {
        if (demo || lostArkApiSaving || lostArkApiResetting || lostArkApiInput is null || string.IsNullOrWhiteSpace(lostArkApiInput.Password)) return;
        lostArkApiSaving = lostArkApiFeedback = true; UpdateLostArkApiSettings();
        try { await engine.SendAsync(new { type = "lostark_api_save", key = lostArkApiInput.Password }); }
        catch (Exception) {
            lostArkApiSaving = false;
            if (lostArkApiStatus is not null) { lostArkApiStatus.Text = "저장하지 못했습니다. 앱을 다시 실행한 뒤 시도해주세요."; lostArkApiStatus.Foreground = Brush("danger"); }
            UpdateLostArkApiControls();
        }
    }

    private async Task SendLostArkApiAction(string type)
    {
        try { if (!demo) await engine.SendAsync(new { type }); }
        catch (Exception) {
            lostArkApiResetting = false;
            UpdateLostArkApiControls();
            if (lostArkApiStatus is not null) { lostArkApiStatus.Text = "작업을 완료하지 못했습니다. 앱을 다시 실행해주세요."; lostArkApiStatus.Foreground = Brush("danger"); }
        }
    }

    private void ReceiveLostArkApiResult(JsonElement value)
    {
        var kind = value.GetProperty("type").GetString();
        lostArkApi = value.Clone(); lostArkApiFeedback = true;
        if (kind == "lostark_api_saved") lostArkApiSaving = false;
        if (kind == "lostark_api_cleared") lostArkApiResetting = lostArkApiSaving = false;
        if (Flag(value,"success") && (kind is "lostark_api_saved" or "lostark_api_cleared") && lostArkApiInput is not null) lostArkApiInput.Password = "";
        UpdateLostArkApiSettings();
        if (lostArkApiStatus is not null) lostArkApiStatus.Foreground = Brush(Flag(value,"success") ? "success" : "danger");
    }

    private void UpdateLostArkApiControls()
    {
        if (lostArkApiInput is not null) lostArkApiInput.IsEnabled = !lostArkApiSaving && !lostArkApiResetting;
        if (lostArkApiReset is not null) lostArkApiReset.IsEnabled = !demo && !lostArkApiResetting;
    }

    private void UpdateLostArkApiSettings()
    {
        UpdateLostArkApiControls();
        if (lostArkApiStatus is not null) {
            lostArkApiStatus.Visibility = lostArkApiFeedback ? Visibility.Visible : Visibility.Collapsed;
            lostArkApiStatus.Text = lostArkApiResetting ? "초기화하는 중…" : lostArkApiSaving ? "API Key를 저장하는 중…" : StateText(lostArkApi,"message","");
        }
        if (lostArkApiInput is not null) lostArkApiInput.PlaceholderText = Flag(lostArkApi,"configured") ? "새 키를 입력하면 기존 키를 변경합니다" : "API Key 입력";
    }
}
