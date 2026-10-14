using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using System.Threading.Tasks;
using Microsoft.UI.Dispatching;
using Microsoft.UI.Xaml.Controls;
using Microsoft.UI.Xaml.Media;
using Windows.UI;

namespace BeatricePC;
/// <summary>Per-pixel alpha splash. Main WinUI window and its XAML host are never modified.</summary>
internal sealed class StartupWindow
{
    internal sealed class ProgressState
    {
        private double value;
        public double Maximum => 3;
        public event Action? Changed;
        public double Value { get => value; set { if (this.value == value) return; this.value = value; Changed?.Invoke(); } }
    }
    public ProgressState Progress { get; } = new();
    public event Action? ReadyToStart;
    public event Action? CancelStartup;
    public int PixelSize { get; }
    public double RenderedProgress => displayed;
    private readonly DispatcherQueue queue = DispatcherQueue.GetForCurrentThread();
    private readonly System.Threading.Timer timer;
    private int frameQueued;
    private readonly Stopwatch motion = new();
    private readonly Color background;
    private readonly double scale;
    private readonly byte[] basePixels, pixels;
    private readonly byte[] iconPixels;
    private readonly int iconSize, iconOrigin;
    private readonly IntPtr hwnd, dc, bitmap, previousBitmap, bits;
    private Point origin;
    private double displayed, from, target;
    private bool activated;
    private volatile bool completed;
    private TaskCompletionSource<bool>? settled;
    private static readonly Dictionary<IntPtr, StartupWindow> windows = new();
    private static readonly WindowProc callback = DispatchWindow;
    private const int SurfaceSize = 256, ShadowInset = 24;
    private const double ShadowOpacity = .10, ShadowBlur = 8, ShadowOffsetY = 4;
    private const string ClassName = "BeatriceSmoothSplash";
    private static bool registered;

    public StartupWindow(Brush surfaceBrush, IntPtr owner)
    {
        background = ((SolidColorBrush)surfaceBrush).Color;
        scale = GetDpiForWindow(owner) / 96.0;
        PixelSize = (int)Math.Round((SurfaceSize + ShadowInset * 2) * scale);
        basePixels = new byte[PixelSize * PixelSize * 4]; pixels = new byte[basePixels.Length];
        iconSize=(int)Math.Round(128*scale);
        iconPixels=AppIconRasterizer.Load(iconSize);
        iconOrigin=(PixelSize-iconSize)/2;
        RasterizeSurface();
        if (!registered)
        {
            var cls = new WindowClass { Size = (uint)Marshal.SizeOf<WindowClass>(), Instance = GetModuleHandle(null),
                Procedure = Marshal.GetFunctionPointerForDelegate(callback), ClassName = ClassName, Cursor = LoadCursor(IntPtr.Zero, new IntPtr(32512)) };
            if (RegisterClassEx(ref cls) == 0) throw new Win32Exception(Marshal.GetLastWin32Error());
            registered = true;
        }
        var area = Microsoft.UI.Windowing.DisplayArea.GetFromWindowId(
            Microsoft.UI.Win32Interop.GetWindowIdFromWindow(owner), Microsoft.UI.Windowing.DisplayAreaFallback.Primary).WorkArea;
        origin = new Point { X = area.X + (area.Width - PixelSize)/2, Y = area.Y + (area.Height - PixelSize)/2 };
        hwnd = CreateWindowEx(0x00080080, ClassName, "Beatrice PC · 준비 중", 0x80000000,
            origin.X, origin.Y, PixelSize, PixelSize, IntPtr.Zero, IntPtr.Zero, GetModuleHandle(null), IntPtr.Zero);
        if (hwnd == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
        windows[hwnd] = this;
        var screen = GetDC(IntPtr.Zero);
        dc = CreateCompatibleDC(screen);
        var info = new BitmapInfo { Size = 40, Width = PixelSize, Height = -PixelSize, Planes = 1, BitCount = 32, ImageSize = (uint)pixels.Length };
        bitmap = CreateDIBSection(screen, ref info, 0, out bits, IntPtr.Zero, 0);
        ReleaseDC(IntPtr.Zero, screen);
        if (bitmap == IntPtr.Zero) { DestroyWindow(hwnd); throw new Win32Exception(Marshal.GetLastWin32Error()); }
        previousBitmap = SelectObject(dc, bitmap);
        timer = new System.Threading.Timer(_ => {
            if (completed || System.Threading.Interlocked.Exchange(ref frameQueued, 1) != 0) return;
            if (!queue.TryEnqueue(() => { System.Threading.Interlocked.Exchange(ref frameQueued, 0); try { TickProgress(); } catch (Exception error) { System.IO.File.WriteAllText(System.IO.Path.Combine(AppContext.BaseDirectory,"splash-frame-error.log"),error.ToString()); } }))
                System.Threading.Interlocked.Exchange(ref frameQueued, 0);
        }, null, System.Threading.Timeout.Infinite, System.Threading.Timeout.Infinite);
        Progress.Changed += AnimateProgress;
        Paint();
    }
    public void Activate()
    {
        if (activated || completed) return;
        activated = true; ShowWindow(hwnd, 8);
        queue.TryEnqueue(() => ReadyToStart?.Invoke());
    }
    private void AnimateProgress()
    {
        if (completed) return;
        settled?.TrySetResult(true);
        target = Math.Clamp(Progress.Value / Progress.Maximum, 0, 1);
        from = displayed;
        settled = new TaskCompletionSource<bool>(TaskCreationOptions.RunContinuationsAsynchronously);
        if (!new Windows.UI.ViewManagement.UISettings().AnimationsEnabled || Math.Abs(target-from) < .0001)
        { displayed = target; Paint(); timer.Change(System.Threading.Timeout.Infinite, System.Threading.Timeout.Infinite); settled.TrySetResult(true); return; }
        motion.Restart(); timer.Change(0, 16);
    }
    private void TickProgress()
    {
        if (completed) return;
        var t = Math.Clamp(motion.Elapsed.TotalMilliseconds / 280, 0, 1);
        displayed = from + (target-from) * (1 - Math.Pow(1-t, 3));
        Paint();
        if (t >= 1) { timer.Change(System.Threading.Timeout.Infinite, System.Threading.Timeout.Infinite); settled?.TrySetResult(true); }
    }
    public Task WaitForProgressAsync() => settled?.Task ?? Task.CompletedTask;
    public void Complete()
    {
        if (completed) return;
        completed = true; timer.Change(System.Threading.Timeout.Infinite, System.Threading.Timeout.Infinite); timer.Dispose();
        Progress.Changed -= AnimateProgress;
        settled?.TrySetResult(true);
        windows.Remove(hwnd); DestroyWindow(hwnd);
        SelectObject(dc, previousBitmap); DeleteObject(bitmap); DeleteDC(dc);
    }
    private void Paint()
    {
        if (completed) return;
        Buffer.BlockCopy(basePixels, 0, pixels, 0, pixels.Length);
        // Reveal the original white mark from the bottom, retaining its alpha edges.
        // The faint unfilled mark keeps the app identity visible while loading.
        for (var y = 0; y < iconSize; y++)
        for (var x = 0; x < iconSize; x++)
        {
            var offset=((y+iconOrigin)*PixelSize+x+iconOrigin)*4;
            var iconOffset=(y*iconSize+x)*4;
            var coverage=Math.Clamp(displayed*iconSize-(iconSize-y-1),0,1);
            var intensity=.16+.84*coverage;
            var opacity=iconPixels[iconOffset+3]/255.0*intensity;
            for(var channel=0;channel<3;channel++)
                pixels[offset+channel]=(byte)Math.Round(iconPixels[iconOffset+channel]*intensity+pixels[offset+channel]*(1-opacity));
        }
        Marshal.Copy(pixels, 0, bits, pixels.Length);
        var size = new Point { X = PixelSize, Y = PixelSize }; var source = new Point();
        var blend = new Blend { Alpha = 255, Format = 1 };
        if (!UpdateLayeredWindow(hwnd, IntPtr.Zero, ref origin, ref size, dc, ref source, 0, ref blend, 2))
            throw new Win32Exception(Marshal.GetLastWin32Error());
    }
    private void RasterizeSurface()
    {
        for (var y=0; y<PixelSize; y++)
        for (var x=0; x<PixelSize; x++)
        {
            var px = (x+.5)/scale-ShadowInset; var py = (y+.5)/scale-ShadowInset;
            var qx = Math.Abs(px-128)-96; var qy = Math.Abs(py-128)-96;
            var distance = Math.Sqrt(Math.Pow(Math.Max(qx,0),2)+Math.Pow(Math.Max(qy,0),2)) + Math.Min(Math.Max(qx,qy),0) - 32;
            var alpha = Math.Clamp(.5-distance*scale,0,1);

            var offset = (y*PixelSize+x)*4;
            basePixels[offset] = (byte)Math.Round(background.B*alpha);
            basePixels[offset+1] = (byte)Math.Round(background.G*alpha);
            basePixels[offset+2] = (byte)Math.Round(background.R*alpha);
            // Black Gaussian falloff behind the rounded surface; cache once per DPI.
            var shadowQy = Math.Abs(py-128-ShadowOffsetY)-96;
            var shadowDistance = Math.Sqrt(Math.Pow(Math.Max(qx,0),2)+Math.Pow(Math.Max(shadowQy,0),2))
                + Math.Min(Math.Max(qx,shadowQy),0)-32;
            var outside = Math.Max(shadowDistance,0);
            var shadow = ShadowOpacity*Math.Exp(-outside*outside/(2*ShadowBlur*ShadowBlur));
            // Fade the final two pixels to fully transparent, avoiding a rectangular edge.
            var edge = Math.Min(Math.Min(x, y), Math.Min(PixelSize-1-x, PixelSize-1-y));
            shadow *= Math.Clamp(edge/(2*scale),0,1);
            basePixels[offset+3] = (byte)Math.Round(255*(alpha+shadow*(1-alpha)));
        }
    }
    public async Task SaveCaptureAsync(Windows.Storage.StorageFolder folder,string name="splash-native.png")
    {
        var file=await folder.CreateFileAsync(name,Windows.Storage.CreationCollisionOption.ReplaceExisting);
        using var stream=await file.OpenAsync(Windows.Storage.FileAccessMode.ReadWrite);
        var encoder=await Windows.Graphics.Imaging.BitmapEncoder.CreateAsync(Windows.Graphics.Imaging.BitmapEncoder.PngEncoderId,stream);
        encoder.SetPixelData(Windows.Graphics.Imaging.BitmapPixelFormat.Bgra8,Windows.Graphics.Imaging.BitmapAlphaMode.Premultiplied,
            (uint)PixelSize,(uint)PixelSize,96*scale,96*scale,pixels);
        await encoder.FlushAsync();
    }
    private static IntPtr DispatchWindow(IntPtr h,uint m,IntPtr w,IntPtr l)
    {
        if(m==0x10 && windows.TryGetValue(h,out var window)){window.CancelStartup?.Invoke();return IntPtr.Zero;}
        return DefWindowProc(h,m,w,l);
    }
    private delegate IntPtr WindowProc(IntPtr h,uint m,IntPtr w,IntPtr l);
    [StructLayout(LayoutKind.Sequential)] private struct Point { public int X,Y; }
    [StructLayout(LayoutKind.Sequential,Pack=1)] private struct Blend { public byte Operation,Flags,Alpha,Format; }
    [StructLayout(LayoutKind.Sequential)] private struct BitmapInfo { public uint Size; public int Width,Height; public ushort Planes,BitCount; public uint Compression,ImageSize; public int XPels,YPels; public uint ColorsUsed,ColorsImportant,Colors; }
    [StructLayout(LayoutKind.Sequential,CharSet=CharSet.Unicode)] private struct WindowClass { public uint Size,Style; public IntPtr Procedure; public int ClassExtra,WindowExtra; public IntPtr Instance,Icon,Cursor,Background; public string? MenuName,ClassName; public IntPtr SmallIcon; }
    [DllImport("user32.dll",CharSet=CharSet.Unicode,SetLastError=true)] private static extern ushort RegisterClassEx(ref WindowClass cls);
    [DllImport("kernel32.dll",CharSet=CharSet.Unicode)] private static extern IntPtr GetModuleHandle(string? name);
    [DllImport("user32.dll",CharSet=CharSet.Unicode)] private static extern IntPtr LoadCursor(IntPtr instance,IntPtr name);
    [DllImport("user32.dll",CharSet=CharSet.Unicode,SetLastError=true)] private static extern IntPtr CreateWindowEx(uint ex,string cls,string title,uint style,int x,int y,int width,int height,IntPtr owner,IntPtr menu,IntPtr instance,IntPtr param);
    [DllImport("user32.dll")] private static extern uint GetDpiForWindow(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern bool ShowWindow(IntPtr hwnd,int command);
    [DllImport("user32.dll")] private static extern bool DestroyWindow(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern IntPtr DefWindowProc(IntPtr hwnd,uint m,IntPtr w,IntPtr l);
    [DllImport("user32.dll")] private static extern IntPtr GetDC(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern int ReleaseDC(IntPtr hwnd,IntPtr dc);
    [DllImport("gdi32.dll")] private static extern IntPtr CreateCompatibleDC(IntPtr dc);
    [DllImport("gdi32.dll",SetLastError=true)] private static extern IntPtr CreateDIBSection(IntPtr dc,ref BitmapInfo info,uint usage,out IntPtr bits,IntPtr section,uint offset);
    [DllImport("gdi32.dll")] private static extern IntPtr SelectObject(IntPtr dc,IntPtr value);
    [DllImport("gdi32.dll")] private static extern bool DeleteObject(IntPtr value);
    [DllImport("gdi32.dll")] private static extern bool DeleteDC(IntPtr dc);
    [DllImport("user32.dll",SetLastError=true)] private static extern bool UpdateLayeredWindow(IntPtr hwnd,IntPtr destination,ref Point origin,ref Point size,IntPtr dc,ref Point source,uint key,ref Blend blend,uint flags);
}
