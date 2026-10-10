using BeatricePC;
var passed=0;
void Equal<T>(T actual,T expected,string name){if(!EqualityComparer<T>.Default.Equals(actual,expected))throw new Exception(name+": "+actual+" != "+expected);passed++;}
var start=new DateTime(2026,10,7,6,0,0);
Equal(RecordPresentation.WeekStart(start.AddTicks(-1)),start.AddDays(-7),"Wednesday before 06:00");
Equal(RecordPresentation.WeekStart(start),start,"Wednesday at 06:00");
Equal(RecordPresentation.WeekStart(start.AddDays(7).AddTicks(-1)),start,"exclusive next boundary");
Equal(RecordPresentation.WeekStart(start.AddDays(7)),start.AddDays(7),"next week");
Equal(RecordPresentation.InWeek(start.AddTicks(-1),start),false,"excluded previous week");
Equal(RecordPresentation.InWeek(start,start),true,"inclusive start");
Equal(RecordPresentation.InWeek(start.AddDays(7).AddTicks(-1),start),true,"included before end");
Equal(RecordPresentation.InWeek(start.AddDays(7),start),false,"exclusive end");
Equal(RecordPresentation.WeekStart(new DateTime(2026,1,1)),new DateTime(2025,12,31,6,0,0),"year boundary");
Equal(RecordPresentation.WeekStart(new DateTime(2026,10,1)),new DateTime(2026,9,30,6,0,0),"month boundary");
Equal(RecordPresentation.KoreaNow(new DateTimeOffset(2026,10,6,21,0,0,TimeSpan.Zero)),start,"UTC to Korea boundary");
Equal(RecordPresentation.TryDate("2026.10.07 05:59",out var before),true,"local date");
Equal(RecordPresentation.InWeek(before,start),false,"persisted local before boundary");
Equal(RecordPresentation.TryDate("2026-10-06T21:00:00Z",out var utc),true,"ISO date");
Equal(utc,start,"ISO zone conversion");
Equal(RecordPresentation.TryDate("invalid",out _),false,"invalid date");
foreach(var (word,iga,eul,eun) in new[]{("후이수","가","를","는"),("힐레우스","가","를","는"),("카멘","이","을","은"),("1관문","이","을","은"),("하드","가","를","는"),("노말","이","을","은")})
{Equal(RecordPresentation.Particle(word,"이/가"),iga,word+" subject");Equal(RecordPresentation.Particle(word,"을/를"),eul,word+" object");Equal(RecordPresentation.Particle(word,"은/는"),eun,word+" topic");}
Equal(RecordPresentation.Sentence("후이수","카멘","하드","레이드 전체"),"후이수가 카멘 하드를 클리어했습니다.","gateless hard");
Equal(RecordPresentation.Sentence("카멘","에키드나","노말",""),"카멘이 에키드나 노말을 클리어했습니다.","gateless normal");
Equal(RecordPresentation.Sentence("후이수","에키드나","하드","2관문"),"후이수가 에키드나 하드 2관문을 클리어했습니다.","gate log");
Equal(RecordPresentation.Sentence("후이수","에키드나","",""),"후이수가 에키드나를 클리어했습니다.","dungeon only");
Console.WriteLine($"PASS: {passed} weekly boundary, Korean time, parsing, particle, and gateless log checks");

// Parsed messages must survive disposal of their input document.
EngineSnapshot parsedSnapshot;
using (var message = System.Text.Json.JsonDocument.Parse("""
{"status":"ready","busy":false,"catalogBusy":false,"profile":{"character":"캐릭터","message":"플레이 중","active":true,"characterClass":"바드","characterEmblem":"C:/cached/bard.svg"},
 "records":[{"character":"캐릭터","dungeon":"던전","mode":"하드","gate":"1관문","date":"2026.10.08 12:00","detail":{"gold":100},"characterClass":"바드","characterEmblem":"C:/cached/bard.svg","itemLevel":"1,774.16"}],
 "clients":[{"hwnd":123,"pid":42,"title":"game"}],"selected":123,"catalogStatus":"cached",
 "catalogLastUpdated":"2026-10-08T00:00:00Z","catalogRefreshAvailableAt":1000,"google":{"email":"example"}}
""")) parsedSnapshot = EngineSnapshot.Parse(message.RootElement);
Equal(parsedSnapshot.Profile.CharacterState,"playing","legacy active profile fallback");
Equal(parsedSnapshot.Profile.Dungeon,null,"missing dungeon is hidden");
Equal(parsedSnapshot.Records[0].Detail.GetProperty("gold").GetInt32(),100,"detail outlives JSON document");
Equal(parsedSnapshot.Clients[0].GetProperty("pid").GetInt32(),42,"clients outlive JSON document");
Equal(parsedSnapshot.Google!.Value.GetProperty("email").GetString(),"example","settings outlive JSON document");
Equal(parsedSnapshot.Drive.HasValue,false,"optional drive state");
Equal(parsedSnapshot.CatalogRefreshAvailableAt,DateTimeOffset.FromUnixTimeSeconds(1000),"catalog deadline");
Console.WriteLine($"PASS: {passed} presentation and engine protocol checks");

Equal(parsedSnapshot.Records[0].CharacterClass,"바드","record profession preserved");
Equal(parsedSnapshot.Records[0].CharacterEmblem,"C:/cached/bard.svg","local record emblem preserved");
Console.WriteLine($"PASS: {passed} presentation and character emblem protocol checks");

Equal(parsedSnapshot.Records[0].ItemLevel,"1,774.16","cached record item level preserved");
Equal(parsedSnapshot.Profile.CharacterClass,"바드","current profile class preserved");
Equal(parsedSnapshot.Profile.CharacterEmblem,"C:/cached/bard.svg","current portrait emblem preserved");
Console.WriteLine($"PASS: {passed} item level and portrait protocol checks");

Equal(RecordPresentation.ItemLevel("1,774.99"),"Lv.1774","item level truncated without grouping");
Equal(RecordPresentation.ItemLevel("1700.00"),"Lv.1700","integer item level");
Equal(RecordPresentation.ItemLevel(null),"","missing item level omitted");
Equal(RecordPresentation.ItemLevel("NaN"),"","invalid item level omitted");
Console.WriteLine($"PASS: {passed} record presentation checks");
