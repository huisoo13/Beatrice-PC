using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Text.Json;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace BeatricePC;
internal sealed class WeeklySummaryView : IDisposable
{
    private readonly StackPanel page;
    private readonly ViewTheme theme;
    private readonly Func<DateTime> clock;
    private readonly DispatcherTimer timer;
    private DateTime anchor;
    private string? goldImage, boundGoldImage;
    private readonly Dictionary<string, BitmapImage> imageSources = new();
    internal void UpdateCurrencyImages(JsonElement? images)
    {
        string? PathFor(string key) => images is JsonElement data && data.ValueKind==JsonValueKind.Object &&
            data.TryGetProperty(key,out var path) && path.ValueKind==JsonValueKind.String ? path.GetString() : null;
        var gold=PathFor("gold"); var bound=PathFor("boundGold");
        if(gold==goldImage && bound==boundGoldImage) return;
        goldImage=gold; boundGoldImage=bound; imageSources.Clear(); Changed?.Invoke();
    }
    private Grid? headingGrid, weekNavigation;
    private TextBlock? weekRange;
    private Button? olderWeekButton, newerWeekButton;
    internal int WeekOffset { get; private set; }
    internal Button? OlderWeekButton => olderWeekButton;
    internal Button? NewerWeekButton => newerWeekButton;
    internal void ChangeWeek(int delta)
    {
        var next=Math.Max(0,WeekOffset+delta);
        if(next==WeekOffset)return;
        WeekOffset=next; Changed?.Invoke();
    }
    private readonly List<Grid> rows=new();
    internal event Action? Changed;
    internal WeeklyReceipt? Receipt { get; private set; }
    internal int RowCount => rows.Count;
    internal WeeklySummaryView(StackPanel page, ViewTheme theme, Func<DateTime> clock)
    {
        this.page=page; this.theme=theme; this.clock=clock; anchor=RecordPresentation.WeekStart(clock());
        timer=new DispatcherTimer { Interval=TimeSpan.FromSeconds(30) };
        timer.Tick+=(_,_) => { var next=RecordPresentation.WeekStart(clock()); if(next==anchor)return; if(WeekOffset>0)WeekOffset+=(int)((next-anchor).TotalDays/7); anchor=next; Changed?.Invoke(); };
        timer.Start();
    }
    public void Dispose() => timer.Stop();
    private TextBlock Text(string value,int size=14,string color="text",bool bold=false) => theme.Text(value,size,color,bold);
    private Grid Row(FrameworkElement left,FrameworkElement gold,FrameworkElement bound,double minHeight=32)
    {
        var grid=new Grid { MinHeight=minHeight,RowSpacing=4 };
        foreach(var weight in new[]{62,19,19}) grid.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(weight,GridUnitType.Star) });
        for(int i=0;i<3;i++) grid.RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
        int col=0;
        foreach(var child in new[]{left,gold,bound}) { Grid.SetColumn(child,col++); if(child is FrameworkElement element) element.VerticalAlignment=VerticalAlignment.Center; grid.Children.Add(child); }
        rows.Add(grid); return grid;
    }
    private StackPanel Number(decimal value,string name,bool unknown=false,bool bold=false,string color="text",int size=14,bool bound=false,bool total=false)
    {
        var empty=unknown || value==0;
        var text=Text(empty ? "—" : WeeklySummary.Amount(value),size,empty ? "muted" : color,bold);
        if(empty) { text.FontFamily=new FontFamily(theme.Font); text.FontWeight=Microsoft.UI.Text.FontWeights.Normal; }
        text.HorizontalAlignment=HorizontalAlignment.Right; text.TextAlignment=TextAlignment.Right;
        text.TextWrapping=TextWrapping.NoWrap;
        AutomationProperties.SetName(text,name+" "+(unknown ? "골드 보상 금액 미연결" : WeeklySummary.Amount(value)+" 골드"));
        var amount=new StackPanel { Orientation=Orientation.Horizontal,Spacing=total ? 4 : 2,HorizontalAlignment=HorizontalAlignment.Right,VerticalAlignment=VerticalAlignment.Center };
        var path=bound ? boundGoldImage : goldImage;
        if(!unknown && value!=0 && !string.IsNullOrEmpty(path) && Path.IsPathRooted(path) && File.Exists(path)) {
            try {
                if(!imageSources.TryGetValue(path,out var source)) { source=new BitmapImage(new Uri(path)); imageSources[path]=source; }
                var icon=new Image { Width=total ? 16 : 14,Height=total ? 16 : 14,Stretch=Stretch.Uniform,Source=source,VerticalAlignment=VerticalAlignment.Center };
                AutomationProperties.SetAccessibilityView(icon,Microsoft.UI.Xaml.Automation.Peers.AccessibilityView.Raw);
                icon.ImageFailed+=(_,_) => { icon.Visibility=Visibility.Collapsed; amount.Spacing=0; };
                amount.Children.Add(icon);
            } catch { /* Preserve readable amounts if an optional local asset cannot load. */ }
        }
        text.VerticalAlignment=VerticalAlignment.Center; amount.Children.Add(text);
        return amount;
    }
    internal void Render(IReadOnlyList<Raid> records)
    {
        rows.Clear(); page.Spacing=0;
        anchor=RecordPresentation.WeekStart(clock());
        Receipt=WeeklySummary.Build(records,anchor.AddDays(-7L*WeekOffset));
        var heading=new Grid { ColumnSpacing=12,Margin=new Thickness(0,0,0,24) };
        headingGrid=heading;
        heading.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(1,GridUnitType.Star) });
        heading.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(1,GridUnitType.Star) });
        heading.RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
        heading.RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
        var title=Text("주간 현황",20,bold:true);title.VerticalAlignment=VerticalAlignment.Top;heading.Children.Add(title);
        weekNavigation=new Grid { ColumnSpacing=12,RowSpacing=8,HorizontalAlignment=HorizontalAlignment.Right };
        foreach(var width in new[]{new GridLength(44),GridLength.Auto,new GridLength(44)})
            weekNavigation.ColumnDefinitions.Add(new ColumnDefinition { Width=width });
        for(var i=0;i<3;i++)weekNavigation.RowDefinitions.Add(new RowDefinition { Height=GridLength.Auto });
        olderWeekButton=WeekNavigationButton.Create(theme,true,"이전 주 현황 보기",()=>ChangeWeek(1));
        newerWeekButton=WeekNavigationButton.Create(theme,false,"다음 주 현황 보기",()=>ChangeWeek(-1));
        newerWeekButton.IsEnabled=WeekOffset>0;
        weekRange=Text($"{Receipt.Start.ToString("yyyy. M. d",CultureInfo.InvariantCulture)} ~ {Receipt.Start.AddDays(7).ToString("yyyy. M. d",CultureInfo.InvariantCulture)}",14,"muted");
        weekRange.VerticalAlignment=VerticalAlignment.Center;weekRange.TextAlignment=TextAlignment.Center;weekRange.Margin=new Thickness(8,0,8,0);
        Grid.SetColumn(weekRange,1);Grid.SetColumn(newerWeekButton,2);
        weekNavigation.Children.Add(olderWeekButton);weekNavigation.Children.Add(weekRange);weekNavigation.Children.Add(newerWeekButton);
        Grid.SetColumn(weekNavigation,1);heading.Children.Add(weekNavigation);page.Children.Add(heading);
        var goldLabel=Text("골드",12,"muted"); goldLabel.HorizontalAlignment=HorizontalAlignment.Right;
        var boundLabel=Text("귀속 골드",12,"muted"); boundLabel.HorizontalAlignment=HorizontalAlignment.Right;
        var labels=Row(Text(""),goldLabel,boundLabel,0); labels.Margin=new Thickness(0,0,0,8); page.Children.Add(labels);
        var total=Row(Text("총합",14,bold:true),Number(Receipt.Money.Gold,"총 일반 골드",bold:true,color:"warning",size:20,total:true),Number(Receipt.Money.BoundGold,"총 귀속 골드",bold:true,size:20,bound:true,total:true));
        page.Children.Add(new Border { Child=total,BorderThickness=new Thickness(0,1,0,1),BorderBrush=theme.Brush("border"),Padding=new Thickness(0,16,0,16),Margin=new Thickness(0,0,0,16) });
        if(Receipt.Characters.Count==0) {
            var empty=Text("이 주에는 클리어 기록이 없습니다.",14,"muted"); empty.Margin=new Thickness(0,48,0,48); empty.TextAlignment=TextAlignment.Center; page.Children.Add(empty); return;
        }
        foreach(var character in Receipt.Characters) {
            var section=new StackPanel { Spacing=0 };
            var identity=new RichTextBlock { FontFamily=new FontFamily(theme.Font),FontSize=14,Foreground=theme.Brush("text"),TextWrapping=TextWrapping.Wrap,IsTextSelectionEnabled=false,Margin=new Thickness(0,0,12,0) };
            var identityParagraph=new Microsoft.UI.Xaml.Documents.Paragraph { Margin=new Thickness(0) }; identity.Blocks.Add(identityParagraph);
            void IdentityPart(string value,int size,string color,bool bold=false) => identityParagraph.Inlines.Add(new Microsoft.UI.Xaml.Documents.Run { Text=value,FontSize=size,Foreground=theme.Brush(color),FontFamily=new FontFamily(bold ? theme.SemiboldFont : theme.Font) });
            IdentityPart((character.Job ?? "—")+"  ",12,"muted");
            IdentityPart(character.Name,14,"characterAccent",true);
            if(character.Level!="") IdentityPart("  "+character.Level,12,"muted");
            var header=Row(identity,Number(character.Money.Gold,character.Name+" 일반 골드 합",bold:true,color:"warning"),Number(character.Money.BoundGold,character.Name+" 귀속 골드 합",bold:true,bound:true));
            header.Margin=new Thickness(0,0,0,8); section.Children.Add(header);
            foreach(var dungeon in character.Dungeons) {
                var description=new RichTextBlock { FontFamily=new FontFamily(theme.Font),FontSize=14,Foreground=theme.Brush("text"),TextWrapping=TextWrapping.Wrap,IsTextSelectionEnabled=false,Margin=new Thickness(0,0,16,0) };
                var paragraph=new Microsoft.UI.Xaml.Documents.Paragraph { Margin=new Thickness(0) }; description.Blocks.Add(paragraph);
                void Part(string value,string color) => paragraph.Inlines.Add(new Microsoft.UI.Xaml.Documents.Run { Text=value,Foreground=theme.Brush(color) });
                Part(dungeon.Name,"text"); if(!string.IsNullOrWhiteSpace(dungeon.Mode))Part("  "+dungeon.Mode,"accent"); if(dungeon.Gates!="")Part("  "+dungeon.Gates,"muted");
                section.Children.Add(Row(description,Number(dungeon.Money.Gold,dungeon.Name+" 일반 골드",dungeon.Money.Missing>0),Number(dungeon.Money.BoundGold,dungeon.Name+" 귀속 골드",dungeon.Money.Missing>0,bound:true)));
            }
            page.Children.Add(new Border { Child=section,BorderBrush=theme.Brush("border"),BorderThickness=new Thickness(0,0,0,character==Receipt.Characters[^1] ? 0 : 1),Padding=new Thickness(0,0,0,16),Margin=new Thickness(0,0,0,16) });
        }
    }
    internal void Adapt(double width)
    {
        if(weekNavigation is not null && weekRange is not null && olderWeekButton is not null && newerWeekButton is not null) {
            width=Math.Max(0,width);
            var headingStacked=width<440;
            if(headingGrid is not null) {
                headingGrid.ColumnDefinitions[1].Width=headingStacked ? new GridLength(0) : new GridLength(1,GridUnitType.Star);
                Grid.SetRow(weekNavigation,headingStacked ? 1 : 0);Grid.SetColumn(weekNavigation,headingStacked ? 0 : 1);
                weekNavigation.HorizontalAlignment=headingStacked ? HorizontalAlignment.Left : HorizontalAlignment.Right;
            }
            var available=headingStacked ? width : Math.Max(0,(width-12)/2);
            var stacked=available<300;var tiny=available<112;
            weekNavigation.MaxWidth=available;
            weekNavigation.ColumnDefinitions[0].Width=tiny ? new GridLength(1,GridUnitType.Star) : new GridLength(44);
            weekNavigation.ColumnDefinitions[2].Width=new GridLength(tiny ? 0 : 44);
            weekNavigation.ColumnDefinitions[1].Width=tiny ? new GridLength(0) : stacked ? new GridLength(1,GridUnitType.Star) : GridLength.Auto;
            Grid.SetColumn(weekRange,stacked ? 0 : 1);Grid.SetColumnSpan(weekRange,stacked ? 3 : 1);
            Grid.SetColumn(newerWeekButton,tiny ? 0 : 2);
            Grid.SetRow(olderWeekButton,stacked ? 1 : 0);Grid.SetRow(newerWeekButton,tiny ? 2 : stacked ? 1 : 0);
            olderWeekButton.HorizontalAlignment=newerWeekButton.HorizontalAlignment=HorizontalAlignment.Center;
            weekRange.MaxWidth=Math.Max(0,available-(stacked ? 16 : 128));
        }
        foreach(var grid in rows) {
            grid.Width=Math.Max(0,width);
            var narrow=width<240;
            grid.ColumnSpacing=narrow ? 0 : 12;
            for(int i=0;i<3;i++) {
                grid.ColumnDefinitions[i].MinWidth=(!narrow && i>0) ? 80 : 0;
                if(i>0 && grid.Children[i] is StackPanel amount && amount.Children[^1] is TextBlock number && grid.Children[0] is TextBlock label && label.Text=="총합") number.FontSize=width<440 ? 14 : 20;
                var moneyWidth=Math.Max(80,(width-24)*0.19);
                grid.ColumnDefinitions[i].Width=narrow ? (i==0 ? new GridLength(1,GridUnitType.Star) : new GridLength(0)) : new GridLength(i==0 ? Math.Max(0,width-24-moneyWidth*2) : moneyWidth);
                Grid.SetColumn((FrameworkElement)grid.Children[i],narrow ? 0 : i); Grid.SetRow((FrameworkElement)grid.Children[i],narrow ? i : 0);
            }
        }
    }
}
