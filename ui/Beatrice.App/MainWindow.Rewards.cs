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
public partial class MainWindow
{
    private JsonElement rewardData;
    private bool rewardsRequested;
    private Button? rewardRefresh;
    private Grid? rewardHeading;
    private StackPanel? rewardRefreshInfo;
    private TextBlock? rewardLastUpdated;
    private DispatcherTimer? rewardCooldownTimer;
    private DateTimeOffset rewardRefreshAvailableAt = DateTimeOffset.MinValue;
    private DateTimeOffset? lastRewardUpdate;
    private readonly Dictionary<string, bool> rewardExpanded = new();
    private readonly Dictionary<string, string> rewardModes = new();
    private readonly List<Grid> rewardTables = new();

    private async System.Threading.Tasks.Task RequestRewards()
    {
        if (demo)
        {
            using var sample = JsonDocument.Parse(System.IO.File.ReadAllText(System.IO.Path.Combine(AppContext.BaseDirectory,"Assets","demo-rewards.json")));
            AcceptRewards(sample.RootElement.Clone()); return;
        }
        if (!engine.IsRunning || rewardsRequested) return;
        rewardsRequested = true;
        try { await engine.SendAsync(new { type = "catalog" }); }
        catch (Exception error) { rewardsRequested = false; if (rewardRefresh is not null) ToolTipService.SetToolTip(rewardRefresh,"데이터 조회 실패: " + error.Message); }
    }
    private async System.Threading.Tasks.Task RefreshRewards()
    {
        if (busy || catalogBusy || DateTimeOffset.UtcNow < rewardRefreshAvailableAt) return;
        rewardRefreshAvailableAt = DateTimeOffset.UtcNow.AddMinutes(5);
        UpdateRewardRefresh();
        if (!demo) await Send(new { type = "catalog_refresh" });
        await RequestRewards();
        if (demo) lastRewardUpdate = DateTimeOffset.UtcNow;
        UpdateRewardRefresh();
    }
    private void UpdateRewardRefresh()
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
    private void AcceptRewards(JsonElement data)
    {
        rewardsRequested = false;
        var changed = rewardData.ValueKind != JsonValueKind.Array || rewardData.GetRawText() != data.GetRawText();
        rewardData = data.Clone();
        if (currentPage == "rewards" && (changed || rewardTables.Count == 0))
        { Page.Children.Clear(); ShowRewards(); Adapt(); }
    }
    private void ShowRewards()
    {
        rewardTables.Clear();
        rewardHeading = new Grid { ColumnSpacing = 12, RowSpacing = 8 };
        rewardHeading.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1,GridUnitType.Star) });
        rewardHeading.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        rewardHeading.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        rewardHeading.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        rewardHeading.Children.Add(Text("보상표",20,bold:true));
        rewardRefresh = new Button { Width = 20, Height = 20, MinWidth = 0, MinHeight = 0, Padding = new Thickness(0),
            Template = (ControlTemplate)Root.Resources["BareSettingsButton"],
            Content = new Image { Width = 12, Height = 12,
                Source = new Microsoft.UI.Xaml.Media.Imaging.SvgImageSource(new Uri("ms-appx:///Assets/icons/refresh-cw-muted.svg")) } };
        AutomationProperties.SetName(rewardRefresh,"보상표 새로고침");
        rewardRefresh.Click += async (_, _) => await RefreshRewards();
        rewardRefreshInfo = new StackPanel { Orientation = Orientation.Horizontal, Spacing = 4, VerticalAlignment = VerticalAlignment.Center, HorizontalAlignment = HorizontalAlignment.Right };
        rewardRefreshInfo.Children.Add(rewardRefresh);
        rewardLastUpdated = Text("마지막 갱신 —",12,"muted"); rewardLastUpdated.VerticalAlignment = VerticalAlignment.Center;
        rewardRefreshInfo.Children.Add(rewardLastUpdated);
        Grid.SetColumn(rewardRefreshInfo,1); rewardHeading.Children.Add(rewardRefreshInfo);
        if (rewardCooldownTimer is null)
        {
            rewardCooldownTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            rewardCooldownTimer.Tick += (_, _) => { UpdateRewardRefresh(); UpdateSettingsState(); };
            rewardCooldownTimer.Start();
        }
        UpdateRewardRefresh();
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
                AdaptRewardTables();
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
            expander = new Expander { Template = (ControlTemplate)Root.Resources["RewardExpanderTemplate"], Header = dungeonTitle, Content = detail, HorizontalAlignment = HorizontalAlignment.Stretch,
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
    private void ValidateRewardInteractions()
    {
        var list = (StackPanel)Page.Children[1];
        var first = (Expander)list.Children[0];
        var detail = (StackPanel)first.Content;
        var tabs = (VariableSizedWrapGrid)detail.Children[0];
        var matching = tabs.Children.OfType<ToggleButton>().First(b => (string)b.Tag == "매칭 모드");
        matching.IsChecked = true;
        var table = (Grid)((Grid)detail.Children[1]).Children[0];
        if (!table.Children.OfType<Border>().Any(c => c.Child is TextBlock t && t.Text == "50%")) throw new InvalidOperationException("난이도별 보상 전환 실패");
        first.IsExpanded = false; first.IsExpanded = true;
        RebuildRecords();
        if (currentPage != "rewards" || Page.Children[1] != list) throw new InvalidOperationException("기록 갱신 중 보상표 화면 변경");
        ShowPage("records"); ShowPage("rewards");
        first = (Expander)((StackPanel)Page.Children[1]).Children[0];
        tabs = (VariableSizedWrapGrid)((StackPanel)first.Content).Children[0];
        if (!first.IsExpanded || !tabs.Children.OfType<ToggleButton>().Any(b => (string)b.Tag == "매칭 모드" && b.IsChecked == true)) throw new InvalidOperationException("보상표 선택 상태 복구 실패");
        tabs.Children.OfType<ToggleButton>().First(b => (string)b.Tag == "하드").IsChecked = true;
    }
    private async System.Threading.Tasks.Task ValidateRewardMotion()
    {
        if (demo && rewardRefreshAvailableAt == DateTimeOffset.MinValue)
        {
            await RefreshRewards();
            var deadline = rewardRefreshAvailableAt;
            await RefreshRewards();
            if (deadline != rewardRefreshAvailableAt || rewardRefresh?.IsEnabled != false || lastRewardUpdate is null) throw new InvalidOperationException("새로고침 쿨타임/갱신 시간 검증 실패");
            rewardRefreshAvailableAt = DateTimeOffset.UtcNow.AddSeconds(-1); UpdateRewardRefresh();
            if (rewardRefresh?.IsEnabled != true) throw new InvalidOperationException("쿨타임 종료 활성화 실패");
        }
        Root.UpdateLayout();
        if (Page.Children.Count != 2 || rewardRefresh?.Content is not Image) throw new InvalidOperationException("보상표 안내 제거/새로고침 버튼 검증 실패");
        var list = (StackPanel)Page.Children[1];
        var first = (Expander)list.Children[0];
        var second = (Expander)list.Children[1];
        var initial = first.ActualHeight;
        var closedHeight = ((TextBlock)first.Header).ActualHeight + first.Padding.Top + first.Padding.Bottom;
        foreach (var dungeon in list.Children.OfType<Expander>())
        {
            var modes = (VariableSizedWrapGrid)((StackPanel)dungeon.Content).Children[0];
            foreach (var button in modes.Children.OfType<ToggleButton>())
                if (button.Height != 26 || button.CornerRadius.TopLeft != 13 || (dungeon.IsExpanded && Math.Abs(button.ActualHeight-26) > .5))
                    throw new InvalidOperationException("난이도 캡슐 높이/반경 불일치");
        }
        var samples = new List<double>();
        void Sample(object? sender, object args)
        {
            Root.UpdateLayout();
            var firstTop = first.TransformToVisual(list).TransformPoint(new Windows.Foundation.Point()).Y;
            var secondTop = second.TransformToVisual(list).TransformPoint(new Windows.Foundation.Point()).Y;
            if (Math.Abs(secondTop-firstTop-first.ActualHeight-8) > 1) throw new InvalidOperationException("펼침 애니메이션과 아래 목록 간격 불일치");
            samples.Add(first.ActualHeight);
        }
        Microsoft.UI.Xaml.Media.CompositionTarget.Rendering += Sample;
        try
        {
            first.IsExpanded = false;
            await System.Threading.Tasks.Task.Delay(300);
            if (SynchronizedExpander.For(first).ChevronAngle != 0) throw new InvalidOperationException("접힘 화살표 방향 변경 실패");
            second.IsExpanded = true;
            await System.Threading.Tasks.Task.Delay(250);
            if (SynchronizedExpander.For(second).ChevronAngle != 180) throw new InvalidOperationException("다른 목록 펼침 화살표 방향 변경 실패");
            second.IsExpanded = false;
            await System.Threading.Tasks.Task.Delay(200);
            if (SynchronizedExpander.For(second).ChevronAngle != 0) throw new InvalidOperationException("다른 목록 접힘 화살표 방향 변경 실패");
            if (!samples.Any(h => h > closedHeight+1 && h < initial-1)) throw new InvalidOperationException("펼침 높이의 중간 프레임이 없습니다.");
            first.IsExpanded = true;
            await System.Threading.Tasks.Task.Delay(70);
            first.IsExpanded = false;
            await System.Threading.Tasks.Task.Delay(50);
            first.IsExpanded = true;
            await System.Threading.Tasks.Task.Delay(300);
            Root.UpdateLayout();
            if (SynchronizedExpander.For(first).ChevronAngle != 180) throw new InvalidOperationException("펼침 화살표 방향 변경 실패");
            if (Math.Abs(first.ActualHeight-initial) > 1) throw new InvalidOperationException("빠른 펼침 전환 후 높이 복구 실패");
            SynchronizedExpander.For(first).ForceReducedMotion = true; first.IsExpanded = false; Root.UpdateLayout();
            if (first.ActualHeight > closedHeight+1) throw new InvalidOperationException("동작 줄이기 즉시 접힘 실패");
            first.IsExpanded = true; Root.UpdateLayout(); SynchronizedExpander.For(first).ForceReducedMotion = false;
        }
        finally { Microsoft.UI.Xaml.Media.CompositionTarget.Rendering -= Sample; }
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
    private void AdaptRewardTables()
    {
        var small = Root.ActualWidth <= 560;
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