using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
namespace BeatricePC;
internal sealed record Raid(string Character, string Dungeon, string Mode, string Gate, string Date, JsonElement Detail, string? CharacterClass = null, string? CharacterEmblem = null, string? ItemLevel = null);
internal sealed record EngineProfile(string Character, string Message, string CharacterState,
    string? Dungeon, string DungeonSubtitle, string DungeonState, string? CharacterClass = null, string? CharacterEmblem = null);
internal sealed record EngineSnapshot(string Status, bool Busy, bool CatalogBusy, EngineProfile Profile,
    JsonElement RecordData, string RecordsJson, JsonElement Clients, long Selected,
    string CatalogStatus, DateTimeOffset? CatalogLastUpdated, DateTimeOffset? CatalogRefreshAvailableAt,
    JsonElement? LostArkApi, JsonElement? Google, JsonElement? Drive, JsonElement? CurrencyImages = null)
{
    public IReadOnlyList<Raid> Records => RecordData.EnumerateArray().Select(row => new Raid(
        row.GetProperty("character").GetString()!, row.GetProperty("dungeon").GetString()!,
        row.GetProperty("mode").GetString()!, row.GetProperty("gate").GetString()!,
        row.GetProperty("date").GetString()!, row.GetProperty("detail").Clone(),
        row.TryGetProperty("characterClass",out var job) ? job.GetString() : null,
        row.TryGetProperty("characterEmblem",out var emblem) ? emblem.GetString() : null,
        row.TryGetProperty("itemLevel",out var level) ? level.GetString() : null)).ToArray();
    private static JsonElement? Optional(JsonElement value, string name) =>
        value.TryGetProperty(name, out var item) ? item.Clone() : null;
    public static EngineSnapshot Parse(JsonElement value)
    {
        var profile = value.GetProperty("profile");
        var characterState = profile.TryGetProperty("characterState", out var state) ? state.GetString()! :
            profile.GetProperty("active").GetBoolean() ? "playing" : "unset";
        var dungeon = profile.TryGetProperty("dungeon", out var name) ? name.GetString() : null;
        var records = value.GetProperty("records");
        DateTimeOffset? updated = value.TryGetProperty("catalogLastUpdated", out var time) &&
            DateTimeOffset.TryParse(time.GetString(), out var parsed) ? parsed : null;
        DateTimeOffset? deadline = value.TryGetProperty("catalogRefreshAvailableAt", out var available) &&
            available.TryGetDouble(out var seconds) ? DateTimeOffset.FromUnixTimeMilliseconds((long)(seconds*1000)) : null;
        return new(value.GetProperty("status").GetString()!, value.GetProperty("busy").GetBoolean(),
            value.GetProperty("catalogBusy").GetBoolean(),
            new(profile.GetProperty("character").GetString()!, profile.GetProperty("message").GetString()!,
                characterState, dungeon, string.IsNullOrEmpty(dungeon) ? "" : profile.GetProperty("dungeonSubtitle").GetString()!,
                string.IsNullOrEmpty(dungeon) ? "" : profile.GetProperty("dungeonState").GetString()!,
                profile.TryGetProperty("characterClass",out var job) ? job.GetString() : null,
                profile.TryGetProperty("characterEmblem",out var emblem) ? emblem.GetString() : null),
            records.Clone(), records.GetRawText(), value.GetProperty("clients").Clone(), value.GetProperty("selected").GetInt64(),
            value.GetProperty("catalogStatus").GetString()!, updated, deadline,
            Optional(value,"lostArkApi"), Optional(value,"google"), Optional(value,"drive"), Optional(value,"currencyImages"));
    }
}
