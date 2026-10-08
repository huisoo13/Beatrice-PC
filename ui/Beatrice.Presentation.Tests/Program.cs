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
