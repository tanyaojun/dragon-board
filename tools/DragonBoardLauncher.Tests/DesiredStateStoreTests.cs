using DragonBoardLauncher.Core;
using Xunit;

namespace DragonBoardLauncher.Tests;

public class DesiredStateStoreTests : IDisposable
{
    private readonly string _dir;
    private readonly DesiredStateStore _store;

    public DesiredStateStoreTests()
    {
        _dir = Path.Combine(Path.GetTempPath(), "dbl-tests-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(_dir);
        _store = new DesiredStateStore(_dir);
    }

    public void Dispose()
    {
        try { Directory.Delete(_dir, recursive: true); }
        catch { /* 清理失败不影响测试结果 */ }
    }

    [Fact]
    public void NoFile_ReturnsEmpty()
    {
        var enabled = _store.LoadEnabled();
        Assert.Empty(enabled);
    }

    [Fact]
    public void SaveThenLoad_RoundTrips()
    {
        _store.SaveEnabled(new[] { "frontend", "voice" });

        var loaded = _store.LoadEnabled();
        Assert.Equal(2, loaded.Count);
        Assert.Contains("frontend", loaded);
        Assert.Contains("voice", loaded);
    }

    [Fact]
    public void SaveRemovedKey_DoesNotPersist()
    {
        _store.SaveEnabled(new[] { "frontend", "voice" });
        _store.SaveEnabled(new[] { "frontend" });

        var loaded = _store.LoadEnabled();
        Assert.Single(loaded);
        Assert.Contains("frontend", loaded);
        Assert.DoesNotContain("voice", loaded);
    }

    [Fact]
    public void EmptySave_ReturnsEmpty()
    {
        _store.SaveEnabled(Array.Empty<string>());
        Assert.Empty(_store.LoadEnabled());
    }

    [Fact]
    public void CorruptFile_ReturnsEmpty()
    {
        File.WriteAllText(_store.FilePath, "{ invalid json !!");
        Assert.Empty(_store.LoadEnabled());
    }
}
