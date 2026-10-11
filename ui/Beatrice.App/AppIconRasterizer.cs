using System;
using System.Collections.Generic;
using System.IO;
using System.Threading.Tasks;
using Windows.Graphics.Imaging;
using Windows.Storage;

namespace BeatricePC;
// Decode the shared transparent app mark at the splash's physical pixel size.
internal static class AppIconRasterizer
{
    private static readonly Dictionary<int,byte[]> cache=new();
    internal static byte[] Load(int size)
    {
        if(!cache.TryGetValue(size,out var pixels)) {
            // Decode off the UI thread; this immutable local asset is cached for repeat startup.
            pixels=Task.Run(async () => {
                var file=await StorageFile.GetFileFromPathAsync(Path.Combine(AppContext.BaseDirectory,"Assets","beatrice-white.png"));
                using var stream=await file.OpenAsync(FileAccessMode.Read);
                var decoder=await BitmapDecoder.CreateAsync(stream);
                var transform=new BitmapTransform { ScaledWidth=(uint)size,ScaledHeight=(uint)size,InterpolationMode=BitmapInterpolationMode.Fant };
                var data=await decoder.GetPixelDataAsync(BitmapPixelFormat.Bgra8,BitmapAlphaMode.Premultiplied,transform,ExifOrientationMode.IgnoreExifOrientation,ColorManagementMode.DoNotColorManage);
                return data.DetachPixelData();
            }).GetAwaiter().GetResult();
            cache[size]=pixels;
        }
        return pixels;
    }
}