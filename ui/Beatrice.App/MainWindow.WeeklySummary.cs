using System;
namespace BeatricePC;
public partial class MainWindow
{
    private WeeklySummaryView weeklySummaryView = null!;
    private void ValidateWeeklySummary()
    {
        ShowPage("weekly"); Root.UpdateLayout();
        var receipt=weeklySummaryView.Receipt;
        if(receipt is null || receipt.Characters.Count!=2 || receipt.Money.Gold!=8000 || receipt.Money.BoundGold!=2000 || receipt.Money.Missing!=3)
            throw new InvalidOperationException("주간 현황 합계 또는 미연결 기록 집계 실패");
        var content=Page.Children[0]; ShowPage("raid-section");
        if(currentPage!="weekly" || !ReferenceEquals(content,Page.Children[0])) throw new InvalidOperationException("주간 현황 분류 선택 유지 실패");
    }
}
