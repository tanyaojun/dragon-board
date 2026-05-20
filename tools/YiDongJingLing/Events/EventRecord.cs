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
    LowOpenLongYang,
    HighOpenLongYin,
    BidPressure,
    AskPressure,
    SpreadWidened,
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
    string Reason)
{
    public string DedupeKey => $"{Code}:{Type}";
    public string DisplayName => string.IsNullOrWhiteSpace(Name) ? Code : Name;
}
