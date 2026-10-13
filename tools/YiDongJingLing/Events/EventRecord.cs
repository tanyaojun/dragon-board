namespace YiDongJingLing.Events;

public enum L1EventType
{
    LimitUpSealed,
    LimitUpOpened,
    UpcomingLimitUpOpen,
    NearLimitUp,
    LimitDownSealed,
    LimitDownOpened,
    UpcomingLimitDownOpen,
    NearLimitDown,
    SealOrderIncreased,
    SealOrderWeakened,
    BigRiseTier,
    BigDropTier,
    FastRise,
    FastDrop,
    TurnRed,
    TurnGreen,
    IntradayHigh,
    IntradayLow,
    AmountTier,
    VolumeAcceleration,
    LargeBidOrder,
    LargeAskOrder,
    OpeningWeakToStrong,
    LowOpenLongYang,
    HighOpenLongYin,
    BidPressure,
    AskPressure,
    SpreadWidened,
    NewStockOpened,
    NewStockReseal,
    LimitUpResealed,
    SectorRush,
    SectorDive,
    SectorLimitUpWave,
    SectorLimitUpOpenWave,
}

public enum L1EventSeverity
{
    Normal,
    Important,
    Critical,
}

public sealed record EventRecord(
    L1EventType Type,
    string TypeName,
    string Code,
    string Name,
    decimal Price,
    decimal ChangePct,
    decimal Volume,
    decimal Amount,
    DateTimeOffset Timestamp,
    L1EventSeverity Severity,
    string Reason,
    OpeningWeakToStrongSignal? OpeningSignal = null,
    string Sector = "",
    string MemberCodes = "")
{
    public string DedupeKey => Sector.Length > 0 ? $"S:{Sector}:{Type}" : $"{Code}:{Type}";
    public string DisplayName => string.IsNullOrWhiteSpace(Name) ? Code : Name;
    public bool IsSectorEvent => Sector.Length > 0;
}
