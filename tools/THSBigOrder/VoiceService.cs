using System;
using System.Collections.Generic;
using System.Linq;
using System.Speech.Synthesis;

namespace THSBigOrder
{
    internal enum BigOrderAnnouncementType { Ignite, Smash, BuyActive, GoodSupport }

    internal sealed class BigOrderAnnouncement
    {
        public BigOrderAnnouncementType Type { get; set; }
        public double Amount { get; set; }
    }

    internal interface IBigOrderVoice : IDisposable
    {
        bool Enabled { get; set; }
        void AnnounceBatch(IReadOnlyList<BigOrderAnnouncement> announcements);
        void CancelPending();
    }

    internal interface ISpeechQueue : IDisposable
    {
        void SpeakAsync(string text);
        void CancelAll();
    }

    internal sealed class SystemSpeechQueue : ISpeechQueue
    {
        private readonly SpeechSynthesizer _synth = new SpeechSynthesizer();

        public SystemSpeechQueue()
        {
            _synth.Rate = 3;
            _synth.Volume = 100;
        }

        public void SpeakAsync(string text) { _synth.SpeakAsync(text); }
        public void CancelAll() { _synth.SpeakAsyncCancelAll(); }
        public void Dispose() { _synth.Dispose(); }
    }

    internal class VoiceService : IBigOrderVoice
    {
        private readonly ISpeechQueue _queue;
        public bool Enabled { get; set; } = true;

        public VoiceService() : this(new SystemSpeechQueue()) { }
        internal VoiceService(ISpeechQueue queue) { _queue = queue; }

        internal static string BuildBatchText(IReadOnlyList<BigOrderAnnouncement> announcements)
        {
            return string.Join("，", (announcements ?? new BigOrderAnnouncement[0]).Select(value =>
            {
                switch (value.Type)
                {
                    case BigOrderAnnouncementType.Ignite:
                        return "点火 " + FormatAmount(value.Amount);
                    case BigOrderAnnouncementType.Smash:
                        return "砸盘 " + FormatAmount(value.Amount);
                    case BigOrderAnnouncementType.BuyActive:
                        return "买活跃";
                    default:
                        return "承接好";
                }
            }));
        }

        public void AnnounceBatch(IReadOnlyList<BigOrderAnnouncement> announcements)
        {
            if (!Enabled || announcements == null || announcements.Count == 0) return;
            var text = BuildBatchText(announcements);
            if (text.Length == 0) return;
            try { _queue.SpeakAsync(text); } catch { }
        }

        public void CancelPending()
        {
            try { _queue.CancelAll(); } catch { }
        }

        public void AnnounceIgnite(double amount)
        {
            AnnounceBatch(new[] { new BigOrderAnnouncement { Type = BigOrderAnnouncementType.Ignite, Amount = amount } });
        }

        public void AnnounceSmash(double amount)
        {
            AnnounceBatch(new[] { new BigOrderAnnouncement { Type = BigOrderAnnouncementType.Smash, Amount = amount } });
        }

        public void AnnounceBuyActive()
        {
            AnnounceBatch(new[] { new BigOrderAnnouncement { Type = BigOrderAnnouncementType.BuyActive } });
        }

        public void AnnounceGoodSupport()
        {
            AnnounceBatch(new[] { new BigOrderAnnouncement { Type = BigOrderAnnouncementType.GoodSupport } });
        }

        private static string FormatAmount(double amount)
        {
            return amount >= 100000000
                ? string.Format("{0:F1}亿", amount / 100000000)
                : string.Format("{0:F0}万", amount / 10000);
        }

        public void Dispose()
        {
            CancelPending();
            try { _queue.Dispose(); } catch { }
        }
    }
}
