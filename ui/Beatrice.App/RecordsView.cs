using System;
using System.Globalization;
using System.Collections.Generic;
using System.Linq;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Documents;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;

namespace BeatricePC;
internal sealed class RecordsView : IDisposable
{
    private readonly StackPanel Page;
    private readonly ViewTheme theme;
    private readonly Func<DateTime> clock;
    private readonly System.Action scrollToTop;
    private string font => theme.Font;
    private string semiboldFont => theme.SemiboldFont;
    private SolidColorBrush Brush(string key) => theme.Brush(key);
    private TextBlock Text(string value, int size = 16, string color = "text", bool bold = false) => theme.Text(value,size,color,bold);
    public event System.Action? Changed;
    internal int WeekOffset { get => recordWeekOffset; set => recordWeekOffset = value; }
    internal IReadOnlyList<Grid> LogRows => recordLogRows;
    internal Button? NewerWeekButton => newerWeekButton;
    internal Button? OlderWeekButton => olderWeekButton;
    internal TextBlock? WeekRange => recordWeekRange;
    public RecordsView(StackPanel page, ViewTheme theme, Func<DateTime> clock,
        System.Action scrollToTop)
    { Page = page; this.theme = theme; this.clock = clock; this.scrollToTop = scrollToTop; }
    public void Dispose() => recordWeekTimer?.Stop();

    private readonly List<TextBlock> recordDateLabels = new();
    private readonly List<Grid> recordLogRows = new();
    private int recordWeekOffset;
    private DateTime recordWeekAnchor;
    private Grid? recordWeekNavigation;
    private TextBlock? recordWeekRange;
    private Button? newerWeekButton, olderWeekButton;
    private DispatcherTimer? recordWeekTimer;
    private DateTime RecordNow => clock();
    private DateTime SelectedRecordWeek => RecordPresentation.WeekStart(RecordNow).AddDays(-7L*recordWeekOffset);
    public void Render(IReadOnlyList<Raid> records)
    {
        recordDateLabels.Clear(); recordLogRows.Clear();
        Page.Spacing = 12;
        var heading = new StackPanel { Spacing = 12 };
        heading.Children.Add(Text("완료 일지",20,bold:true));
        recordWeekNavigation = new Grid { ColumnSpacing = 12, RowSpacing = 8, HorizontalAlignment = HorizontalAlignment.Center };
        recordWeekNavigation.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(44) });
        recordWeekNavigation.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
        recordWeekNavigation.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(44) });
        recordWeekNavigation.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        recordWeekNavigation.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        olderWeekButton = WeekNavigationButton.Create(theme,true,"이전 주 기록 보기",()=>ChangeRecordWeek(1)); newerWeekButton = WeekNavigationButton.Create(theme,false,"다음 주 기록 보기",()=>ChangeRecordWeek(-1));
        newerWeekButton.IsEnabled = recordWeekOffset > 0;
        recordWeekRange = Text($"{SelectedRecordWeek.ToString("yyyy. M. d",CultureInfo.InvariantCulture)} ~ {SelectedRecordWeek.AddDays(7).ToString("yyyy. M. d",CultureInfo.InvariantCulture)}",14,bold:true);
        recordWeekRange.VerticalAlignment = VerticalAlignment.Center; recordWeekRange.TextAlignment = TextAlignment.Center;
        recordWeekRange.Margin = new Thickness(8,0,8,0);
        Grid.SetColumn(recordWeekRange,1); Grid.SetColumn(newerWeekButton,2);
        recordWeekNavigation.Children.Add(olderWeekButton); recordWeekNavigation.Children.Add(recordWeekRange); recordWeekNavigation.Children.Add(newerWeekButton);
        heading.Children.Add(recordWeekNavigation); Page.Children.Add(heading);
        var list = new StackPanel { Spacing = 0 };
        var dated = records.Select(raid => (raid, valid:RecordPresentation.TryDate(raid.Date,out var date),date)).ToList();
        var selected = dated.Where(item => item.valid && RecordPresentation.InWeek(item.date,SelectedRecordWeek)).OrderByDescending(item => item.date).ToList();
        foreach (var day in selected.GroupBy(item => item.date.Date))
        {
            var separator = new Grid { ColumnSpacing = 12, Margin = new Thickness(0,list.Children.Count == 0 ? 0 : 20,0,12) };
            separator.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1,GridUnitType.Star) });
            separator.ColumnDefinitions.Add(new ColumnDefinition { Width = GridLength.Auto });
            separator.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1,GridUnitType.Star) });
            var dateLabel = Text(day.Key.ToString("yyyy년 M월 d일",CultureInfo.InvariantCulture),12,"muted"); dateLabel.TextAlignment = TextAlignment.Center; recordDateLabels.Add(dateLabel); Grid.SetColumn(dateLabel,1); separator.Children.Add(dateLabel);
            foreach (var column in new[]{0,2}) { var line = new Border { Height = 1, Background = Brush("border"), VerticalAlignment = VerticalAlignment.Center }; Grid.SetColumn(line,column); separator.Children.Add(line); }
            list.Children.Add(separator);
            foreach (var item in day) list.Children.Add(RecordLog(item.raid,item.date));
        }
        if (selected.Count == 0) list.Children.Add(new Border { Padding = new Thickness(0,64,0,64), Child = new TextBlock { Text = "이 주에는 클리어 기록이 없습니다.", FontFamily = new FontFamily(font), FontSize = 14, Foreground = Brush("muted"), TextAlignment = TextAlignment.Center, TextWrapping = TextWrapping.Wrap } });
        if (recordWeekOffset == 0 && dated.Any(item => !item.valid))
        {
            list.Children.Add(Text("날짜 확인 불가",12,"muted"));
            foreach (var item in dated.Where(item => !item.valid)) list.Children.Add(RecordLog(item.raid,null));
        }
        Page.Children.Add(list);
        recordWeekAnchor = RecordPresentation.WeekStart(RecordNow);
        if (recordWeekTimer is null)
        {
            recordWeekTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(30) };
            recordWeekTimer.Tick += (_,_) => {
                var anchor = RecordPresentation.WeekStart(RecordNow);
                if (anchor == recordWeekAnchor) return;
                if (recordWeekOffset > 0) recordWeekOffset += (int)((anchor-recordWeekAnchor).TotalDays/7);
                recordWeekAnchor = anchor;
                Changed?.Invoke();
            };
            recordWeekTimer.Start();
        }
    }
    private Border RecordLog(Raid raid,DateTime? date)
    {
        var grid = new Grid { ColumnSpacing = 12, RowSpacing = 4 };
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        grid.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        recordLogRows.Add(grid);
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(42) });
        grid.ColumnDefinitions.Add(new ColumnDefinition { Width = new GridLength(1,GridUnitType.Star) });
        var timestamp = Text(date?.ToString("HH:mm",CultureInfo.InvariantCulture) ?? "—",12,"muted"); timestamp.VerticalAlignment = VerticalAlignment.Center; timestamp.TextLineBounds = TextLineBounds.Tight; grid.Children.Add(timestamp);
        var message = new RichTextBlock { FontFamily = new FontFamily(font), FontSize = 14,
            Foreground = Brush("muted"), TextWrapping = TextWrapping.Wrap, IsTextSelectionEnabled = false,
            TextLineBounds = TextLineBounds.Full, LineHeight = 20, LineStackingStrategy = LineStackingStrategy.BlockLineHeight,
            VerticalAlignment = VerticalAlignment.Center };
        var paragraph = new Paragraph { Margin = new Thickness(0) };
        message.Blocks.Add(paragraph);
        if (!string.IsNullOrWhiteSpace(raid.CharacterEmblem)) {
            var icon = new Image { Width = 18, Height = 18, Stretch = Stretch.Uniform };
            var glyph = Text(raid.Character,14,"characterAccent",true);
            glyph.TextLineBounds = TextLineBounds.Tight;
            glyph.Measure(new Windows.Foundation.Size(double.PositiveInfinity,double.PositiveInfinity));
            var slot = new Canvas { Width = 20, Height = glyph.DesiredSize.Height };
            Canvas.SetTop(icon,glyph.DesiredSize.Height - glyph.BaselineOffset + glyph.DesiredSize.Height/2 - 9);
            slot.Children.Add(icon);
            AutomationProperties.SetName(icon,raid.CharacterClass ?? "직업 문양");
            ToolTipService.SetToolTip(icon,raid.CharacterClass ?? "직업 문양");
            var inline = new InlineUIContainer { Child = slot };
            paragraph.Inlines.Add(inline);
            _ = LoadEmblem(icon,paragraph,inline,raid.CharacterEmblem);
        }
        void Part(string value, bool bold = false, string color = "muted") => paragraph.Inlines.Add(new Run { Text = value, Foreground = Brush(color), FontFamily = new FontFamily(bold ? semiboldFont : font), FontWeight = bold ? Microsoft.UI.Text.FontWeights.SemiBold : Microsoft.UI.Text.FontWeights.Normal });
        Part(raid.Character,true,"characterAccent");
        Part(RecordPresentation.Particle(raid.Character,"이/가") + " "); Part(raid.Dungeon,true,"text");
        if (!string.IsNullOrWhiteSpace(raid.Mode)) Part(" " + raid.Mode,false,"accent");
        var gate = RecordPresentation.Gate(raid.Gate);
        if (gate != "") Part(" " + gate,false,"text");
        Part(RecordPresentation.Particle(gate != "" ? gate : string.IsNullOrWhiteSpace(raid.Mode) ? raid.Dungeon : raid.Mode,"을/를") + " 클리어했습니다.");
        Grid.SetColumn(message,1); grid.Children.Add(message);
        var row = new Border { Child = grid, Padding = new Thickness(4,10,4,10), MinHeight = 44,
            HorizontalAlignment = HorizontalAlignment.Stretch };
        AutomationProperties.SetName(row,RecordPresentation.Sentence(raid.Character,raid.Dungeon,raid.Mode,raid.Gate) + " " + raid.Date);
        return row;
    }
    private async System.Threading.Tasks.Task LoadEmblem(Image image,Paragraph paragraph,InlineUIContainer inline,string path)
    {
        var source = await EmblemImageSource.Load(path,18,Brush("characterAccent").Color);
        if (source is not null) image.Source = source;
        else paragraph.Inlines.Remove(inline);
    }
    private void ChangeRecordWeek(int delta)
    {
        var offset = Math.Max(0,recordWeekOffset + delta);
        if (offset == recordWeekOffset) return;
        recordWeekOffset = offset; Changed?.Invoke(); scrollToTop();
    }
    public void Adapt(double width)
    {
        if (recordWeekNavigation is null || recordWeekRange is null || newerWeekButton is null || olderWeekButton is null) return;
        width = Math.Max(0,width);
        var stacked = width < 300;
        var tiny = width < 112;
        recordWeekNavigation.MaxWidth = width;
        recordWeekNavigation.ColumnDefinitions[0].Width = tiny ? new GridLength(1,GridUnitType.Star) : new GridLength(44);
        recordWeekNavigation.ColumnDefinitions[2].Width = new GridLength(tiny ? 0 : 44);
        recordWeekNavigation.ColumnDefinitions[1].Width = tiny ? new GridLength(0) : stacked ? new GridLength(1,GridUnitType.Star) : GridLength.Auto;
        Grid.SetColumn(recordWeekRange,stacked ? 0 : 1); Grid.SetColumnSpan(recordWeekRange,stacked ? 3 : 1);
        Grid.SetColumn(newerWeekButton,tiny ? 0 : 2);
        Grid.SetRow(olderWeekButton,stacked ? 1 : 0); Grid.SetRow(newerWeekButton,tiny ? 2 : stacked ? 1 : 0);
        if (recordWeekNavigation.RowDefinitions.Count < 3) recordWeekNavigation.RowDefinitions.Add(new RowDefinition { Height = GridLength.Auto });
        olderWeekButton.HorizontalAlignment = newerWeekButton.HorizontalAlignment = HorizontalAlignment.Center;
        recordWeekRange.MaxWidth = Math.Max(0,width - (stacked ? 16 : 128));
        foreach (var dateLabel in recordDateLabels) dateLabel.MaxWidth = Math.Max(0,width-24);
        foreach (var row in recordLogRows)
        {
            var narrow = width < 240;
            row.ColumnDefinitions[0].Width = narrow ? new GridLength(1,GridUnitType.Star) : new GridLength(42);
            row.ColumnDefinitions[1].Width = narrow ? new GridLength(0) : new GridLength(1,GridUnitType.Star);
            foreach (var child in row.Children.OfType<FrameworkElement>().Skip(1)) {
                Grid.SetColumn(child,narrow ? 0 : 1); Grid.SetRow(child,narrow ? 1 : 0);
            }
        }
    }
}
