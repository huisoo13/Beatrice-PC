using BeatricePC;
using System.Diagnostics;
var passed=0;
void Equal<T>(T actual,T expected,string name){if(!EqualityComparer<T>.Default.Equals(actual,expected))throw new Exception(name+": "+actual+" != "+expected);passed++;}
var relaunch = AppRelaunch.CreateStartInfo(@"C:\Program Files\Beatrice\BeatricePC.exe",
    new[]{"BeatricePC.exe",@"--app-root=C:\Program Files\Beatrice","--page=records","--capture","--demo"});
Equal(relaunch.FileName,@"C:\Program Files\Beatrice\BeatricePC.exe","relaunch executable with spaces");
Equal(relaunch.ArgumentList.Count,1,"relaunch drops demo/capture/previous page");
Equal(relaunch.ArgumentList[0],@"--app-root=C:\Program Files\Beatrice","relaunch preserves installation root as one argument");
Equal(relaunch.UseShellExecute,false,"relaunch does not use shell");
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

// Weekly receipts reuse completed records and cached character metadata without fetching APIs.
System.Text.Json.JsonElement Detail(string json) { using var doc=System.Text.Json.JsonDocument.Parse(json); return doc.RootElement.Clone(); }
var matched=Detail("""{"goldReward":true,"status":"matched","values":{"gold":10000,"fee":9000,"bound_percentage":0.2}}""");
var noMatch=Detail("""{"status":"unmatched"}""");
Raid Sample(string who,string dungeon,string mode,string gate,string date,System.Text.Json.JsonElement? detail=null,string? job="바드",string? level="1,774.99") => new(who,dungeon,mode,gate,date,detail??matched,job,null,level);
var receipt=WeeklySummary.Build(new[]{
    Sample("후이수","던전A","하드","1관문","2026.10.07 06:00"),
    Sample("후이수","던전A","하드","2관문","2026.10.08 12:00"),
    Sample("후이수","던전A","노말","3관문","2026.10.08 13:00"),
    Sample("다른캐릭터","던전B","하드","레이드 전체","2026.10.08 14:00",noMatch,null,null),
    Sample("이전주","던전C","하드","1관문","2026.10.07 05:59"),
    Sample("다음주","던전C","하드","1관문","2026.10.14 06:00"),
    Sample("날짜오류","던전C","하드","1관문","invalid")},new DateTime(2026,10,10));
Equal(receipt.Characters.Count,2,"receipt Wednesday boundaries and invalid dates");
Equal(receipt.Money.Gold,24000m,"receipt unbound gold ignores extra reward fee");
Equal(receipt.Money.BoundGold,6000m,"receipt bound gold");
Equal(receipt.Money.Missing,1,"receipt missing linked reward count");
var bard=receipt.Characters.Single(c => c.Name=="후이수");
var sortedReceipt=WeeklySummary.Build(new[]{
    Sample("미확인","A","하드","1관문","2026.10.08 15:00",level:"invalid"),
    Sample("낮음","A","하드","1관문","2026.10.08 14:00",level:"999.99"),
    Sample("높음","A","하드","1관문","2026.10.08 13:00",level:"1,774.99"),
    Sample("소수차이","A","하드","1관문","2026.10.08 12:00",level:"1774.01"),
    Sample("동일레벨","A","하드","1관문","2026.10.08 11:00",level:"1774.01"),
    Sample("누락","A","하드","1관문","2026.10.08 10:00",level:null)},start);
Equal(string.Join(",",sortedReceipt.Characters.Select(c => c.Name)),"높음,소수차이,동일레벨,낮음,미확인,누락","numeric level descending, stable ties and unknown levels last");
Equal(sortedReceipt.Money.Gold,48000m,"sorting preserves reward totals");
var growing=WeeklySummary.Build(new[]{
    Sample("후이수","A","하드","1관문","2026.10.08 10:00",level:"1,780.16"),
    Sample("후이수","B","하드","1관문","2026.10.08 11:00",level:"1,774.99"),
    Sample("후이수","C","하드","1관문","2026.10.08 12:00",level:null),
    Sample("후이수","D","하드","1관문","2026.10.15 12:00",level:"1,900.00")},start);
Equal(growing.Characters.Count,1,"different record levels group as one character");
Equal(growing.Characters[0].Level,"Lv.1780","highest selected-week record level wins over latest");
Equal(growing.Money.Gold,24000m,"level consolidation preserves all weekly rewards");
Equal(bard.Dungeons.Count,2,"same dungeon modes stay separate");
Equal(bard.Dungeons.Single(d => d.Mode=="하드").Gates,"1–2관문","contiguous gates grouped");
Equal(bard.Level,"Lv.1774","receipt level uses cached truncated item level");
Equal(bard.Job,"바드","receipt cached profession");
Equal(receipt.Characters.Single(c => c.Name=="다른캐릭터").Dungeons[0].Gates,"","receipt gateless label omitted");
Equal(WeeklySummary.GateLabel(new[]{"3관문","1관문","1관문"}),"1·3관문","missing middle gate not invented");
Equal(WeeklySummary.GateLabel(new[]{"1관문","2관문","4관문","5관문"}),"1–2·4–5관문","multiple contiguous ranges");
Equal(WeeklySummary.GateLabel(new[]{"레이드 전체",""}),"","gateless only");
Equal(WeeklySummary.ReadMoney(Detail("""{"goldReward":true,"status":"matched","values":{"gold":101,"fee":0,"bound_percentage":0.5}}""")).Gold,51m,"integer splitting conserves reward");
Equal(WeeklySummary.ReadMoney(Detail("""{"goldReward":true,"status":"matched","values":{"gold":100,"fee":0,"bound_percentage":1}}""")).Gold,0m,"fully bound reward");
Equal(WeeklySummary.ReadMoney(Detail("""{"goldReward":true,"status":"matched","values":{"gold":100,"fee":0,"bound_percentage":0}}""")).BoundGold,0m,"fully unbound reward");
Equal(WeeklySummary.ReadMoney(Detail("""{"goldReward":true,"status":"matched","values":{"gold":100,"bound_percentage":2}}""")).Missing,1,"invalid ratio unknown");
Equal(WeeklySummary.ReadMoney(Detail("""{"status":123}""")).Missing,1,"invalid status safely unknown");
Equal(WeeklySummary.ReadMoney(Detail("""{"goldReward":true,"status":"matched","values":{"gold":-1,"bound_percentage":0}}""")).Missing,1,"negative reward unknown");
Equal(WeeklySummary.ReadMoney(default).Missing,1,"missing detail safely unknown");
var mixed=WeeklySummary.Build(new[]{Sample("혼합","A","하드","1관문","2026.10.08 12:00"),Sample("혼합","A","하드","2관문","2026.10.08 13:00",noMatch)},start);
Equal(mixed.Characters[0].Dungeons[0].Money.Missing,1,"mixed known unknown dungeon marked incomplete");
Equal(mixed.Money.Gold,8000m,"mixed totals retain only known reward");
Equal(WeeklySummary.Build(Array.Empty<Raid>(),start).Money.Gold,0m,"empty receipt totals zero");
Equal(WeeklySummary.Amount(1234567),"1,234,567","currency grouping independent of locale");
Console.WriteLine($"PASS: {passed} presentation, engine protocol and weekly receipt checks");
EngineSnapshot currencySnapshot;
using(var doc=System.Text.Json.JsonDocument.Parse("""
{"status":"ready","busy":false,"catalogBusy":false,"profile":{"character":"이름","message":"플레이 중","active":true},"records":[],"clients":[],"selected":0,"catalogStatus":"cached","currencyImages":{"gold":"C:/cache/gold.png","boundGold":"C:/cache/bound.png"}}
""")) currencySnapshot=EngineSnapshot.Parse(doc.RootElement);
Equal(currencySnapshot.CurrencyImages!.Value.GetProperty("gold").GetString(),"C:/cache/gold.png","currency path survives JSON disposal");
Equal(currencySnapshot.CurrencyImages!.Value.GetProperty("boundGold").GetString(),"C:/cache/bound.png","bound currency path preserved");
Equal(parsedSnapshot.CurrencyImages.HasValue,false,"older engines need no currency image field");
Equal(parsedSnapshot.Obs.HasValue,false,"older engine snapshots need no OBS diagnostic field");
EngineSnapshot obsSnapshot;
using(var doc=System.Text.Json.JsonDocument.Parse("""
{"status":"ready","busy":false,"catalogBusy":false,"profile":{"character":"이름","message":"플레이 중","active":true},"records":[],"clients":[],"selected":0,"catalogStatus":"cached","obs":{"status":"캡처 오류","error":"OBS 접근 거부"}}
""")) obsSnapshot=EngineSnapshot.Parse(doc.RootElement);
Equal(obsSnapshot.Obs!.Value.GetProperty("error").GetString(),"OBS 접근 거부","OBS diagnostics survive snapshot JSON disposal");
Console.WriteLine($"PASS: {passed} presentation, protocol, receipt and currency image checks");
Equal(WeeklySummary.ReadMoney(Detail("""{"goldReward":false,"status":"unmatched"}""")).Missing,0,"confirmed no gold needs no catalog");
Equal(WeeklySummary.ReadMoney(Detail("""{"goldReward":false,"status":"matched","values":{"gold":9999,"bound_percentage":0}}""")).Gold,0m,"confirmed no gold ignores catalog gold");
Equal(WeeklySummary.ReadMoney(Detail("""{"status":"matched","values":{"gold":9999,"bound_percentage":0}}""")).Gold,9999m,"historical unknown shows catalog gold");
Equal(WeeklySummary.ReadMoney(Detail("""{"goldReward":null,"status":"matched","values":{"gold":9999,"bound_percentage":0}}""")).Gold,9999m,"null receipt shows catalog gold");
Console.WriteLine($"PASS: {passed} gold receipt checks");

Equal(RecordPresentation.GoldReceipt(Detail("""{"goldReward":true}""")),"획득","receipt detail received");
Equal(RecordPresentation.GoldReceipt(Detail("""{"goldReward":false}""")),"미획득","receipt detail absent");
Equal(RecordPresentation.GoldReceipt(Detail("""{"goldReward":null}""")),"미확인","receipt detail unknown");
Equal(RecordPresentation.GoldReceipt(default),"미확인","receipt old detail unknown");
Console.WriteLine($"PASS: {passed} gold receipt presentation checks");

if (OperatingSystem.IsWindows())
{
    var root = Path.GetFullPath(Path.Combine(AppContext.BaseDirectory, "../../../../../"));
    var python = Path.Combine(root, ".venv-win", "Scripts", "python.exe");
    using var job = new EngineProcessLifetime();
    var startInfo = new ProcessStartInfo(python) { WorkingDirectory = root, UseShellExecute = false,
        RedirectStandardOutput = true, RedirectStandardError = true, CreateNoWindow = true };
    startInfo.Environment["BEATRICE_ENGINE_JOB"] = job.Name;
    startInfo.ArgumentList.Add("-u"); startInfo.ArgumentList.Add("-c");
    startInfo.ArgumentList.Add("from beatrice.process_lifetime import join_owner_job; join_owner_job(); import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); print(p.pid,flush=True); time.sleep(60)");
    using var parent = Process.Start(startInfo)!;
    // Deliberately let venv spawn Python before attaching its redirector.
    var lineTask = parent.StandardOutput.ReadLineAsync();
    if (!lineTask.Wait(TimeSpan.FromSeconds(10))) throw new Exception("Lifetime child startup timed out");
    var pid = int.Parse(lineTask.Result ?? throw new Exception(parent.StandardError.ReadToEnd()));
    using var descendant = Process.GetProcessById(pid);
    job.Attach(parent);
    job.Dispose();
    Equal(parent.WaitForExit(5000), true, "job closes redirector");
    Equal(descendant.WaitForExit(5000), true, "job closes Python descendant");
    Console.WriteLine($"PASS: {passed} including real process lifetime checks");
}
