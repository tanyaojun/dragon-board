namespace YiDongJingLing.MarketData;

public static class TradingSession
{
    public static bool IsContinuousAuction(DateTimeOffset timestamp)
    {
        var local = timestamp.ToLocalTime();
        if (local.DayOfWeek is DayOfWeek.Saturday or DayOfWeek.Sunday) return false;

        var time = local.TimeOfDay;
        return IsBetween(time, new TimeSpan(9, 30, 0), new TimeSpan(11, 30, 0)) ||
               IsBetween(time, new TimeSpan(13, 0, 0), new TimeSpan(15, 0, 0));
    }

    private static bool IsBetween(TimeSpan value, TimeSpan start, TimeSpan end)
    {
        return value >= start && value <= end;
    }
}
