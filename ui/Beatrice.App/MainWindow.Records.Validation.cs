using System;
using System.Linq;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Automation.Provider;
using Microsoft.UI.Xaml.Controls;

namespace BeatricePC;
public partial class MainWindow
{
    private async Task ValidateWeeklyRecordInteractions()
    {
        ShowPage("records"); recordWeekOffset = 0; RebuildRecords(); Root.UpdateLayout();
        await Task.Delay(50); Root.UpdateLayout();
        foreach (var row in recordLogRows)
        {
            var time = (TextBlock)row.Children[0]; var message = (TextBlock)row.Children[1];
            var timeCenter = time.TransformToVisual(row).TransformPoint(new Windows.Foundation.Point()).Y + time.ActualHeight/2;
            var messageCenter = message.TransformToVisual(row).TransformPoint(new Windows.Foundation.Point()).Y + message.ActualHeight/2;
            if (Math.Abs(timeCenter-messageCenter) > .5) throw new InvalidOperationException("시간과 로그 문장의 수직 중앙 정렬 불일치");
        }
        int LogCount() => ((StackPanel)Page.Children[1]).Children.OfType<Button>().Count();
        if (LogCount() != 4 || newerWeekButton?.IsEnabled != false || recordWeekRange?.FontSize != 14)
            throw new InvalidOperationException("이번 주 기록 및 날짜 영역 검증 실패");
        if (((StackPanel)Page.Children[0]).Children[0] is not TextBlock title || title.FontSize != 20 || !title.FontFamily.Source.Contains("Pretendard"))
            throw new InvalidOperationException("본문 제목 크기 또는 Pretendard 적용 실패");
        void Invoke(Button button) => ((IInvokeProvider)new ButtonAutomationPeer(button).GetPattern(PatternInterface.Invoke)).Invoke();
        Invoke(olderWeekButton!); await Task.Delay(50);
        if (recordWeekOffset != 1 || LogCount() != 1 || newerWeekButton?.IsEnabled != true)
            throw new InvalidOperationException("수요일 05:59의 이전 주 분류 또는 이전 주 버튼 실패");
        ShowPage("rewards"); ShowPage("records");
        if (recordWeekOffset != 1 || LogCount() != 1) throw new InvalidOperationException("선택 주간 유지 실패");
        Invoke(olderWeekButton!); await Task.Delay(50);
        if (recordWeekOffset != 2 || LogCount() != 1) throw new InvalidOperationException("2주 전 기록 실패");
        Invoke(olderWeekButton!); await Task.Delay(50);
        if (recordWeekOffset != 3 || LogCount() != 0) throw new InvalidOperationException("기록 없는 주간 실패");
        for (var i=0;i<3;i++) { Invoke(newerWeekButton!); await Task.Delay(50); }
        if (recordWeekOffset != 0 || LogCount() != 4 || newerWeekButton?.IsEnabled != false) throw new InvalidOperationException("이번 주 복귀 실패");
    }
}
