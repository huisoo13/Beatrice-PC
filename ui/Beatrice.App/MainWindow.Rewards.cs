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
    private RewardsView rewardsView = null!;
    private JsonElement rewardData;
    private bool rewardsRequested;
    private DispatcherTimer? rewardCooldownTimer;
    private DateTimeOffset rewardRefreshAvailableAt = DateTimeOffset.MinValue;
    private DateTimeOffset? lastRewardUpdate;

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
        catch (Exception error) { rewardsRequested = false; if (rewardsView.RefreshButton is not null) ToolTipService.SetToolTip(rewardsView.RefreshButton,"데이터 조회 실패: " + error.Message); }
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
    private void UpdateRewardRefresh() => rewardsView.UpdateRefresh(busy, catalogBusy, rewardRefreshAvailableAt, lastRewardUpdate, catalogMessage);
    private void AcceptRewards(JsonElement data)
    {
        rewardsRequested = false;
        var changed = rewardData.ValueKind != JsonValueKind.Array || rewardData.GetRawText() != data.GetRawText();
        rewardData = data.Clone();
        if (currentPage == "rewards" && (changed || rewardsView.Tables.Count == 0))
        { Page.Children.Clear(); ShowRewards(); Adapt(); }
    }
    private void ShowRewards()
    {
        rewardsView.Render(rewardData);
        if (rewardCooldownTimer is null)
        {
            rewardCooldownTimer = new DispatcherTimer { Interval = TimeSpan.FromSeconds(1) };
            rewardCooldownTimer.Tick += (_, _) => { UpdateRewardRefresh(); UpdateSettingsState(); };
            rewardCooldownTimer.Start();
        }
        UpdateRewardRefresh();
    }
    private void AdaptRewardTables() => rewardsView.Adapt(Root.ActualWidth);
}
