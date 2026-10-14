using System;
namespace BeatricePC;
public partial class MainWindow
{
    private WeeklySummaryView weeklySummaryView = null!;
    private void ValidateWeeklySummary()
    {
        ShowPage("weekly"); Root.UpdateLayout();
        var title=(Microsoft.UI.Xaml.Controls.TextBlock)((Microsoft.UI.Xaml.Controls.Grid)Page.Children[0]).Children[0];
        if(Math.Abs(title.TransformToVisual(Page).TransformPoint(new Windows.Foundation.Point()).Y)>.5)
            throw new InvalidOperationException("주간 현황 제목의 본문 상단 정렬 실패");
        var receipt=weeklySummaryView.Receipt;
        if(receipt is null || receipt.Characters.Count!=2 || receipt.Money.Gold!=8000 || receipt.Money.BoundGold!=2000 || receipt.Money.Missing!=3)
            throw new InvalidOperationException("주간 현황 합계 또는 미연결 기록 집계 실패");
        if(weeklySummaryView.NewerWeekButton?.IsEnabled!=false)throw new InvalidOperationException("이번 주 다음 버튼 상태 실패");
        weeklySummaryView.ChangeWeek(1);
        if(weeklySummaryView.WeekOffset!=1 || weeklySummaryView.Receipt?.Start!=receipt.Start.AddDays(-7) || weeklySummaryView.NewerWeekButton?.IsEnabled!=true)
            throw new InvalidOperationException("주간 현황 이전 주 전환 실패");
        ShowPage("records");ShowPage("weekly");
        if(weeklySummaryView.WeekOffset!=1)throw new InvalidOperationException("주간 현황 선택 주 유지 실패");
        weeklySummaryView.ChangeWeek(-1);
        if(weeklySummaryView.Receipt?.Money!=receipt.Money || weeklySummaryView.NewerWeekButton?.IsEnabled!=false)
            throw new InvalidOperationException("주간 현황 이번 주 합계 복귀 실패");
        var content=Page.Children[0]; ShowPage("raid-section");
        if(currentPage!="weekly" || !ReferenceEquals(content,Page.Children[0])) throw new InvalidOperationException("주간 현황 분류 선택 유지 실패");
    }
}
