using System;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Microsoft.UI.Xaml.Media.Animation;
using Windows.Foundation;

namespace BeatricePC;
// Animate the space occupied by the content, so siblings follow the same layout each frame.
internal sealed class SynchronizedExpander
{
    private readonly Expander expander;
    private static readonly System.Runtime.CompilerServices.ConditionalWeakTable<Expander,SynchronizedExpander> instances = new();
    internal static SynchronizedExpander For(Expander control) => instances.GetValue(control,c => new SynchronizedExpander(c));
    private Border? viewport;
    private Border? contentSurface;
    private Storyboard? motion;
    private bool expanded;
    private double measuredWidth;
    private readonly RectangleGeometry clip = new();
    internal bool ForceReducedMotion { get; set; }

    private SynchronizedExpander(Expander control)
    {
        expander = control;
        expander.RegisterPropertyChangedCallback(Expander.IsExpandedProperty,(_, _) => UpdateChevron(expander.IsExpanded));
        expander.Loaded += (_, _) => ApplyTemplate();
        expander.Expanding += (_, _) => ResizeContent(true,true);
        expander.Collapsed += (_, _) => ResizeContent(false,true);
        expander.SizeChanged += (_, args) => {
            if (Math.Abs(args.NewSize.Width - measuredWidth) > .5) ResizeContent(expanded,false);
        };
        expander.Unloaded += (_, _) => { motion?.Stop(); motion = null; };
    }
    private static FrameworkElement? Find(DependencyObject root,string name)
    {
        if (root is FrameworkElement element && element.Name == name) return element;
        for (var i=0;i<VisualTreeHelper.GetChildrenCount(root);i++)
            if (Find(VisualTreeHelper.GetChild(root,i),name) is FrameworkElement found) return found;
        return null;
    }
    private void ApplyTemplate()
    {
        expander.ApplyTemplate();
        if (Find(expander,"ExpanderHeader") is Control header) header.ApplyTemplate();
        viewport = Find(expander,"ExpanderContentClip") as Border;
        contentSurface = Find(expander,"ExpanderContent") as Border;
        if (viewport is null || contentSurface is null) return;
        // Keep the full content laid out behind an animated, clipped viewport.
        contentSurface.Visibility = Visibility.Visible;
        contentSurface.MinHeight = 0;
        contentSurface.VerticalAlignment = VerticalAlignment.Top;
        contentSurface.RenderTransform = new CompositeTransform();
        viewport.VerticalAlignment = VerticalAlignment.Top;
        viewport.Clip = clip;
        viewport.SizeChanged += (_, _) => UpdateClip();
        expanded = expander.IsExpanded;
        ResizeContent(expanded,false);
    }
    internal double ChevronAngle => Find(expander,"RewardChevron") is Microsoft.UI.Xaml.Shapes.Path arrow && arrow.RenderTransform is RotateTransform rotation ? rotation.Angle : double.NaN;
    private void UpdateChevron(bool open)
    {
        if (Find(expander,"RewardChevron") is Microsoft.UI.Xaml.Shapes.Path arrow && arrow.RenderTransform is RotateTransform rotation)
            rotation.Angle = open ? 180 : 0;
    }
    private void UpdateClip()
    {
        if (viewport is not null) clip.Rect = new Rect(0,0,Math.Max(0,viewport.ActualWidth),Math.Max(0,viewport.ActualHeight));
    }
    internal void RefreshContent() => ResizeContent(expander.IsExpanded,true);
    private void ResizeContent(bool open, bool animate)
    {
        expanded = open;
        UpdateChevron(open);
        if (viewport is null || contentSurface is null || expander.Content is not FrameworkElement content) return;
        var width = viewport.ActualWidth > 0 ? viewport.ActualWidth : expander.ActualWidth;
        if (width <= 0) return;
        measuredWidth = expander.ActualWidth;
        contentSurface.Visibility = Visibility.Visible;
        content.Measure(new Size(width,double.PositiveInfinity));
        var fullHeight = content.DesiredSize.Height;
        var from = double.IsNaN(viewport.Height) ? viewport.ActualHeight : viewport.Height;
        motion?.Stop(); motion = null;
        contentSurface.Height = fullHeight;
        contentSurface.Visibility = Visibility.Visible;
        contentSurface.RenderTransform = new CompositeTransform();
        var target = open ? fullHeight : 0;
        var animationsEnabled = !ForceReducedMotion && new Windows.UI.ViewManagement.UISettings().AnimationsEnabled;
        if (!animate || !animationsEnabled || Math.Abs(from-target) < .5)
        { viewport.Height = target; contentSurface.Visibility = open ? Visibility.Visible : Visibility.Collapsed; UpdateClip(); return; }
        viewport.Height = from;
        var animation = new DoubleAnimation { From = from, To = target,
            Duration = new Duration(TimeSpan.FromMilliseconds(open ? 220 : 180)), EnableDependentAnimation = true,
            EasingFunction = new CubicEase { EasingMode = EasingMode.EaseInOut } };
        Storyboard.SetTarget(animation,viewport); Storyboard.SetTargetProperty(animation,"Height");
        var storyboard = new Storyboard(); storyboard.Children.Add(animation); motion = storyboard;
        storyboard.Completed += (_, _) => {
            if (motion != storyboard) return;
            viewport.Height = target; storyboard.Stop(); motion = null;
            if (!open) contentSurface.Visibility = Visibility.Collapsed;
            UpdateClip();
        };
        storyboard.Begin();
    }
}