using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Controls.Primitives;

namespace BeatricePC;
internal sealed class RewardsView
{
    private readonly StackPanel Page;
    private readonly ViewTheme theme;
    private readonly Func<System.Threading.Tasks.Task> refresh;
    private double lastWidth = 1280;
    private string font => theme.Font;
    private Microsoft.UI.Xaml.Media.SolidColorBrush Brush(string key) => theme.Brush(key);
    private TextBlock Text(string value, int size = 16, string color = "text", bool bold = false) => theme.Text(value,size,color,bold);
    private Button? rewardRefresh;
    private Grid? rewardHeading;
    private StackPanel? rewardRefreshInfo;
    private TextBlock? rewardLastUpdated;
    private readonly Dictionary<string, bool> rewardExpanded = new();
    private readonly Dictionary<string, string> rewardModes = new();
    private readonly List<Grid> rewardTables = new();
    internal Button? RefreshButton => rewardRefresh;
    internal TextBlock? LastUpdated => rewardLastUpdated;
    internal IReadOnlyList<Grid> Tables => rewardTables;
    public RewardsView(StackPanel page, ViewTheme theme, Func<System.Threading.Tasks.Task> refresh)
    { Page = page; this.theme = theme; this.refresh = refresh; }
    public void UpdateRefresh(bool busy, bool catalogBusy, DateTimeOffset rewardRefreshAvailableAt, DateTimeOffset? lastRewardUpdate, string catalogMessage)
    {
        if (rewardRefresh is null) return;
        var remaining = rewardRefreshAvailableAt - DateTimeOffset.UtcNow;
        var remainingSeconds = (int)Math.Ceiling(Math.Max(0,remaining.TotalSeconds));
        rewardRefresh.IsEnabled = !busy && !catalogBusy && remaining <= TimeSpan.Zero;
        rewardRefresh.Opacity = 1;
        ToolTipService.SetToolTip(rewardRefresh,catalogBusy ? "보상표 갱신 중…" : remaining > TimeSpan.Zero ? $"새로고침 가능까지 {remainingSeconds/60:00}:{remainingSeconds%60:00}" : "보상표 새로고침");
        if (rewardLastUpdated is not null)
        {
            rewardLastUpdated.Text = lastRewardUpdate is DateTimeOffset time ? "마지막 갱신 " + time.ToLocalTime().ToString("yy. M. d tt hh:mm",CultureInfo.InvariantCulture) : "마지막 갱신 —";
            ToolTipService.SetToolTip(rewardLastUpdated,lastRewardUpdate?.ToLocalTime().ToString("yyyy.MM.dd HH:mm:ss") ?? "갱신 기록 없음");
        }
        AutomationProperties.SetHelpText(rewardRefresh,catalogMessage);
    }
    public void Render(JsonElement rewardData)
    {
        rewardTables.Clear();
        rewardHeading = new Grid { ColumnSpacing = 12, RowSpacing = 8 };
        rewardHeading.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1,GridUnitType.Star) });
        rewardHeading.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        rewardHeading.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        rewardHeading.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        rewardHeading.Children.Add(Text("보상표",20,bold:true));
        rewardRefresh = new Button { Width = 20, Height = 20, MinWidth = 0, MinHeight = 0, Padding = new Thickness(0),
            Template = (ControlTemplate)theme.Resources["BareSettingsButton"],
            Content = new Image { Width = 12, Height = 12,
                Source = new Microsoft.UI.Xaml.Media.Imaging.SvgImageSource(new Uri("ms-appx:///Assets/icons/refresh-cw-muted.svg")) } };
        AutomationProperties.SetName(rewardRefresh,"보상표 새로고침");
        rewardRefresh.Click += async (_, _) => await refresh();
        rewardRefreshInfo = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 4, VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Right };
        rewardRefreshInfo.Children.Add(rewardRefresh);
        rewardLastUpdated = Text("마지막 갱신 —",12,"muted"); rewardLastUpdated.VerticalAlignment = VerticalAlignment.Center;
        rewardRefreshInfo.Children.Add(rewardLastUpdated);
        Grid.SetColumn(rewardRefreshInfo,1); rewardHeading.Children.Add(rewardRefreshInfo);
        Page.Children.Add(rewardHeading);
        var list = new StackPanel { Spacing = 8 };
        Page.Children.Add(list);
        if (rewardData.ValueKind != JsonValueKind.Array)
        { list.Children.Add(Text("공용 데이터를 불러오는 중…",14,"muted")); return; }
        foreach (var dungeon in rewardData.EnumerateArray().GroupBy(r => r.GetProperty("dungeon").GetString()!))
        {
            var name = dungeon.Key;
            var modes = dungeon.GroupBy(r => r.GetProperty("mode").GetString()!).ToList();
            var selected = rewardModes.TryGetValue(name,out var mode) && modes.Any(m => m.Key == mode) ? mode : modes[0].Key;
            var detail = new StackPanel { Spacing = 0 };
            var tabs = new VariableSizedWrapGrid { Orientation = Orientation.Horizontal, ItemWidth = 1, ItemHeight = 30, Margin = new Thickness(16,0,16,12), HorizontalAlignment = HorizontalAlignment.Stretch };
            var tableHost = new Grid();
            Expander? expander = null;
            void SelectMode(string value)
            {
                rewardModes[name] = value;
                foreach (var button in tabs.Children.OfType<ToggleButton>())
                {
                    var active = (string)button.Tag == value;
                    button.IsChecked = active; button.Background = Brush(active ? "accentTint" : "hover");
                    button.Foreground = Brush(active ? "accent" : "muted");
                }
                foreach (var old in tableHost.Children.OfType<Grid>()) rewardTables.Remove(old);
                tableHost.Children.Clear();
                var table = RewardTable(modes.First(m => m.Key == value)); tableHost.Children.Add(table); rewardTables.Add(table);
                Adapt(lastWidth);
                if (expander is not null) SynchronizedExpander.For(expander).RefreshContent();
            }
            foreach (var group in modes)
            {
                var button = new ToggleButton { Content = group.Key, Tag = group.Key, FontFamily = new Microsoft.UI.Xaml.Media.FontFamily(font), FontSize = 12,
                    Padding = new Thickness(10,4,10,4), Height = 26, MinHeight = 26, VerticalAlignment = VerticalAlignment.Center, MinWidth = 0, CornerRadius = new CornerRadius(13), BorderThickness = new Thickness(0), Margin = new Thickness(0,0,4,0) };
                AutomationProperties.SetName(button,name + " " + group.Key);
                var measure = Text(group.Key,12); measure.Measure(new Windows.Foundation.Size(double.PositiveInfinity,double.PositiveInfinity));
                VariableSizedWrapGrid.SetColumnSpan(button,(int)Math.Ceiling(measure.DesiredSize.Width + 24));
                foreach (var state in new[]{"","PointerOver","Pressed"})
                {
                    button.Resources["ToggleButtonBackground" + state] = Brush("hover");
                    button.Resources["ToggleButtonForeground" + state] = Brush("muted");
                    button.Resources["ToggleButtonBackgroundChecked" + state] = Brush("accentTint");
                    button.Resources["ToggleButtonForegroundChecked" + state] = Brush("accent");
                }
                button.Checked += (_, _) => { if (!rewardModes.TryGetValue(name,out var current) || current != group.Key) SelectMode(group.Key); };
                button.Unchecked += (_, _) => { if (rewardModes.TryGetValue(name,out var current) && current == group.Key) button.IsChecked = true; };
                button.Click += (_, _) => SelectMode(group.Key); tabs.Children.Add(button);
            }
            detail.Children.Add(tabs); detail.Children.Add(tableHost);
            var dungeonTitle = Text(name,14,bold:true);
            expander = new Expander { Template = (ControlTemplate)theme.Resources["RewardExpanderTemplate"], Header = dungeonTitle, Content = detail, HorizontalAlignment = HorizontalAlignment.Stretch,
                HorizontalContentAlignment = HorizontalAlignment.Stretch, MinWidth = 0, MinHeight = 0, Padding = new Thickness(16,12,16,12),
                CornerRadius = new CornerRadius(12), Background = Brush("sidebar"), BorderThickness = new Thickness(0),
                IsExpanded = rewardExpanded.TryGetValue(name,out var expanded) ? expanded : list.Children.Count == 0 };
            AutomationProperties.SetName(expander,name);
            foreach (var key in new[]{"ExpanderHeaderBackground","ExpanderContentBackground"}) expander.Resources[key] = Brush("sidebar");
            foreach (var key in new[]{"ExpanderHeaderForeground","ExpanderHeaderForegroundPointerOver","ExpanderHeaderForegroundPressed","ExpanderChevronForeground","ExpanderChevronPointerOverForeground","ExpanderChevronPressedForeground"}) expander.Resources[key] = Brush("text");
            foreach (var key in new[]{"ExpanderHeaderBorderBrush","ExpanderHeaderBorderPointerOverBrush","ExpanderHeaderBorderPressedBrush","ExpanderContentBorderBrush","ExpanderChevronBackground","ExpanderChevronPointerOverBackground","ExpanderChevronPressedBackground"}) expander.Resources[key] = new Microsoft.UI.Xaml.Media.SolidColorBrush(Microsoft.UI.Colors.Transparent);
            expander.Resources["ExpanderHeaderBorderThickness"] = new Thickness(0);
            expander.Expanding += (_, _) => rewardExpanded[name] = true;
            expander.Collapsed += (_, _) => rewardExpanded[name] = false;
            SynchronizedExpander.For(expander);
            list.Children.Add(expander); SelectMode(selected);
        }
        if (list.Children.Count == 0) list.Children.Add(Text("보관된 공용 데이터가 없습니다. 설정에서 공용 데이터를 갱신해주세요.",14,"muted"));
    }
    private Grid RewardTable(IEnumerable<JsonElement> data)
    {
        var table = new Grid();
        for (var i = 0; i < 4; i++) table.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1,GridUnitType.Star) });
        var labels = new[]{"관문","골드","비용","귀속 비율"};
        void AddRow(string[] values, bool header = false)
        {
            var index = table.RowDefinitions.Count; table.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
            for (var i = 0; i < 4; i++)
            {
                var text = Text(values[i],header ? 12 : 14,header || i >= 2 ? "muted" : "text",!header && i == 1);
                text.HorizontalAlignment = i == 0 ? HorizontalAlignment.Left : HorizontalAlignment.Right;
                text.VerticalAlignment = VerticalAlignment.Center;
                var cell = new Border { Padding = new Thickness(16,header ? 0 : 8,16,8), MinHeight = header ? 26 : 44, Child = text };
                if (!header) { var line = Brush("border"); line.Opacity = .55; cell.BorderBrush = line; cell.BorderThickness = new Thickness(0,1,0,0); }
                Grid.SetColumn(cell,i); Grid.SetRow(cell,index); table.Children.Add(cell);
            }
        }
        AddRow(labels,true);
        foreach (var row in data.OrderBy(r => GateOrder(r.GetProperty("gate").GetString()!)))
        {
            var gate = row.GetProperty("gate").GetString()!;
            AddRow(new[]{int.TryParse(gate,out var number) ? number + "관문" : gate,
                row.GetProperty("gold").GetInt64().ToString("N0",CultureInfo.GetCultureInfo("ko-KR")),
                row.GetProperty("fee").GetInt64().ToString("N0",CultureInfo.GetCultureInfo("ko-KR")),
                (row.GetProperty("bound_percentage").GetDouble()*100).ToString("0.##",CultureInfo.InvariantCulture) + "%"});
        }
        return table;
    }
    private static int GateOrder(string value) => int.TryParse(new string(value.Where(char.IsDigit).ToArray()),out var number) ? number : int.MaxValue;
    public void Adapt(double width)
    {
        lastWidth = width;
        var small = width <= 560;
        if (rewardRefreshInfo is not null)
        {
            Grid.SetColumn(rewardRefreshInfo,small ? 0 : 1); Grid.SetRow(rewardRefreshInfo,small ? 1 : 0);
            Grid.SetColumnSpan(rewardRefreshInfo,small ? 2 : 1);
        }
        foreach (var table in rewardTables)
            foreach (var cell in table.Children.OfType<Border>())
            {
                cell.Padding = new Thickness(small ? 5 : 16,Grid.GetRow(cell) == 0 ? 0 : 8,small ? 5 : 16,8);
                if (cell.Child is TextBlock text) text.FontSize = small || Grid.GetRow(cell) == 0 ? 12 : 14;
            }
    }
}
