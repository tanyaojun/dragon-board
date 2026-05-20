namespace YiDongJingLing.Events;

public sealed class L1EventRules
{
    public decimal NearLimitDistancePct { get; set; } = 1.0m;
    public decimal[] RiseTiers { get; set; } = [3m, 5m, 7m, 9m];
    public decimal[] DropTiers { get; set; } = [3m, 5m, 7m, 9m];
    public decimal[] AmountTiers { get; set; } = [100_000_000m, 300_000_000m, 500_000_000m, 1_000_000_000m];
    public decimal FastRise30SecPct { get; set; } = 2m;
    public decimal FastRise60SecPct { get; set; } = 3m;
    public decimal FastRise300SecPct { get; set; } = 5m;
    public decimal FastDrop30SecPct { get; set; } = -2m;
    public decimal FastDrop60SecPct { get; set; } = -3m;
    public decimal FastDrop300SecPct { get; set; } = -5m;
    public decimal PressureRatio { get; set; } = 2.5m;
    public decimal SpreadPct { get; set; } = 1.0m;
    public decimal LargeOrderAmount { get; set; } = 10_000_000m;
    public decimal OpenGapPct { get; set; } = 1m;
    public decimal LongBodyPct { get; set; } = 4m;
    public decimal SealWeakRatio { get; set; } = 0.5m;
    public decimal SealIncreaseRatio { get; set; } = 1.5m;
    public decimal UpcomingOpenSealWeakRatio { get; set; } = 0.35m;
    public decimal UpcomingOpenMinSealAmount { get; set; } = 5_000_000m;
    public decimal UpcomingOpenMinSealVolume { get; set; } = 10_000m;
    public TimeSpan UpcomingOpenWindow { get; set; } = TimeSpan.FromSeconds(10);
    public decimal VolumeAccelerationRatio { get; set; } = 2.0m;
}
