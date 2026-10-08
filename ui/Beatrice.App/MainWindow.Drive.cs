using System;
using System.Text.Json;
using System.Threading.Tasks;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Controls;

namespace BeatricePC;
public partial class MainWindow
{
    private JsonElement google, drive;
    private TextBlock? googleStatus, driveStatus;
    private Button? googleLogin, googleLogout, driveConnect, driveUpload, driveDownload;
    private string? activePreviewId;

    private void AddDriveSettings()
    {
        var section = Section("Google Drive");
        section.Children.Add(Text("로그인과 권한 연결 후 새 완료 기록이 자동 저장됩니다.",14,"muted"));
        if (demo) section.Children.Add(Text("화면 미리보기에서는 Google 계정을 연결하지 않습니다.",12,"muted"));
        googleStatus = Text("Google · 로그인하지 않음",14,"muted");
        AutomationProperties.SetLiveSetting(googleStatus,AutomationLiveSetting.Polite);
        section.Children.Add(googleStatus);
        googleLogin = Action("Google 로그인",async (_, _) => await Send(new { type = Flag(google,"busy") ? "google_cancel" : "google_login" }));
        googleLogout = Action("로그아웃",async (_, _) => await Send(new { type = "google_logout" }));
        ToolTipService.SetToolTip(googleLogout,"이 PC의 로그인 정보를 삭제합니다. Google 계정의 앱 권한은 유지됩니다.");
        driveConnect = Action("Drive 권한 연결",async (_, _) => await Send(new { type = "google_connect" }));
        driveUpload = Action("Drive에 저장",async (_, _) => await Send(new { type = "drive_upload" }));
        driveDownload = Action("Drive에서 불러오기",async (_, _) => await Send(new { type = "drive_download" }));
        ToolTipService.SetToolTip(driveDownload,"분석을 보류하고, 확인 후 PC 기록을 Drive 기록으로 교체합니다.");
        foreach (var button in new[]{googleLogin,googleLogout,driveConnect,driveUpload,driveDownload}) section.Children.Add(button);
        driveStatus = Text("Drive · 로그인 후 사용할 수 있습니다.",14,"muted");
        AutomationProperties.SetLiveSetting(driveStatus,AutomationLiveSetting.Polite);
        section.Children.Add(driveStatus);
    }

    private static bool Flag(JsonElement state, string name) => state.ValueKind == JsonValueKind.Object && state.TryGetProperty(name,out var value) && value.ValueKind == JsonValueKind.True;
    private static string StateText(JsonElement state, string name, string fallback) => state.ValueKind == JsonValueKind.Object && state.TryGetProperty(name,out var value) ? value.GetString() ?? fallback : fallback;

    private void UpdateDriveSettings()
    {
        var signingIn = Flag(google,"busy");
        var signedIn = Flag(google,"signedIn");
        var authorized = Flag(google,"authorized");
        var available = !demo && !busy && !signingIn;
        if (googleStatus is not null) googleStatus.Text = StateText(google,"message","Google · 로그인하지 않음");
        if (driveStatus is not null) driveStatus.Text = StateText(drive,"message","Drive · 로그인 후 사용할 수 있습니다.");
        if (googleLogin is not null)
        {
            googleLogin.Content = signingIn ? "로그인 취소" : "Google 로그인";
            googleLogin.Visibility = signingIn || !signedIn ? Visibility.Visible : Visibility.Collapsed;
            googleLogin.IsEnabled = !demo && (signingIn || available);
        }
        if (googleLogout is not null)
        {
            googleLogout.Visibility = Flag(google,"canLogout") ? Visibility.Visible : Visibility.Collapsed;
            googleLogout.IsEnabled = available;
        }
        if (driveConnect is not null)
        {
            driveConnect.Visibility = signedIn && !authorized ? Visibility.Visible : Visibility.Collapsed;
            driveConnect.IsEnabled = available && signedIn;
        }
        if (driveUpload is not null) driveUpload.IsEnabled = available && authorized && Flag(drive,"available");
        if (driveDownload is not null) driveDownload.IsEnabled = available && authorized && Flag(drive,"available");
    }

    private async Task ShowDrivePreview(JsonElement preview)
    {
        var previewId = preview.GetProperty("previewId").GetString()!;
        if (activePreviewId is not null) return;
        activePreviewId = previewId;
        var apply = false;
        try
        {
            // A record-detail dialog may already be open; keep the worker paused until this preview is answered.
            while (dialogOpen && !closing) await Task.Delay(100);
            if (closing) return;
            dialogOpen = true;
            var created = DateTimeOffset.TryParse(preview.GetProperty("createdTime").GetString(),out var at)
                ? at.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss") : "시각 확인 불가";
            var content = Text($"계정: {preview.GetProperty("email").GetString()}\n저장 시각: {created}\nDrive 완료 기록: {preview.GetProperty("completedCount").GetInt32()}건 / 현재 PC 기록: {preview.GetProperty("localCount").GetInt32()}건\n진행 전·진행 중 기록 {preview.GetProperty("omittedCount").GetInt32()}건은 불러오지 않습니다.\n\n현재 PC 기록을 로컬 백업한 후 Drive 기록으로 교체합니다. 계속할까요?",14);
            activeDialog = CreateDialog("Drive 기록 불러오기",content);
            activeDialog.PrimaryButtonText = "복원";
            activeDialog.CloseButtonText = "취소";
            activeDialog.DefaultButton = ContentDialogButton.Close;
            apply = await activeDialog.ShowAsync() == ContentDialogResult.Primary;
        }
        catch (Exception error)
        {
            if (driveStatus is not null) driveStatus.Text = "복원 확인 창을 열지 못했습니다: " + error.Message;
        }
        finally
        {
            if (!closing)
            {
                activeDialog = null;
                dialogOpen = false;
                await Send(new { type = "drive_restore", previewId, apply });
            }
            activePreviewId = null;
        }
    }
}
