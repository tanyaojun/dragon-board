using DragonBoardLauncher;
using DragonBoardLauncher.Core;
using Xunit;

namespace DragonBoardLauncher.Tests;

public class CollectorHealthGuardTests
{
    private static SnapshotCollectorHealth Unhealthy(string fingerprint, string message, bool restartable = true) =>
        SnapshotCollectorHealth.Unhealthy(fingerprint, message, restartable);

    [Fact]
    public void Healthy_ResetsAndNoRestart()
    {
        var guard = new CollectorHealthGuard();
        var decision = guard.Evaluate(SnapshotCollectorHealth.Healthy());

        Assert.False(decision.ShouldRestart);
        Assert.False(decision.CollectFailed);
        Assert.Null(decision.LogMessage);
    }

    [Fact]
    public void HardFailure_TwoPollsConfirmsRestart()
    {
        var guard = new CollectorHealthGuard();
        var health = Unhealthy("hard:scheduler-stopped", "调度器未运行");

        // 第一次轮询：进入 pending，不触发
        var first = guard.Evaluate(health);
        Assert.False(first.ShouldRestart);
        Assert.False(first.CollectFailed);

        // 第二次同 fingerprint：确认触发重启
        var second = guard.Evaluate(health);
        Assert.True(second.ShouldRestart);
        Assert.True(second.CollectFailed);
    }

    [Fact]
    public void NonRestartable_NeverRestarts()
    {
        var guard = new CollectorHealthGuard();
        var health = Unhealthy("wait:lock", "锁冲突等待", restartable: false);

        for (var i = 0; i < 3; i++)
        {
            var decision = guard.Evaluate(health);
            Assert.False(decision.ShouldRestart, $"第 {i + 1} 次轮询不应触发重启");
            Assert.True(decision.CollectFailed);
        }
    }

    [Fact]
    public void NullHealth_OfflineRestarts()
    {
        var guard = new CollectorHealthGuard();
        var decision = guard.Evaluate(null);

        Assert.True(decision.ShouldRestart);
        Assert.True(decision.CollectFailed);
    }

    [Fact]
    public void FailureThenRecovery_ResetsPending()
    {
        var guard = new CollectorHealthGuard();
        var health = Unhealthy("hard:a", "a");

        guard.Evaluate(health); // pending=1
        var recovered = guard.Evaluate(SnapshotCollectorHealth.Healthy());
        Assert.False(recovered.ShouldRestart);
        Assert.Null(recovered.LogMessage); // 首次未失败过，无恢复日志

        // 恢复后再故障，重新防抖
        var again1 = guard.Evaluate(health);
        Assert.False(again1.ShouldRestart);
        var again2 = guard.Evaluate(health);
        Assert.True(again2.ShouldRestart);
    }

    [Fact]
    public void FailureThenRecovery_EmitsRestoreLog()
    {
        var guard = new CollectorHealthGuard();
        var health = Unhealthy("hard:a", "a");

        guard.Evaluate(health);
        guard.Evaluate(health); // 确认失败（wasUnhealthy=true）

        var recovered = guard.Evaluate(SnapshotCollectorHealth.Healthy());
        Assert.NotNull(recovered.LogMessage);
        Assert.Contains("恢复正常", recovered.LogMessage);
    }
}
