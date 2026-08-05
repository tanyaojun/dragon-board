using System.Text.Json;
using DragonBoardLauncher;
using Xunit;

namespace DragonBoardLauncher.Tests;

public class LogPolicyTests
{
    private static JsonElement Element(string json)
    {
        using var doc = JsonDocument.Parse(json);
        return doc.RootElement.Clone();
    }

    [Fact]
    public void MissingPolicy_ReturnsNull_AndServiceFallsBack()
    {
        // ParseLogPolicy 只解析显式 logPolicy 对象；无对象返回 null，
        // 由 ManagedService 构造函数按 logOnlyErrors 兜底。
        var item = Element("{\"key\":\"bridge\",\"logOnlyErrors\":true}");
        var policy = LauncherServices.ParseLogPolicy(item, logOnlyErrors: true);

        Assert.Null(policy);

        // ManagedService 兜底：logOnlyErrors=true → ErrorsOnly。
        var service = new ManagedService(
            "bridge", 8765, "dummy", "python", "main.py",
            logOnlyErrors: true);
        Assert.Equal(ServiceLogLevel.ErrorsOnly, service.LogPolicy.Level);
    }

    [Fact]
    public void MissingPolicy_DefaultsToAll_WhenNoLogOnlyErrors()
    {
        // 无 logPolicy 且 logOnlyErrors=false → ManagedService 兜底为 All。
        var item = Element("{\"key\":\"mongo\"}");
        var policy = LauncherServices.ParseLogPolicy(item, logOnlyErrors: false);

        Assert.Null(policy);

        var service = new ManagedService("mongo", 27017, "dummy", "mongod", "--dbpath x");
        Assert.Equal(ServiceLogLevel.All, service.LogPolicy.Level);
        Assert.False(service.LogPolicy.SuppressHealth);
    }

    [Fact]
    public void ErrorsOnlyPolicy_Parses()
    {
        var item = Element("{\"logPolicy\":{\"level\":\"errors-only\"}}");
        var policy = LauncherServices.ParseLogPolicy(item, logOnlyErrors: false);

        Assert.NotNull(policy);
        Assert.Equal(ServiceLogLevel.ErrorsOnly, policy!.Level);
    }

    [Fact]
    public void FilterAccessWithSuppressHealth_Parses()
    {
        var item = Element("{\"logPolicy\":{\"level\":\"filter-access\",\"suppressHealth\":true}}");
        var policy = LauncherServices.ParseLogPolicy(item, logOnlyErrors: false);

        Assert.NotNull(policy);
        Assert.Equal(ServiceLogLevel.FilterAccess, policy!.Level);
        Assert.True(policy.SuppressHealth);
    }

    [Fact]
    public void UnknownLevel_FallsBackToAll()
    {
        var item = Element("{\"logPolicy\":{\"level\":\"bogus\"}}");
        var policy = LauncherServices.ParseLogPolicy(item, logOnlyErrors: false);

        Assert.NotNull(policy);
        Assert.Equal(ServiceLogLevel.All, policy!.Level);
    }

    [Fact]
    public void ExplicitPolicy_OverridesLogOnlyErrors()
    {
        // logOnlyErrors=true 但显式 logPolicy 为 filter-access：应优先显式策略。
        var item = Element("{\"logOnlyErrors\":true,\"logPolicy\":{\"level\":\"filter-access\"}}");
        var policy = LauncherServices.ParseLogPolicy(item, logOnlyErrors: true);

        Assert.NotNull(policy);
        Assert.Equal(ServiceLogLevel.FilterAccess, policy!.Level);
        Assert.False(policy.ErrorsOnly);
    }
}
