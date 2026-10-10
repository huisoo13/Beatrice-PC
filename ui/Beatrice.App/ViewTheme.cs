using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
namespace BeatricePC;
internal delegate TextBlock TextFactory(string value, int size = 16, string color = "text", bool bold = false);
internal sealed record ViewTheme(string Font, string SemiboldFont, ResourceDictionary Resources,
    Func<string, SolidColorBrush> Brush, TextFactory Text);
