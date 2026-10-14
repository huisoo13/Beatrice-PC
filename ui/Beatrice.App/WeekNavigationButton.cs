using System;
using Microsoft.UI;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Automation;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Shapes;
namespace BeatricePC;
internal static class WeekNavigationButton
{
    internal static Button Create(ViewTheme theme,bool older,string label,Action activate)
    {
        var arrow = new Polyline { Points = older ? new Microsoft.UI.Xaml.Media.PointCollection { new(12,4),new(6,10),new(12,16) } : new Microsoft.UI.Xaml.Media.PointCollection { new(6,4),new(12,10),new(6,16) },
            Stroke = theme.Brush("muted"), StrokeThickness = 1.75, StrokeStartLineCap = PenLineCap.Round, StrokeEndLineCap = PenLineCap.Round, Width = 20, Height = 20 };
        var button = new Button { Width = 44, Height = 44, Padding = new Thickness(0), CornerRadius = new CornerRadius(22),
            Background = new SolidColorBrush(Colors.Transparent), BorderBrush = theme.Brush("border"), BorderThickness = new Thickness(1), Content = arrow };
        AutomationProperties.SetName(button,label); ToolTipService.SetToolTip(button,label);
        foreach (var state in new[]{"", "PointerOver", "Pressed"}) button.Resources["ButtonBackground" + state] = state == "" ? new SolidColorBrush(Colors.Transparent) : theme.Brush("sidebar");
        button.Click += (_,_) => activate();
        return button;
    }
}
