using System.Net;
using System.Text;
using System.Text.Json;
using YiDongJingLing.Events;
using YiDongJingLing.Speech;
using Xunit;

namespace YiDongJingLing.Tests;

public sealed class SpeechAnnouncerTests
{
    private static EventRecord Record(
        L1EventType type,
        string typeName,
        string code,
        decimal changePct,
        DateTimeOffset timestamp)
    {
        return new EventRecord(
            type, typeName, code, "测试" + code, 10m, changePct, 0m, 0m,
            timestamp, L1EventSeverity.Important, "reason");
    }

    [Fact]
    public async Task Announce_should_post_one_speak_request_per_event_in_time_order()
    {
        var handler = new RecordingHandler();
        using var announcer = new SpeechAnnouncer(Path.GetTempPath(), log: null, handler);
        var at = DateTimeOffset.Parse("2026-10-13T09:35:00+08:00");
        var events = new List<EventRecord>
        {
            Record(L1EventType.NearLimitUp, "逼近涨停", "600002", 8.9m, at.AddSeconds(6)),
            Record(L1EventType.FastRise, "快速拉升", "600001", 3.2m, at),
        };

        await announcer.AnnounceAsync(events);

        var speaks = handler.Requests.Where(item => item.Path == "/speak").ToList();
        Assert.Equal(2, speaks.Count);
        var texts = speaks
            .Select(item => JsonDocument.Parse(item.Body ?? "{}").RootElement.TryGetProperty("text", out var text)
                ? text.GetString()
                : null)
            .ToList();
        Assert.Equal("测试600001，快速拉升，涨幅3.2%", texts[0]);
        Assert.Equal("测试600002，逼近涨停", texts[1]);
    }

    [Fact]
    public async Task Announce_should_post_nothing_when_event_list_empty()
    {
        var handler = new RecordingHandler();
        using var announcer = new SpeechAnnouncer(Path.GetTempPath(), log: null, handler);

        await announcer.AnnounceAsync([]);

        Assert.DoesNotContain(handler.Requests, item => item.Path == "/speak");
    }

    private sealed record LoggedRequest(string Path, string? Body);

    private sealed class RecordingHandler : HttpMessageHandler
    {
        public List<LoggedRequest> Requests { get; } = new();

        protected override Task<HttpResponseMessage> SendAsync(
            HttpRequestMessage request,
            CancellationToken cancellationToken)
        {
            var path = request.RequestUri?.AbsolutePath ?? "";
            string? body = null;
            if (request.Content is not null)
            {
                body = request.Content.ReadAsStringAsync(cancellationToken).GetAwaiter().GetResult();
            }

            Requests.Add(new LoggedRequest(path, body));

            var payload = path == "/health"
                ? """{"ok":true,"service":"VoiceWorker"}"""
                : """{"ok":true,"queued":true,"queueLength":0}""";
            var response = new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(payload, Encoding.UTF8, "application/json"),
            };
            return Task.FromResult(response);
        }
    }
}
