namespace BeatricePC;
public partial class MainWindow
{
    private RecordsView recordsView = null!;
    private void ShowRecords() => recordsView.Render(records);
    private void AdaptRecordWeek()
    {
        if (currentPage == "records") recordsView.Adapt(Root.ActualWidth - RailColumn.Width.Value - 200 - 48);
    }
}
