using YiDongJingLing.Settings;
using Xunit;

namespace YiDongJingLing.Tests;

public sealed class AppSettingsTests
{
    [Fact]
    public void Default_voice_mode_should_be_all()
    {
        Assert.Equal(VoiceMode.All, new AppSettings().VoiceMode);
    }

    [Fact]
    public void Default_cooldowns_should_be_short_for_state_change_and_long_for_noise()
    {
        var settings = new AppSettings();

        Assert.Equal(30, settings.StateChangeCooldownSeconds);
        Assert.Equal(180, settings.NoiseCooldownSeconds);
    }

    [Fact]
    public void Clone_should_copy_cooldown_settings()
    {
        var settings = new AppSettings
        {
            StateChangeCooldownSeconds = 45,
            NoiseCooldownSeconds = 240,
        };

        var clone = settings.Clone();

        Assert.Equal(45, clone.StateChangeCooldownSeconds);
        Assert.Equal(240, clone.NoiseCooldownSeconds);
    }
}
