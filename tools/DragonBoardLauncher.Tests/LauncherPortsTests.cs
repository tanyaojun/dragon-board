using DragonBoardLauncher;
using Xunit;

namespace DragonBoardLauncher.Tests;

public class LauncherPortsTests
{
    // IsEndpointForPort 是 private；通过 GetPidsByPort 间接测端口匹配代价高。
    // 用反射访问 private 方法做精确断言，防 :16379 误命中 6379 类回归。
    private static bool Match(string endpoint, int port)
    {
        var method = typeof(LauncherPorts).GetMethod(
            "IsEndpointForPort",
            System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Static,
            binder: null,
            types: new[] { typeof(string), typeof(int) },
            modifiers: null);
        Assert.NotNull(method);
        return (bool)method!.Invoke(null, new object[] { endpoint, port })!;
    }

    [Theory]
    [InlineData("127.0.0.1:8001", 8001, true)]
    [InlineData("0.0.0.0:6379", 6379, true)]
    [InlineData("127.0.0.1:16379", 6379, false)] // 端口后缀误匹配防护
    [InlineData("127.0.0.1:18001", 8001, false)]
    [InlineData("127.0.0.1:63790", 6379, false)]
    [InlineData("[::1]:8001", 8001, true)]
    [InlineData("[::]:8001", 8001, true)]
    [InlineData("[::1]:18001", 8001, false)]
    public void EndpointPort_MatchOnlyExactPort(string endpoint, int port, bool expected)
    {
        Assert.Equal(expected, Match(endpoint, port));
    }
}
