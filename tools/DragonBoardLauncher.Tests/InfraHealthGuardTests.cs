using DragonBoardLauncher.Core;
using Xunit;

namespace DragonBoardLauncher.Tests;

public class TradingWindowTests
{
    // 窗口边界：09:15:00 起、15:10:00 止（含端点）。
    // 背景见 TradingWindow.cs：交易时段内禁止停启式重启（09-15 10:00 误杀教训）。
    [Theory]
    [InlineData("09:14:59", false)]
    [InlineData("09:15:00", true)]
    [InlineData("10:00:00", true)]
    [InlineData("11:30:00", true)] // 午休也在窗内（保守：整窗不执行停启式修复）
    [InlineData("15:10:00", true)]
    [InlineData("15:10:01", false)]
    [InlineData("03:00:00", false)]
    public void IsInside_MatchesTradingWindowBoundaries(string timeText, bool expected)
    {
        var time = TimeSpan.Parse(timeText);
        Assert.Equal(expected, TradingWindow.IsInside(time));
    }
}

public class SnapshotCollectorProbeEvidenceTests
{
    // 健康证据可靠性判定（P0-B 细化 + P1-C）：只有 probe:*（探针连不上 8001，
    // 没读到服务自报状态）算不可靠；服务自报契约（healthy/http:/hard:/
    // startup-failure:/no-restart:）都是可靠证据。
    [Theory]
    [InlineData("probe:TimeoutException:The request was canceled", true)]
    [InlineData("probe:HttpRequestException: 无法连接", true)]
    [InlineData("http:503", false)]
    [InlineData("hard:调度器未运行", false)]
    [InlineData("startup-failure:wait", false)]
    [InlineData("no-restart:alert:数据源失败", false)]
    [InlineData("missing-status", false)]
    [InlineData("healthy", false)]
    [InlineData("", false)]
    public void IsUnreliableHealthEvidence_OnlyProbePrefixIsUnreliable(
        string fingerprint,
        bool expected)
    {
        Assert.Equal(
            expected,
            SnapshotCollectorProbe.IsUnreliableHealthEvidence(fingerprint));
    }

    [Theory]
    [InlineData("startup-failure:wait", true)]
    [InlineData("startup-failure:restart", true)]
    [InlineData("probe:TimeoutException:x", false)]
    [InlineData("hard:调度器未运行", false)]
    [InlineData("missing-status", false)]
    [InlineData("", false)]
    public void IsLockWaitStartupFailureMarker_OnlyStartupFailurePrefix(
        string fingerprint,
        bool expected)
    {
        Assert.Equal(
            expected,
            SnapshotCollectorProbe.IsLockWaitStartupFailureMarker(fingerprint));
    }
}

public class InfraHealthGuardTests
{
    // xUnit 每个测试新建类实例：实例字段 = 每测试独立 Guard，互不污染
    private readonly InfraHealthGuard _guard = new();

    [Fact]
    public void Offline_AnnouncesOnce_ThenSilent_UntilRestored()
    {
        // 首次离线：应拉起 + 公告一次（3 秒轮询不刷屏）
        var first = _guard.Evaluate("mongo", "MongoDB 数据库", reachable: false);
        Assert.True(first.ShouldRestart);
        Assert.NotNull(first.LogMessage);

        // 持续离线：仍应拉起，但不重复公告
        var second = _guard.Evaluate("mongo", "MongoDB 数据库", reachable: false);
        Assert.True(second.ShouldRestart);
        Assert.Null(second.LogMessage);
    }

    [Fact]
    public void Restore_AnnouncesOnce_ThenNextOfflineAnnouncesAgain()
    {
        _guard.Evaluate("redis", "Redis 缓存", reachable: false); // 离线（公告）
        _guard.Evaluate("redis", "Redis 缓存", reachable: false); // 持续离线（静默）

        var restored = _guard.Evaluate("redis", "Redis 缓存", reachable: true);
        Assert.False(restored.ShouldRestart);
        Assert.NotNull(restored.LogMessage); // 恢复公告一次

        var restoredAgain = _guard.Evaluate("redis", "Redis 缓存", reachable: true);
        Assert.Null(restoredAgain.LogMessage); // 持续在线不再公告

        var offlineAgain = _guard.Evaluate("redis", "Redis 缓存", reachable: false);
        Assert.True(offlineAgain.ShouldRestart);
        Assert.NotNull(offlineAgain.LogMessage); // 再次离线重新公告
    }

    [Fact]
    public void Keys_TrackIndependently()
    {
        var mongoOffline = _guard.Evaluate("mongo", "MongoDB 数据库", reachable: false);
        Assert.NotNull(mongoOffline.LogMessage); // mongo 首次离线

        var redisOffline = _guard.Evaluate("redis", "Redis 缓存", reachable: false);
        Assert.NotNull(redisOffline.LogMessage); // redis 各自独立公告

        var mongoOfflineAgain = _guard.Evaluate("mongo", "MongoDB 数据库", reachable: false);
        Assert.Null(mongoOfflineAgain.LogMessage); // mongo 已公告过，静默
    }
}
