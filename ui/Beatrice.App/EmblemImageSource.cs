using System;
using System.Xml;
using System.Xml.Linq;
using System.Text.RegularExpressions;
using Microsoft.UI.Xaml.Media.Imaging;
using Windows.Storage;
using Windows.Storage.Streams;
namespace BeatricePC;
internal static class EmblemImageSource
{
    public static async System.Threading.Tasks.Task<SvgImageSource?> Load(string path,double size,Windows.UI.Color color)
    {
        try {
            var file = await StorageFile.GetFileFromPathAsync(path);
            var svg = await FileIO.ReadTextAsync(file);
            var tint = $"#{color.R:X2}{color.G:X2}{color.B:X2}";
            using var reader = XmlReader.Create(new System.IO.StringReader(svg),
                new XmlReaderSettings { DtdProcessing = DtdProcessing.Prohibit, XmlResolver = null });
            var document = XDocument.Load(reader);
            bool Painted(string value) => !string.Equals(value.Trim(),"none",StringComparison.OrdinalIgnoreCase)
                && !string.Equals(value.Trim(),"transparent",StringComparison.OrdinalIgnoreCase);
            foreach (var element in document.Root!.DescendantsAndSelf()) {
                foreach (var attribute in element.Attributes()) {
                    if (attribute.Name.LocalName is "fill" or "stroke" or "color" && Painted(attribute.Value))
                        attribute.Value = tint;
                    else if (attribute.Name.LocalName == "style")
                        attribute.Value = Regex.Replace(attribute.Value,@"(?<property>fill|stroke|color)\s*:\s*(?<value>[^;]+)",
                            match => Painted(match.Groups["value"].Value) ? match.Groups["property"].Value + ":" + tint : match.Value,
                            RegexOptions.IgnoreCase);
                }
            }
            using var stream = new InMemoryRandomAccessStream();
            using (var writer = new DataWriter(stream)) {
                writer.WriteBytes(System.Text.Encoding.UTF8.GetBytes(document.ToString(SaveOptions.DisableFormatting)));
                await writer.StoreAsync();
                writer.DetachStream();
            }
            stream.Seek(0);
            var source = new SvgImageSource { RasterizePixelWidth = size, RasterizePixelHeight = size };
            if (await source.SetSourceAsync(stream) == SvgImageSourceLoadStatus.Success) return source;
        }
        catch { /* Callers own their fallback UI. */ }
        return null;
    }
}
