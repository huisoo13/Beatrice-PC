using System;
using System.Globalization;
using System.Linq;

namespace BeatricePC;
internal static class RecordPresentation
{
    internal static readonly TimeSpan KoreaOffset = TimeSpan.FromHours(9);
    internal static DateTime KoreaNow(DateTimeOffset instant) => instant.ToOffset(KoreaOffset).DateTime;
    internal static DateTime WeekStart(DateTime local)
    {
        var candidate = local.Date.AddDays(-((7 + (int)local.DayOfWeek - (int)DayOfWeek.Wednesday) % 7)).AddHours(6);
        return local < candidate ? candidate.AddDays(-7) : candidate;
    }
    internal static bool TryDate(string text, out DateTime local)
    {
        if (DateTime.TryParseExact(text, new[]{"yyyy.MM.dd HH:mm", "yyyy.MM.dd HH:mm:ss", "yyyy. M. d HH:mm", "yyyy-MM-dd HH:mm:ss", "yyyy-MM-dd HH:mm"}, CultureInfo.InvariantCulture, DateTimeStyles.None, out local)) return true;
        if (DateTimeOffset.TryParse(text,CultureInfo.InvariantCulture,DateTimeStyles.None,out var instant))
        { local = KoreaNow(instant); return true; }
        local = default; return false;
    }
    internal static bool InWeek(DateTime local, DateTime start) => local >= start && local < start.AddDays(7);
    internal static string Gate(string gate) => string.IsNullOrWhiteSpace(gate) || gate is "레이드 전체" or "전체" or "관문 없음" or "0관문" ? "" : gate.Trim();
    internal static string Particle(string noun, string pair)
    {
        var last = noun.TrimEnd().LastOrDefault(char.IsLetterOrDigit);
        var consonant = last >= '\uAC00' && last <= '\uD7A3' ? (last - '\uAC00') % 28 != 0
            : char.IsDigit(last) ? "013678".Contains(last) : "lmnrLMNR".Contains(last);
        return pair switch { "은/는" => consonant ? "은" : "는", "이/가" => consonant ? "이" : "가", "을/를" => consonant ? "을" : "를", _ => throw new ArgumentException(nameof(pair)) };
    }
    internal static string Sentence(string character,string dungeon,string mode,string gate)
    {
        gate = Gate(gate);
        var target = string.Join(" ",new[]{dungeon,mode,gate}.Where(v => !string.IsNullOrWhiteSpace(v)));
        return character + Particle(character,"이/가") + " " + target + Particle(target,"을/를") + " 클리어했습니다.";
    }
}
