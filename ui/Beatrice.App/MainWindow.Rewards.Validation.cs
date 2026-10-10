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
            if (deadline != rewardRefreshAvailableAt || rewardsView.RefreshButton?.IsEnabled != false || lastRewardUpdate is null) throw new InvalidOperationException("새로고침 쿨타임/갱신 시간 검증 실패");
            rewardRefreshAvailableAt = DateTimeOffset.UtcNow.AddSeconds(-1); UpdateRewardRefresh();
            if (rewardsView.RefreshButton?.IsEnabled != true) throw new InvalidOperationException("쿨타임 종료 활성화 실패");
        }
        Root.UpdateLayout();
        if (Page.Children.Count != 2 || rewardsView.RefreshButton?.Content is not Image) throw new InvalidOperationException("보상표 안내 제거/새로고침 버튼 검증 실패");
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
}
