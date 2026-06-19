using System;
using System.Speech.Synthesis;

namespace THSBigOrder
{
    /// <summary>
    /// 语音播报服务
    /// </summary>
    public class VoiceService : IDisposable
    {
        private SpeechSynthesizer _synth;
        private bool _enabled = true;
        
        public bool Enabled 
        { 
            get => _enabled; 
            set => _enabled = value; 
        }

        public VoiceService()
        {
            _synth = new SpeechSynthesizer();
            _synth.Rate = 3;  // 语速：-10到10，3较快
            _synth.Volume = 100;  // 音量：0-100
        }

        /// <summary>
        /// 播报点火
        /// </summary>
        public void AnnounceIgnite(double amount)
        {
            if (!_enabled) return;
            string amountStr = FormatAmount(amount);
            SpeakAsync("点火 " + amountStr);
        }

        /// <summary>
        /// 播报砸盘
        /// </summary>
        public void AnnounceSmash(double amount)
        {
            if (!_enabled) return;
            string amountStr = FormatAmount(amount);
            SpeakAsync("砸盘 " + amountStr);
        }

        /// <summary>
        /// 播报买活跃
        /// </summary>
        public void AnnounceBuyActive()
        {
            if (!_enabled) return;
            SpeakAsync("买活跃");
        }

        /// <summary>
        /// 播报承接好
        /// </summary>
        public void AnnounceGoodSupport()
        {
            if (!_enabled) return;
            SpeakAsync("承接好");
        }

        private string FormatAmount(double amount)
        {
            if (amount >= 100000000)
                return string.Format("{0:F1}亿", amount / 100000000);
            return string.Format("{0:F0}万", amount / 10000);
        }

        private void SpeakAsync(string text)
        {
            try
            {
                // 异步播报，不阻塞UI
                _synth.SpeakAsyncCancelAll();  // 取消之前的播报，避免堆积
                _synth.SpeakAsync(text);
            }
            catch { }
        }

        public void Dispose()
        {
            try
            {
                _synth?.SpeakAsyncCancelAll();
                _synth?.Dispose();
            }
            catch { }
        }
    }
}
