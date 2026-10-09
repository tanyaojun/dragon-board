using DragonBoardLauncher.Core;
using Xunit;

namespace DragonBoardLauncher.Tests;

public class RestartPolicyTests
{
    [Fact]
    public void FirstRequest_Allowed()
    {
        var policy = new RestartPolicy(cooldown: TimeSpan.FromSeconds(60));
        Assert.True(policy.TryRequestRestart("collector", out var reason));
        Assert.Null(reason);
    }

    [Fact]
    public void Cooldown_BlocksSecondRequest()
    {
        var policy = new RestartPolicy(cooldown: TimeSpan.FromSeconds(60));
        Assert.True(policy.TryRequestRestart("collector", out _));
        policy.RecordRestart("collector");

        Assert.False(policy.TryRequestRestart("collector", out var reason));
        Assert.Contains("冷却", reason);
    }

    [Fact]
    public void ShortCooldown_AllowsAfterWait()
    {
        var policy = new RestartPolicy(cooldown: TimeSpan.FromMilliseconds(50));
        Assert.True(policy.TryRequestRestart("collector", out _));
        policy.RecordRestart("collector");
        Assert.False(policy.TryRequestRestart("collector", out _));

        // 冷却 50ms + 第 1 次失败退避 1s（2^(1-1)）= 1.05s 后才允许
        Thread.Sleep(1100);
        Assert.True(policy.TryRequestRestart("collector", out _));
    }

    [Fact]
    public void MaxConsecutive_PausesRestart()
    {
        var policy = new RestartPolicy(
            cooldown: TimeSpan.FromMilliseconds(1),
            maxConsecutive: 3,
            maxBackoff: TimeSpan.FromMilliseconds(1));

        // 连续 3 次重启达到上限：每次间隔 5ms 跳过冷却+退避（1ms+1ms）。
        for (var i = 0; i < 3; i++)
        {
            Thread.Sleep(5);
            Assert.True(policy.TryRequestRestart("collector", out _));
            policy.RecordRestart("collector");
        }

        // 第 4 次：即使冷却已过，也被"连续失败上限"拦截
        Thread.Sleep(5);
        Assert.False(policy.TryRequestRestart("collector", out var reason));
        Assert.Contains("暂停", reason);
    }

    [Fact]
    public void Reset_ClearsFailureCountAndBackoff()
    {
        var policy = new RestartPolicy(
            cooldown: TimeSpan.FromMilliseconds(1),
            maxConsecutive: 3);

        for (var i = 0; i < 3; i++)
        {
            policy.RecordRestart("collector");
        }
        Assert.False(policy.TryRequestRestart("collector", out _));

        policy.Reset("collector");
        // 失败计数与指数退避清零；冷却仍保留（见下一个测试），等待 1s 退避下限后放行。
        Thread.Sleep(1100);
        Assert.True(policy.TryRequestRestart("collector", out _));
    }

    [Fact]
    public void Reset_KeepsCooldownToThrottleFlapping()
    {
        // 2026-10-09 评审 P2：可达即全清会让抖动型服务每 ~61s 无限重拉。
        // 恢复只清失败计数；冷却时间戳保留，快速抖动仍被限流。
        var policy = new RestartPolicy(cooldown: TimeSpan.FromMilliseconds(500));
        policy.RecordRestart("collector");
        policy.Reset("collector");

        Assert.False(policy.TryRequestRestart("collector", out _));
    }

    [Fact]
    public void Backoff_GrowsWithFailures()
    {
        var policy = new RestartPolicy(cooldown: TimeSpan.FromMilliseconds(1));
        policy.RecordRestart("collector");
        policy.RecordRestart("collector");

        var detail = policy.DescribeBlock("collector");
        Assert.Contains("退避", detail);
        Assert.Contains("2 次", detail);
    }

    [Fact]
    public void DescribeBlock_EmptyWhenNoRestart()
    {
        var policy = new RestartPolicy();
        Assert.Equal("", policy.DescribeBlock("collector"));
    }
}
