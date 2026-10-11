using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Media;

namespace BeatricePC;
public partial class MainWindow
{
    private JsonElement? obs;
    private TextBlock? obsStatusText, obsErrorText;
    private void AddObsSettings()
    {
        var section = Section("OBS","게임 화면을 감지하기 위해 사용됩니다.");
        var clientGroup = new StackPanel { Spacing = 12 };
        section.Children.Add(clientGroup);
        clientGroup.Children.Add(Text("감지 중인 클라이언트",14,bold:true));
        clientSelector = new ComboBox { HorizontalAlignment = HorizontalAlignment.Stretch, PlaceholderText = "게임 실행 대기", MinHeight = 44, FontFamily = new FontFamily(font), FontSize = 14 };
        AutomationProperties.SetName(clientSelector,"분석할 게임 클라이언트");
        clientSelector.SelectionChanged += async (_, _) => {
            if (!applyingClients && clientSelector.SelectedItem is ComboBoxItem item && item.Tag is long hwnd)
                await Send(new { type = "select", hwnd });
        };
        clientGroup.Children.Add(clientSelector); UpdateClients();
        engineStatus = Text(statusMessage,12,"muted"); clientGroup.Children.Add(engineStatus);
        var engineGroup = new StackPanel { Spacing = 12 };
        section.Children.Add(engineGroup);
        engineGroup.Children.Add(Text("내장 OBS 엔진",14,bold:true));
        obsStatusText = Text("상태 확인 대기",14,"muted");
        engineGroup.Children.Add(obsStatusText);
        var errorGroup = new StackPanel { Spacing = 12 };
        section.Children.Add(errorGroup);
        errorGroup.Children.Add(Text("오류 메시지",14,bold:true));
        obsErrorText = Text("없음",14,"muted");
        errorGroup.Children.Add(obsErrorText);
        UpdateObsSettings();
    }
    private void UpdateObsSettings()
    {
        string Read(string key,string fallback) => obs is JsonElement value && value.ValueKind == JsonValueKind.Object &&
            value.TryGetProperty(key,out var item) && item.ValueKind == JsonValueKind.String ? item.GetString() ?? fallback : fallback;
        var error = Read("error","");
        if (obsStatusText is not null) obsStatusText.Text = Read("status","상태 확인 대기");
        if (obsErrorText is not null) {
            obsErrorText.Text = string.IsNullOrWhiteSpace(error) ? "없음" : error;
            obsErrorText.Foreground = Brush(string.IsNullOrWhiteSpace(error) ? "muted" : "danger");
        }
    }
}
