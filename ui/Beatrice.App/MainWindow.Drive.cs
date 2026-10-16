using System;
using System.Text.Json;
using System.Threading.Tasks;
using System.Linq;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;

namespace BeatricePC;
public partial class MainWindow
{
    private JsonElement google, drive;
    private GoogleAccountView? googleAccountView;
    private Button? googleLogin, googleLogout;
    private StackPanel? driveBackupSection;
    private Button? driveDownload, driveDelete;
    private TextBlock? driveBackupStatus;
    private string? activePreviewId;
    private bool googleLoginRequested, googleLoginObservedBusy;

    private void AddDriveSettings()
    {
        var section = Section("Google Drive","데이터를 앱 또는 웹과 공유하기 위해 사용됩니다.");
        googleAccountView = new GoogleAccountView(new ViewTheme(font,semiboldFont,Root.Resources,Brush,Text));
        AutomationProperties.SetLiveSetting(googleAccountView.Element,AutomationLiveSetting.Polite);
        section.Children.Add(googleAccountView.Element);
        googleLogin = new Button { MaxWidth=180, Height=44, Padding=new Thickness(0),
            HorizontalAlignment=HorizontalAlignment.Left, HorizontalContentAlignment=HorizontalAlignment.Stretch,
            Template=(ControlTemplate)Root.Resources["BareSettingsButton"],
            Content=new Image { Height=40, Stretch=Stretch.Uniform,
                Source=new BitmapImage(new Uri("ms-appx:///Assets/google-signin-light.png")) } };
        AutomationProperties.SetName(googleLogin,"Google 계정으로 로그인");
        AutomationProperties.SetAccessibilityView((Image)googleLogin.Content,AccessibilityView.Raw);
        googleLogin.Click += async (_, _) => {
            googleLoginRequested=true;googleLoginObservedBusy=false;
            try { await Send(new { type="google_login" }); }
            catch { googleLoginRequested=false;throw; }
        };
        googleLogout = Action("로그아웃",async (_, _) => await ConfirmGoogleLogout());
        googleLogout.MinWidth=80; googleLogout.MinHeight=32; googleLogout.Height=32;
        googleLogout.Padding=new Thickness(12,4,12,4);
        googleLogout.CornerRadius=new CornerRadius(6); googleLogout.BorderThickness=new Thickness(1);
        googleLogout.HorizontalAlignment=HorizontalAlignment.Left;
        googleLogout.Background=Brush("surface"); googleLogout.BorderBrush=Brush("danger"); googleLogout.Foreground=Brush("danger");
        foreach (var state in new[]{"","PointerOver","Pressed","Disabled"}) {
            googleLogout.Resources["ButtonBackground"+state]=Brush(state is "PointerOver" or "Pressed" ? "hover" : "surface");
            googleLogout.Resources["ButtonBorderBrush"+state]=Brush("danger");
            googleLogout.Resources["ButtonForeground"+state]=Brush("danger");
        }
        ToolTipService.SetToolTip(googleLogout,"이 PC의 로그인 정보를 삭제합니다. Google 계정의 앱 권한은 유지됩니다.");
        section.Children.Add(googleLogin); section.Children.Add(googleLogout);
        driveBackupSection = new StackPanel { Spacing=12, Margin=new Thickness(0,24,0,0) };
        driveBackupSection.Children.Add(Text("백업 데이터",14,bold:true));
        var backupButtons = new StackPanel { Orientation=Orientation.Vertical, Spacing=8 };
        backupButtons.SizeChanged+=(_,args)=>backupButtons.Orientation=args.NewSize.Width>=280 ? Orientation.Horizontal : Orientation.Vertical;
        driveDownload = Action("백업 불러오기",async (_,_) => await Send(new { type="drive_download" }));
        driveDelete = Action("백업 데이터 삭제",async (_,_) => await ConfirmDeleteDriveBackup());
        driveDownload.HorizontalAlignment=driveDelete.HorizontalAlignment=HorizontalAlignment.Left;
        driveDelete.Foreground=Brush("danger");
        foreach(var state in new[]{"","PointerOver","Pressed"}) driveDelete.Resources["ButtonForeground"+state]=Brush("danger");
        ToolTipService.SetToolTip(driveDownload,"Drive PC 백업을 확인한 후 이 PC의 기록을 복원합니다.");
        ToolTipService.SetToolTip(driveDelete,"Google Drive의 PC.json 백업만 삭제합니다. 이 PC의 기록은 유지됩니다.");
        backupButtons.Children.Add(driveDownload); backupButtons.Children.Add(driveDelete);
        driveBackupSection.Children.Add(backupButtons);
        driveBackupStatus=Text("",14,"muted");
        AutomationProperties.SetLiveSetting(driveBackupStatus,AutomationLiveSetting.Polite);
        driveBackupSection.Children.Add(driveBackupStatus);section.Children.Add(driveBackupSection);
        UpdateDriveSettings();
    }

    private static bool Flag(JsonElement state, string name) => state.ValueKind == JsonValueKind.Object && state.TryGetProperty(name,out var value) && value.ValueKind == JsonValueKind.True;
    private static string StateText(JsonElement state, string name, string fallback) => state.ValueKind == JsonValueKind.Object && state.TryGetProperty(name,out var value) ? value.GetString() ?? fallback : fallback;

    private void UpdateDriveSettings()
    {
        var signingIn = Flag(google,"busy");
        var signedIn = Flag(google,"signedIn");
        var available = !demo && !busy && !signingIn;
        if (googleAccountView is not null) {
            googleAccountView.Update(StateText(google,"name",""),StateText(google,"email",""),signedIn ? StateText(google,"picture","") : "");
            googleAccountView.Element.Visibility = signedIn ? Visibility.Visible : Visibility.Collapsed;
        }
        if (googleLogin is not null)
        {
            googleLogin.Visibility = signedIn ? Visibility.Collapsed : Visibility.Visible;
            googleLogin.IsEnabled = available;
            var message=StateText(google,"message","Google 계정으로 로그인");
            ToolTipService.SetToolTip(googleLogin,message);
            AutomationProperties.SetHelpText(googleLogin,message);
            AutomationProperties.SetItemStatus(googleLogin,signingIn ? "로그인 진행 중" : "");
        }
        if (googleLogout is not null)
        {
            googleLogout.Visibility = signedIn ? Visibility.Visible : Visibility.Collapsed;
            googleLogout.IsEnabled = available;
        }
        if(driveBackupSection is not null) driveBackupSection.Visibility=signedIn ? Visibility.Visible : Visibility.Collapsed;
        foreach(var button in new[]{driveDownload,driveDelete}) if(button is not null) {
            button.Visibility=signedIn ? Visibility.Visible : Visibility.Collapsed;
            button.IsEnabled=available && signedIn && Flag(drive,"available");
        }
        if(driveBackupStatus is not null) {
            var message=StateText(drive,"message","");
            if(message=="Drive · 로그인 후 사용할 수 있습니다.")message="";
            driveBackupStatus.Text=message;
            driveBackupStatus.Visibility=signedIn && !string.IsNullOrWhiteSpace(message) ? Visibility.Visible : Visibility.Collapsed;
        }
    }

    private void ReceiveGoogleState(JsonElement state)
    {
        google=state;
        if(!googleLoginRequested || demo || closing)return;
        if(Flag(state,"busy")) { googleLoginObservedBusy=true;return; }
        if(!googleLoginObservedBusy)return;
        googleLoginRequested=false;googleLoginObservedBusy=false;
        if(AppWindow.Presenter is Microsoft.UI.Windowing.OverlappedPresenter presenter &&
            presenter.State==Microsoft.UI.Windowing.OverlappedPresenterState.Minimized)presenter.Restore();
        AppWindow.Show();Activate();
    }

    private Task ConfirmGoogleLogout() => ConfirmGoogleAction(false,googleLogout);
    private Task ConfirmDeleteDriveBackup() => ConfirmGoogleAction(true,driveDelete);

    private async Task ConfirmGoogleAction(bool needsDrive,Button? source)
    {
        if(dialogOpen || closing || (!demo && (busy || Flag(google,"busy") || !Flag(google,"signedIn") || (needsDrive && !Flag(drive,"available")))))return;
        var account=StateText(google,"email","");
        dialogOpen=true;
        try {
            activeDialog=GoogleWarningDialog.Create(Root.XamlRoot,new ViewTheme(font,semiboldFont,Root.Resources,Brush,Text),needsDrive);
            var result=await activeDialog.ShowAsync();
            if(result==ContentDialogResult.Primary && !demo && !closing && !busy && !Flag(google,"busy") &&
                account==StateText(google,"email","") && Flag(google,"signedIn") && (!needsDrive || Flag(drive,"available")))
                await Send(new { type=needsDrive ? "drive_delete" : "google_logout" });
        }
        finally {
            activeDialog=null;dialogOpen=false;
            if(!closing && source is { Visibility:Visibility.Visible,IsEnabled:true })source.Focus(FocusState.Programmatic);
        }
    }

    private void ValidateDriveAccountUI()
    {
        var saved=google;var savedDrive=drive;
        try {
            ShowSettingsSection("Google Drive");
            drive=JsonSerializer.SerializeToElement(new { message="Drive · 로그인 후 사용할 수 있습니다.",available=true });
            google=JsonSerializer.SerializeToElement(new { signedIn=false, busy=false }); UpdateDriveSettings();
            var originalContent=googleLogin!.Content;
            if (googleLogin.Visibility != Visibility.Visible || googleAccountView!.Element.Visibility != Visibility.Collapsed || googleLogout!.Visibility != Visibility.Collapsed || driveBackupSection!.Visibility != Visibility.Collapsed || driveDownload!.IsEnabled || driveDelete!.IsEnabled)
                throw new InvalidOperationException("로그인 전 Google 버튼 표시 실패");
            google=JsonSerializer.SerializeToElement(new { signedIn=false, busy=true }); UpdateDriveSettings();
            if (googleLogin.IsEnabled || !ReferenceEquals(originalContent,googleLogin.Content)) throw new InvalidOperationException("Google 로그인 중 중복 실행 방지 실패");
            google=JsonSerializer.SerializeToElement(new { signedIn=true, name="샘플 사용자", email="preview@example.com", busy=false }); UpdateDriveSettings();
            if (googleLogin.Visibility != Visibility.Collapsed || googleAccountView.Element.Visibility != Visibility.Visible || !AutomationProperties.GetName(googleAccountView.Element).Contains("샘플 사용자, preview@example.com") || googleLogout.Visibility != Visibility.Visible ||
                driveBackupSection!.Visibility != Visibility.Visible || driveDownload!.Visibility!=Visibility.Visible || driveDelete!.Visibility!=Visibility.Visible || driveBackupStatus!.Visibility!=Visibility.Collapsed)
                throw new InvalidOperationException("로그인 후 계정·백업 관리 화면 실패");
        }
        finally { google=saved;drive=savedDrive; UpdateDriveSettings(); }
    }

    private async Task ShowDrivePreview(JsonElement preview)
    {
        var previewId = preview.GetProperty("previewId").GetString()!;
        if (activePreviewId is not null) return;
        activePreviewId = previewId;
        var apply = false;
        try
        {
            // Keep the worker paused until an existing confirmation closes and this preview is answered.
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
            SetFailure("복원 확인 창을 열지 못했습니다: " + error.Message);
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
