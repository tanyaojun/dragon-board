// src/composables/useVoice.ts
import { ref, onUnmounted } from 'vue'
import { voiceService } from '@/services/VoiceService'

export function useVoice() {
  const supported = voiceService.supported
  const speaking = voiceService.speaking
  const paused = voiceService.paused
  const voices = voiceService.voices

  /**
   * 播报文本
   */
  const speak = (text: string, options?: Parameters<typeof voiceService.speak>[1]) => {
    return voiceService.speak(text, options)
  }

  /**
   * 停止播报
   */
  const stop = () => voiceService.stop()

  /**
   * 暂停播报
   */
  const pause = () => voiceService.pause()

  /**
   * 恢复播报
   */
  const resume = () => voiceService.resume()

  /**
   * 获取所有语音
   */
  const getVoices = () => voiceService.getVoices()

  onUnmounted(() => {
    // 组件卸载时停止播报（可选）
    // stop()
  })

  return {
    supported,
    speaking,
    paused,
    voices,
    speak,
    stop,
    pause,
    resume,
    getVoices
  }
}