public sealed class EnvFileLoaderTests
{
    [Fact]
    public void LoadReadsPowerShellAndPlainEnvLines()
    {
        var path = Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}.env.local");
        File.WriteAllLines(path, [
            "# local voice config",
            "$env:VOICE_ENGINE='volcengine'",
            "VOLC_TTS_CLUSTER=volcano_tts",
            "VOLC_TTS_ACCESS_TOKEN=\"token-value\"",
            "not a valid line",
        ]);

        try
        {
            var values = EnvFileLoader.Load(path);

            Assert.Equal("volcengine", values["VOICE_ENGINE"]);
            Assert.Equal("volcano_tts", values["VOLC_TTS_CLUSTER"]);
            Assert.Equal("token-value", values["VOLC_TTS_ACCESS_TOKEN"]);
            Assert.False(values.ContainsKey("not"));
        }
        finally
        {
            File.Delete(path);
        }
    }

    [Fact]
    public void LoadReturnsEmptyDictionaryWhenFileDoesNotExist()
    {
        var values = EnvFileLoader.Load(Path.Combine(Path.GetTempPath(), $"{Guid.NewGuid():N}.env.local"));

        Assert.Empty(values);
    }
}
