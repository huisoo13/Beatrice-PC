using System;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
namespace BeatricePC;
internal sealed class CharacterPortraitView
{
    private readonly Image image;
    private readonly ImageSource fallback;
    private readonly Windows.UI.Color color;
    private string? current;
    private int generation;
    public CharacterPortraitView(Image image,Windows.UI.Color color)
    { this.image = image; this.color = color; fallback = image.Source; }
    public void Update(string? path,string? job)
    {
        AutomationProperties.SetName(image,string.IsNullOrEmpty(job) ? "캐릭터 이미지" : job + " 직업 문양");
        ToolTipService.SetToolTip(image,string.IsNullOrEmpty(job) ? null : job);
        if (current == path) return;
        current = path; var request = ++generation;
        image.Source = fallback;
        if (!string.IsNullOrWhiteSpace(path)) _ = Load(path,request);
    }
    private async System.Threading.Tasks.Task Load(string path,int request)
    {
        var source = await EmblemImageSource.Load(path,image.Width,color);
        if (source is not null && request == generation) image.Source = source;
    }
}
