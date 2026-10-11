using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
namespace BeatricePC;
internal static class ApiKeyRequiredView
{
    public static void Render(StackPanel page,ScrollViewer viewport,ViewTheme theme,string title,Action register)
    {
        page.Spacing=12;
        var heading=theme.Text(title,20,"text",true);
        page.Children.Add(heading);
        var host=new Grid();
        var prompt=new StackPanel { Spacing=12, VerticalAlignment=VerticalAlignment.Center, HorizontalAlignment=HorizontalAlignment.Center };
        var message=theme.Text("로스트아크 API 키를 등록해주세요.",14,"muted",false);
        message.TextAlignment=TextAlignment.Center; prompt.Children.Add(message);
        var button=new Button { Content="등록하기", MinHeight=44, Padding=new Thickness(16,8,16,8),
            FontFamily=new FontFamily(theme.Font), FontSize=14, HorizontalAlignment=HorizontalAlignment.Center };
        AutomationProperties.SetName(button,"로스트아크 API 키 등록하기");
        button.Click+=(_,_)=>register(); prompt.Children.Add(button); host.Children.Add(prompt); page.Children.Add(host);
        void Resize() => host.MinHeight=Math.Max(0,viewport.ActualHeight-page.Margin.Top-page.Margin.Bottom-heading.ActualHeight-page.Spacing);
        SizeChangedEventHandler resize=(_,_)=>Resize();
        host.Loaded+=(_,_)=> { viewport.SizeChanged+=resize; Resize(); };
        host.Unloaded+=(_,_)=>viewport.SizeChanged-=resize;
    }
}
