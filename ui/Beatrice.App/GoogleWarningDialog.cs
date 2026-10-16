using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;

namespace BeatricePC;
internal static class GoogleWarningDialog
{
    internal static ContentDialog Create(XamlRoot root,ViewTheme theme,bool deleteBackup)
    {
        var content=new StackPanel { Spacing=16 };
        var explanation=theme.Text(deleteBackup
            ? "Drive에 저장된 PC 백업을 삭제합니다.\n이 PC의 기록은 그대로 유지됩니다."
            : "이 PC에서 Google 계정 연결을 해제합니다.\n다시 로그인할 때까지 자동 백업이 중단됩니다.",14,"muted");
        explanation.LineHeight=22;content.Children.Add(explanation);
        if(deleteBackup)content.Children.Add(theme.Text("삭제한 백업은 복구할 수 없습니다.",14,"danger"));
        content.Children.Add(theme.Text(deleteBackup
            ? "새 완료 기록이 생기면 다시 자동 백업합니다."
            : "PC 기록과 Drive 백업은 삭제되지 않습니다.",12,"muted"));
        var dialog=new WarningDialog { XamlRoot=root,RequestedTheme=ElementTheme.Dark,
            Title=theme.Text(deleteBackup ? "백업 데이터 삭제" : "Google 로그아웃",20,"text",true),
            Content=content,PrimaryButtonText=deleteBackup ? "백업 삭제" : "로그아웃",CloseButtonText="취소",
            DefaultButton=ContentDialogButton.Close,Background=theme.Brush("hover"),Foreground=theme.Brush("text"),
            BorderBrush=theme.Brush("border"),BorderThickness=new Thickness(1),CornerRadius=new CornerRadius(12),
            FontFamily=new FontFamily(theme.Font),FontSize=14 };
        foreach(var key in theme.Resources.Keys)dialog.Resources[key]=theme.Resources[key];
        dialog.Resources["ContentDialogMinWidth"]=320d;dialog.Resources["ContentDialogMaxWidth"]=420d;
        dialog.Resources["ContentDialogPadding"]=new Thickness(24);
        dialog.Resources["ContentDialogButtonSpacing"]=0d;
        dialog.Resources["ContentDialogTitleMargin"]=new Thickness(0,0,0,16);
        dialog.Resources["ContentDialogTopOverlay"]=new SolidColorBrush(Microsoft.UI.Colors.Transparent);
        dialog.Resources["ContentDialogSeparatorThickness"]=new Thickness(0);
        dialog.Resources["OverlayCornerRadius"]=new CornerRadius(12);
        dialog.Resources["ControlCornerRadius"]=new CornerRadius(8);
        foreach(var state in new[]{"","PointerOver","Pressed","Disabled"}) {
            dialog.Resources["ButtonBackground"+state]=theme.Brush(state is "PointerOver" or "Pressed" ? "sidebar" : "surface");
            dialog.Resources["ButtonForeground"+state]=theme.Brush("danger");
            dialog.Resources["ButtonBorderBrush"+state]=theme.Brush("border");
            dialog.Resources["AccentButtonBackground"+state]=theme.Brush(state is "PointerOver" or "Pressed" ? "hover" : "sidebar");
            dialog.Resources["AccentButtonForeground"+state]=theme.Brush("text");
            dialog.Resources["AccentButtonBorderBrush"+state]=theme.Brush("border");
        }
        Style ButtonStyle() {
            var style=new Style(typeof(Button));
            style.Setters.Add(new Setter(Control.FontFamilyProperty,new FontFamily(theme.Font)));
            style.Setters.Add(new Setter(Control.FontSizeProperty,14d));
            style.Setters.Add(new Setter(FrameworkElement.MinHeightProperty,44d));
            style.Setters.Add(new Setter(Control.PaddingProperty,new Thickness(16,10,16,10)));
            style.Setters.Add(new Setter(Control.CornerRadiusProperty,new CornerRadius(8)));
            return style;
        }
        dialog.PrimaryButtonStyle=ButtonStyle();dialog.CloseButtonStyle=ButtonStyle();
        return dialog;
    }
    private sealed class WarningDialog : ContentDialog
    {
        protected override void OnApplyTemplate()
        {
            base.OnApplyTemplate();
            // The default button's accent Style replaces CloseButtonStyle.
            // Set geometry on the template parts without changing cancel semantics.
            if(GetTemplateChild("CommandSpace") is Grid commands)commands.Padding=new Thickness(0);
            foreach(var name in new[]{"PrimaryButton","CloseButton"}) {
                if(GetTemplateChild(name) is not Button button)continue;
                var primary=name=="PrimaryButton";
                button.MinHeight=44;button.Padding=new Thickness(16,10,16,10);button.Margin=new Thickness(0);
                button.HorizontalAlignment=HorizontalAlignment.Stretch;button.VerticalAlignment=VerticalAlignment.Stretch;
                button.CornerRadius=primary ? new CornerRadius(0,0,0,11) : new CornerRadius(0,0,11,0);
                button.BorderThickness=primary ? new Thickness(0,1,1,0) : new Thickness(0,1,0,0);
            }
        }
    }
}
