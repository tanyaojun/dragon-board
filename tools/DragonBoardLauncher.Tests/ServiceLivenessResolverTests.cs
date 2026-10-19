using DragonBoardLauncher.Core;
using Xunit;

namespace DragonBoardLauncher.Tests;

public class ServiceLivenessResolverTests
{
    // 2026-10-19 复盘回归（用户反馈 3000/8000/8008/32145 盘中"掉线又自动恢复"）：
    // 端口探测是启发式（TCP 表损坏 + 短超时连接），活着的服务会被假阴性；
    // 真伤害是假阴性让"启动"变可点 → 重复启动 → [Errno 10048] 自杀
    // （10-14 13:37:26 量化后端 API 实证）。

    [Fact]
    public void ProbeSaysRunning_IsRunningWithoutDeepProbe()
    {
        var deepProbeCalls = 0;

        Assert.True(ServiceLivenessResolver.IsRunning(true, false, () =>
        {
            deepProbeCalls++;
            return false;
        }));
        Assert.Equal(0, deepProbeCalls);
    }

    [Fact]
    public void ProbeSaysDown_NoStrongEvidence_IsDownWithoutDeepProbe()
    {
        // 从未观察到在跑、也没有存活的跟踪进程：冷启动场景，不做深探测（不加延迟）。
        var deepProbeCalls = 0;

        Assert.False(ServiceLivenessResolver.IsRunning(false, false, () =>
        {
            deepProbeCalls++;
            return true;
        }));
        Assert.Equal(0, deepProbeCalls);
    }

    [Fact]
    public void ProbeSaysDown_StrongEvidence_DeepProbeSucceeds_IsRunning()
    {
        // 关键回归：服务在跑（跟踪进程存活/本会话见过）而端口探测失败时，
        // 深探测找到活的监听 → 判定运行中（不再误停、不再重复启动 10048）。
        Assert.True(ServiceLivenessResolver.IsRunning(false, true, () => true));
    }

    [Fact]
    public void ProbeSaysDown_StrongEvidence_DeepProbeFails_IsDown()
    {
        // 深探测也失败 → 认死，交给启动/清理路径。
        Assert.False(ServiceLivenessResolver.IsRunning(false, true, () => false));
    }
}