using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Automation.Peers;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Imaging;
using Microsoft.UI.Xaml.Shapes;

namespace BeatricePC;
internal sealed class GoogleAccountView
{
    public Grid Element { get; } = new() { ColumnSpacing=12 };
    private readonly TextBlock nameText, emailText;
    private readonly Ellipse photo;
    private BitmapImage? currentPhoto;
    private string picturePath="";
    public GoogleAccountView(ViewTheme theme)
    {
        Element.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(40) });
        Element.ColumnDefinitions.Add(new ColumnDefinition { Width=new GridLength(1,GridUnitType.Star) });
        var avatar=new Grid { Width=40,Height=40,VerticalAlignment=VerticalAlignment.Center };
        avatar.Children.Add(new Image { Source=new SvgImageSource(new Uri("ms-appx:///Assets/profile-placeholder.svg")),Stretch=Stretch.Uniform });
        photo=new Ellipse { Width=40,Height=40 }; avatar.Children.Add(photo);
        AutomationProperties.SetAccessibilityView(avatar,AccessibilityView.Raw);
        Element.Children.Add(avatar);
        var labels=new StackPanel { Spacing=2,VerticalAlignment=VerticalAlignment.Center };
        nameText=theme.Text("",16,"text",true); emailText=theme.Text("",12,"muted");
        labels.Children.Add(nameText); labels.Children.Add(emailText);
        Grid.SetColumn(labels,1); Element.Children.Add(labels);
    }
    public void Update(string name,string email,string picture)
    {
        nameText.Text=string.IsNullOrWhiteSpace(name) ? "Google 계정" : name;
        emailText.Text=email;
        AutomationProperties.SetName(Element,"로그인된 Google 계정: " + nameText.Text + ", " + email);
        if (picturePath==picture) return;
        picturePath=picture; currentPhoto=null; photo.Fill=null;
        if (!Uri.TryCreate(picture,UriKind.Absolute,out var uri) || uri.Scheme != Uri.UriSchemeHttps || !string.IsNullOrEmpty(uri.UserInfo)) return;
        var source=new BitmapImage(); currentPhoto=source;
        // Keep the brush in the visual tree so WinUI requests the remote image.
        // An empty/failed brush leaves the placeholder underneath visible.
        source.ImageFailed += (_,_) => { if (ReferenceEquals(currentPhoto,source)) photo.Fill=null; };
        photo.Fill=new ImageBrush { ImageSource=source,Stretch=Stretch.UniformToFill };
        source.UriSource=uri;
    }
}
