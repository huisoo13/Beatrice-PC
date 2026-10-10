using System;
using System.Collections.Generic;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Automation.Provider;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace BeatricePC;
public partial class MainWindow
{
    private readonly Dictionary<string,StackPanel> settingsSections = new();
    private readonly Dictionary<string,Button> settingsMenuItems = new();
    private string selectedSettingsSection = "게임 클라이언트";
    private void BuildSettingsNavigation()
    {
        SettingsNavigation.Children.Clear(); settingsMenuItems.Clear();
        SettingsNavigation.Children.Add(Text("설정",20,bold:true));
        void Group(string label,params string[] items)
        {
            var group = new StackPanel { Spacing = 4 };
            var heading = Text(label,12,"muted"); heading.Margin = new Thickness(12,0,12,4); group.Children.Add(heading);
            foreach (var item in items)
            {
                var button = new Button { Content = Text(item,14), Tag = item, MinHeight = 44, Padding = new Thickness(12,8,12,8),
                    HorizontalAlignment = HorizontalAlignment.Stretch, HorizontalContentAlignment = HorizontalAlignment.Left,
                    BorderThickness = new Thickness(0), CornerRadius = new CornerRadius(8), Background = Brush("sidebar") };
                AutomationProperties.SetName(button,item + " 설정으로 이동");
                button.Click += (_,_) => ShowSettingsSection(item);
                group.Children.Add(button); settingsMenuItems[item] = button;
            }
            SettingsNavigation.Children.Add(group);
        }
        Group("앱 관리","게임 클라이언트","공용 데이터","기록 관리");
        Group("계정 및 연동","로스트아크","Google Drive");
        ShowSettingsSection(selectedSettingsSection);
    }
    private void SelectSettingsMenu(string selected)
    {
        foreach (var (name,button) in settingsMenuItems)
        {
            button.Background = Brush(name == selected ? "accentTint" : "sidebar");
            if (button.Content is TextBlock text) text.Foreground = Brush(name == selected ? "text" : "muted");
        }
    }
    private void ShowSettingsSection(string selected)
    {
        if (!settingsSections.TryGetValue(selected,out var section)) return;
        if (selectedSettingsSection == "로스트아크" && selected != selectedSettingsSection) _ = SaveLostArkApiKey();
        selectedSettingsSection = selected; SelectSettingsMenu(selected);
        if (SettingsContent.Children.Count == 1 && ReferenceEquals(SettingsContent.Children[0],section)) return;
        SettingsContent.Children.Clear(); SettingsContent.Children.Add(section);
        Adapt(); SettingsContent.UpdateLayout(); SettingsScroll.ChangeView(null,0,null,true);
    }
    private async Task ValidateSettingsTextNavigation()
    {
        if (settingsOpen) DismissSettings(false);
        ToggleSettings(); await Task.Delay(100); Root.UpdateLayout();
        if (settingsMenuItems.Count != 5 || SettingsNavigation.Children.OfType<StackPanel>().Count() != 2 ||
            settingsMenuItems.Values.Any(button => button.Content is not TextBlock)) throw new InvalidOperationException("설정 텍스트 메뉴 및 분류 생성 실패");
        foreach (var name in new[]{"로스트아크","Google Drive","공용 데이터","기록 관리","게임 클라이언트"})
        {
            var button = settingsMenuItems[name];
            ((IInvokeProvider)new ButtonAutomationPeer(button).GetPattern(PatternInterface.Invoke)).Invoke();
            await Task.Delay(100);
            if (selectedSettingsSection != name || SettingsContent.Children.Count != 1 || !ReferenceEquals(SettingsContent.Children[0],settingsSections[name]))
                throw new InvalidOperationException("설정 메뉴별 화면 전환 실패: " + name);
            var content = SettingsContent.Children[0];
            ((IInvokeProvider)new ButtonAutomationPeer(button).GetPattern(PatternInterface.Invoke)).Invoke();
            if (!ReferenceEquals(content,SettingsContent.Children[0])) throw new InvalidOperationException("같은 설정 메뉴 재선택 상태 유지 실패");
        }
        DismissSettings(false);
    }
}
