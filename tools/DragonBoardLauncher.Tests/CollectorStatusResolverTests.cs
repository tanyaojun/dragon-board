using DragonBoardLauncher.Core;
using Xunit;

namespace DragonBoardLauncher.Tests;

public class CollectorStatusResolverTests
{
    // 2026-10-19 复盘回归：端口探测假阴性不得把活着的 8001 判成离线
    // （旧实现据此 EnsureHealthy 停启式重启健康实例，留下残留锁 + 等锁实例自杀）。

    [Fact]
    public void PortProbeSaysRunning_IsRunning()
    {
        var unreachable = SnapshotCollectorHealth.Unhealthy(
            "probe:HttpRequestException:refused",
            "无法读取采集服务(8001)健康状态",
            HttpReached: false);

        Assert.True(CollectorStatusResolver.IsRunning(true, unreachable));
    }

    [Theory]
    [InlineData(true)]  // status=ok
    [InlineData(false)] // status=degraded/error 但服务自报成功（端口确实在听）
    public void HttpReached_OverridesPortProbeFalse(bool healthy)
    {
        var selfReported = healthy
            ? SnapshotCollectorHealth.Healthy()
            : SnapshotCollectorHealth.Unhealthy(
                "no-restart:alert:最近异常",
                "快照采集提示: 最近异常",
                Restartable: false);

        Assert.True(CollectorStatusResolver.IsRunning(false, selfReported));
    }

    [Theory]
    [InlineData("probe:TimeoutException:10s 超时")]
    [InlineData("startup-failure:wait")]
    public void Unreachable_AndPortProbeFalse_IsOffline(string fingerprint)
    {
        var offline = SnapshotCollectorHealth.Unhealthy(
            fingerprint,
            "采集服务(8001)不可达",
            HttpReached: false);

        Assert.False(CollectorStatusResolver.IsRunning(false, offline));
    }

    [Fact]
    public void Unreachable_ButPortProbeTrue_StaysRunning()
    {
        // 端口在听但探针拿不到自报（预热尖峰/主循环阻塞）：仍算运行中，
        // 由 guard 的 probe:* 不可靠证据规则决定是否推迟停启式重启。
        var unreachable = SnapshotCollectorHealth.Unhealthy(
            "probe:TimeoutException:10s 超时",
            "采集服务(8001)不可达",
            HttpReached: false);

        Assert.True(CollectorStatusResolver.IsRunning(true, unreachable));
    }
}
