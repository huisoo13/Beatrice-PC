using System;
using System.Text.Json;
using System.Threading.Tasks;
using System.Linq;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace BeatricePC;
public partial class MainWindow
{
    private JsonElement lostArkApi;
    private PasswordBox? lostArkApiInput;
    private TextBlock? lostArkApiStatus;
    private StackPanel? lostArkApiEntry, lostArkApiRegistered, lostArkApiGuide;
    private bool lostArkApiSaving, lostArkApiFeedback, lostArkApiEditing;
    private Button? lostArkApiVerify, lostArkApiChange;

    private void AddLostArkApiSettings()
    {
        var section=Section("로스트아크 API","캐릭터 정보 호출을 위한 API 키를 관리합니다.");
        lostArkApiEntry=new StackPanel { Spacing=12 }; section.Children.Add(lostArkApiEntry);
        lostArkApiInput=new PasswordBox {
            PlaceholderText="API 키 입력", PasswordRevealMode=PasswordRevealMode.Hidden,
            MaxLength=16384, MinHeight=44, Height=44, Padding=new Thickness(12,0,12,0),
            VerticalContentAlignment=VerticalAlignment.Center, HorizontalAlignment=HorizontalAlignment.Stretch,
            FontFamily=new FontFamily(font), FontSize=14, Background=Brush("surface"),
            Foreground=Brush("text"), BorderBrush=Brush("border")
        };
        foreach(var state in new[]{"","PointerOver","Focused","Disabled"}) {
            lostArkApiInput.Resources["TextControlBackground"+state]=Brush(state=="PointerOver" ? "hover" : "surface");
            lostArkApiInput.Resources["TextControlForeground"+state]=Brush("text");
            lostArkApiInput.Resources["TextControlBorderBrush"+state]=Brush(state=="Focused" ? "accent" : "border");
            lostArkApiInput.Resources["TextControlPlaceholderForeground"+state]=Brush("muted");
        }
        lostArkApiInput.Loaded+=(_,_)=>CenterLostArkApiInput(lostArkApiInput);
        AutomationProperties.SetName(lostArkApiInput,"로스트아크 API 키");
        lostArkApiInput.PasswordChanged+=(_,_)=> { lostArkApiFeedback=false; UpdateLostArkApiSettings(); };
        lostArkApiInput.KeyDown+=async (_,args)=> {
            if(args.Key!=Windows.System.VirtualKey.Enter) return;
            args.Handled=true; await VerifyLostArkApiKey();
        };
        lostArkApiEntry.Children.Add(lostArkApiInput);
        lostArkApiVerify=Action("검증",async (_,_)=>await VerifyLostArkApiKey());
        lostArkApiVerify.HorizontalAlignment=HorizontalAlignment.Left;
        lostArkApiEntry.Children.Add(lostArkApiVerify);
        lostArkApiStatus=Text("",14,"muted");
        AutomationProperties.SetLiveSetting(lostArkApiStatus,AutomationLiveSetting.Polite);
        lostArkApiEntry.Children.Add(lostArkApiStatus);
        lostArkApiGuide=new StackPanel { Spacing=12 };
        lostArkApiGuide.Children.Add(Text("API 키 발급 방법",14,bold:true));
        lostArkApiGuide.Children.Add(Text("1. 로스트아크 개발자 사이트에서 STOVE 계정으로 로그인합니다.\n2. MY CLIENTS에서 CREATE A NEW CLIENT를 선택합니다.\n3. 클라이언트 정보를 입력하고 약관에 동의해 생성합니다.\n4. 발급된 API KEY를 복사해 위 입력창에 붙여넣고 검증을 누릅니다.",14,"muted"));
        var portal=new HyperlinkButton { Content="로스트아크 개발자 사이트 열기", NavigateUri=new Uri("https://developer-lostark.game.onstove.com/getting-started"),
            FontFamily=new FontFamily(font), FontSize=14, Foreground=Brush("accent"), Padding=new Thickness(0), HorizontalAlignment=HorizontalAlignment.Left };
        lostArkApiGuide.Children.Add(portal); section.Children.Add(lostArkApiGuide);
        lostArkApiRegistered=new StackPanel { Spacing=12 };
        lostArkApiRegistered.Children.Add(Text("API키가 정상적으로 등록되었습니다.",14,"success"));
        lostArkApiChange=Action("변경",(_,_)=> {
            lostArkApiEditing=true; lostArkApiFeedback=false; UpdateLostArkApiSettings();
            lostArkApiInput.Focus(FocusState.Programmatic);
        });
        lostArkApiChange.HorizontalAlignment=HorizontalAlignment.Left;
        lostArkApiRegistered.Children.Add(lostArkApiChange); section.Children.Add(lostArkApiRegistered);
        UpdateLostArkApiSettings();
    }
    private static void CenterLostArkApiInput(DependencyObject parent)
    {
        for(var i=0;i<VisualTreeHelper.GetChildrenCount(parent);i++) {
            var child=VisualTreeHelper.GetChild(parent,i);
            if(child is FrameworkElement element && (element.Name=="ContentElement" || element.Name=="PlaceholderTextContentPresenter"))
                element.VerticalAlignment=VerticalAlignment.Center;
            CenterLostArkApiInput(child);
        }
    }
    private async Task VerifyLostArkApiKey()
    {
        if(demo || lostArkApiSaving || Flag(lostArkApi,"busy") || lostArkApiInput is null || string.IsNullOrWhiteSpace(lostArkApiInput.Password)) return;
        lostArkApiSaving=lostArkApiFeedback=true; UpdateLostArkApiSettings();
        try { await engine.SendAsync(new { type="lostark_api_verify", key=lostArkApiInput.Password }); }
        catch(Exception) {
            lostArkApiSaving=false;
            lostArkApi=JsonSerializer.SerializeToElement(new { configured=Flag(lostArkApi,"configured"), message="검증 요청을 보내지 못했습니다. 다시 시도해주세요." });
            UpdateLostArkApiSettings();
        }
    }
    private void ReceiveLostArkApiResult(JsonElement value)
    {
        lostArkApi=value.Clone(); lostArkApiSaving=false;
        if(Flag(value,"success")) {
            lostArkApiEditing=false;
            if(lostArkApiInput is not null) lostArkApiInput.Password="";
        }
        lostArkApiFeedback=true;
        UpdateLostArkApiSettings(); RebuildRecords();
    }
    private void UpdateLostArkApiSettings()
    {
        var working=lostArkApiSaving || Flag(lostArkApi,"busy");
        var editing=!Flag(lostArkApi,"configured") || lostArkApiEditing;
        if(lostArkApiEntry is not null) lostArkApiEntry.Visibility=editing ? Visibility.Visible : Visibility.Collapsed;
        if(lostArkApiGuide is not null) lostArkApiGuide.Visibility=editing ? Visibility.Visible : Visibility.Collapsed;
        if(lostArkApiRegistered is not null) lostArkApiRegistered.Visibility=editing ? Visibility.Collapsed : Visibility.Visible;
        if(lostArkApiInput is not null) lostArkApiInput.IsEnabled=!working;
        if(lostArkApiVerify is not null) {
            lostArkApiVerify.IsEnabled=!demo && !working && !string.IsNullOrWhiteSpace(lostArkApiInput?.Password);
            lostArkApiVerify.Content=working ? "검증 중…" : "검증";
        }
        if(lostArkApiChange is not null) lostArkApiChange.IsEnabled=!working;
        if(lostArkApiStatus is not null) {
            lostArkApiStatus.Visibility=editing && (working || lostArkApiFeedback) ? Visibility.Visible : Visibility.Collapsed;
            lostArkApiStatus.Text=working ? "API 키를 검증하는 중…" : StateText(lostArkApi,"message","");
            lostArkApiStatus.Foreground=Brush(working ? "muted" : "danger");
        }
    }
    private void OpenLostArkApiRegistration()
    {
        if(!settingsOpen) ToggleSettings();
        ShowSettingsSection("로스트아크 API");
        if(!Flag(lostArkApi,"configured")) lostArkApiInput?.Focus(FocusState.Programmatic);
    }

    private void ValidateApiRegistrationUI()
    {
        var saved=lostArkApi;
        try {
            lostArkApi=JsonSerializer.SerializeToElement(new { configured=false });
            foreach(var page in new[]{"weekly","records"}) {
                ShowPage(page); RebuildRecords();
                var prompt=(StackPanel)((Grid)Page.Children[1]).Children[0];
                if(((TextBlock)prompt.Children[0]).Text!="로스트아크 API 키를 등록해주세요.") throw new InvalidOperationException("API 등록 안내 누락");
                var register=(Button)prompt.Children[1];
                ((Microsoft.UI.Xaml.Automation.Provider.IInvokeProvider)new ButtonAutomationPeer(register).GetPattern(PatternInterface.Invoke)).Invoke();
                if(!settingsOpen || selectedSettingsSection!="로스트아크 API" || lostArkApiEntry?.Visibility!=Visibility.Visible || lostArkApiRegistered?.Visibility!=Visibility.Collapsed)
                    throw new InvalidOperationException("API 등록 버튼의 설정 진입 실패");
                if(settingsSections["로스트아크 API"].Children.OfType<Button>().Any()) throw new InvalidOperationException("이전 API 초기화 버튼이 남아 있습니다.");
                DismissSettings(false);
            }
            ReceiveLostArkApiResult(JsonSerializer.SerializeToElement(new { type="lostark_api_saved", success=true, configured=true }));
            OpenLostArkApiRegistration();
            if(lostArkApiEntry?.Visibility!=Visibility.Collapsed || lostArkApiGuide?.Visibility!=Visibility.Collapsed || lostArkApiRegistered?.Visibility!=Visibility.Visible)
                throw new InvalidOperationException("등록 완료 화면 전환 실패");
            ((Microsoft.UI.Xaml.Automation.Provider.IInvokeProvider)new ButtonAutomationPeer(lostArkApiChange!).GetPattern(PatternInterface.Invoke)).Invoke();
            if(lostArkApiEntry.Visibility!=Visibility.Visible || !Flag(lostArkApi,"configured")) throw new InvalidOperationException("키 보존 상태의 변경 화면 실패");
            ReceiveLostArkApiResult(JsonSerializer.SerializeToElement(new { type="lostark_api_saved", success=false, configured=true, message="테스트 검증 실패" }));
            if(!lostArkApiEditing || lostArkApiStatus?.Visibility!=Visibility.Visible || !Flag(lostArkApi,"configured"))
                throw new InvalidOperationException("검증 실패 시 편집 상태 또는 기존 키 유지 실패");
        }
        finally {
            DismissSettings(false); lostArkApi=saved; lostArkApiEditing=lostArkApiFeedback=lostArkApiSaving=false;
            UpdateLostArkApiSettings(); RebuildRecords();
        }
    }
}
