using DragonBoardLauncher.Core;
using Xunit;

namespace DragonBoardLauncher.Tests;

public class StartThrottleTests
{
    [Fact]
    public void FirstStart_Allowed()
    {
        var throttle = new StartThrottle(TimeSpan.FromSeconds(15));
        Assert.True(throttle.TryAcquire("collector"));
    }

    [Fact]
    public void RapidSecondStart_Blocked()
    {
        var throttle = new StartThrottle(TimeSpan.FromSeconds(15));
        Assert.True(throttle.TryAcquire("collector"));
        // 秒级连发（用户连点/多触发器叠加）被拒
        Assert.False(throttle.TryAcquire("collector"));
        Assert.False(throttle.TryAcquire("collector"));
    }

    [Fact]
    public void ProcessExit_ClearsThrottle()
    {
        var throttle = new StartThrottle(TimeSpan.FromSeconds(15));
        Assert.True(throttle.TryAcquire("collector"));
        // 等锁实例 RuntimeError 退出（Exited 事件）→ 节流解除，修复重拉放行
        throttle.Reset("collector");
        Assert.True(throttle.TryAcquire("collector"));
    }

    [Fact]
    public void ExplicitStop_ClearsThrottle()
    {
        var throttle = new StartThrottle(TimeSpan.FromSeconds(15));
        Assert.True(throttle.TryAcquire("collector"));
        throttle.Reset("collector");
        Assert.True(throttle.TryAcquire("collector"));
    }

    [Fact]
    public void DifferentServices_Independent()
    {
        var throttle = new StartThrottle(TimeSpan.FromSeconds(15));
        Assert.True(throttle.TryAcquire("collector"));
        Assert.True(throttle.TryAcquire("quant-api"));
    }

    [Fact]
    public void IntervalElapse_AllowsAgain()
    {
        var throttle = new StartThrottle(TimeSpan.FromMilliseconds(50));
        Assert.True(throttle.TryAcquire("collector"));
        Assert.False(throttle.TryAcquire("collector"));
        Thread.Sleep(60);
        Assert.True(throttle.TryAcquire("collector"));
    }
}
