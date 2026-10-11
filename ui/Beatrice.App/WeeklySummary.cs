using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace BeatricePC;
internal sealed record WeeklyMoney(decimal Gold, decimal BoundGold, int Missing)
{
    internal static WeeklyMoney Zero => new(0,0,0);
    internal static WeeklyMoney Sum(IEnumerable<WeeklyMoney> values) => values.Aggregate(Zero,
        (a,b) => new(a.Gold+b.Gold,a.BoundGold+b.BoundGold,a.Missing+b.Missing));
}
internal sealed record WeeklyDungeon(string Name, string Mode, string Gates, WeeklyMoney Money);
internal sealed record WeeklyCharacter(string Name, string? Job, string Level, IReadOnlyList<WeeklyDungeon> Dungeons, WeeklyMoney Money);
internal sealed record WeeklyReceipt(DateTime Start, IReadOnlyList<WeeklyCharacter> Characters, WeeklyMoney Money);
internal static class WeeklySummary
{
    internal static WeeklyReceipt Build(IReadOnlyList<Raid> records, DateTime koreaNow)
    {
        var start=RecordPresentation.WeekStart(koreaNow);
        var selected=records.Select(r => (Raid:r,Valid:RecordPresentation.TryDate(r.Date,out var date),Date:date))
            .Where(r => r.Valid && RecordPresentation.InWeek(r.Date,start)).OrderByDescending(r => r.Date).ToArray();
        var characters=selected.GroupBy(r => r.Raid.Character,StringComparer.Ordinal).Select(character => {
            var rows=character.Select(r => r.Raid).ToArray();
            var dungeons=rows.GroupBy(r => (r.Dungeon,r.Mode)).Select(group => new WeeklyDungeon(
                group.Key.Dungeon,group.Key.Mode,GateLabel(group.Select(r => r.Gate)),
                WeeklyMoney.Sum(group.Select(r => ReadMoney(r.Detail))))).ToArray();
            var level=rows.Select(r => ReadLevel(r.ItemLevel)).FirstOrDefault(v => v > 0);
            return (Level:level,Character:new WeeklyCharacter(character.Key,rows.Select(r => r.CharacterClass).FirstOrDefault(v => !string.IsNullOrWhiteSpace(v)),
                RecordPresentation.ItemLevel(level.ToString(CultureInfo.InvariantCulture)),
                dungeons,WeeklyMoney.Sum(dungeons.Select(d => d.Money))));
        }).OrderByDescending(c => c.Level).Select(c => c.Character).ToArray();
        return new(start,characters,WeeklyMoney.Sum(characters.Select(c => c.Money)));
    }
    private static decimal ReadLevel(string? value) => decimal.TryParse(value,
        NumberStyles.AllowThousands | NumberStyles.AllowDecimalPoint,CultureInfo.InvariantCulture,out var level) && level > 0 ? level : 0;
    internal static WeeklyMoney ReadMoney(JsonElement detail)
    {
        if (detail.ValueKind == JsonValueKind.Object && detail.TryGetProperty("goldReward",out var receipt) && receipt.ValueKind == JsonValueKind.False) return WeeklyMoney.Zero;
        if (detail.ValueKind != JsonValueKind.Object || !detail.TryGetProperty("status",out var status) ||
            status.ValueKind != JsonValueKind.String || status.GetString() != "matched" || !detail.TryGetProperty("values",out var values) || values.ValueKind != JsonValueKind.Object ||
            !values.TryGetProperty("gold",out var gold) || gold.ValueKind != JsonValueKind.Number || !gold.TryGetDecimal(out var amount) || amount<0 || amount>1000000000000m || amount != decimal.Truncate(amount) ||
            !values.TryGetProperty("bound_percentage",out var bound) || bound.ValueKind != JsonValueKind.Number || !bound.TryGetDecimal(out var ratio) || ratio<0 || ratio>1)
            return new(0,0,1);
        var boundGold=decimal.Truncate(amount*ratio);
        return new(amount-boundGold,boundGold,0); // Extra reward purchases are not detected yet: do not subtract fee.
    }
    internal static string GateLabel(IEnumerable<string> labels)
    {
        var names=labels.Select(RecordPresentation.Gate).Where(v => v != "").Distinct().ToArray();
        var numbers=names.Select(v => Regex.Match(v,@"^(\d+)관문$")).ToArray();
        if(numbers.Any(m => !m.Success || !int.TryParse(m.Groups[1].Value,out _))) return string.Join(" · ",names);
        var gates=numbers.Select(m => int.Parse(m.Groups[1].Value,CultureInfo.InvariantCulture)).Distinct().OrderBy(v => v).ToArray();
        var ranges=new List<string>();
        for(int i=0;i<gates.Length;i++) {
            var first=gates[i]; var last=first;
            while(i+1<gates.Length && (long)gates[i+1]==(long)last+1) last=gates[++i];
            ranges.Add(first==last ? first.ToString(CultureInfo.InvariantCulture) : $"{first}–{last}");
        }
        return ranges.Count==0 ? "" : string.Join("·",ranges)+"관문";
    }
    internal static string Amount(decimal amount) => amount.ToString("N0",CultureInfo.InvariantCulture);
}
