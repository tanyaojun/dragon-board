// src/services/VoiceService.ts
import { ref } from 'vue'
import { EventManager } from '@/utils/eventManager'
import { AppEvents } from '@/types'

export class VoiceService {
  private static instance: VoiceService
  private synth: SpeechSynthesis
  private currentUtterance: SpeechSynthesisUtterance | null = null
  
  // 响应式状态
  public supported = ref(false)
  public speaking = ref(false)
  public paused = ref(false)
  public voices = ref<SpeechSynthesisVoice[]>([])

  private constructor() {
    this.synth = window.speechSynthesis
    this.checkSupport()
    this.loadVoices()
    
    // 监听 voices 变化（某些浏览器异步加载）
    if (this.synth.onvoiceschanged !== undefined) {
      this.synth.onvoiceschanged = this.loadVoices.bind(this)
    }
  }

  static getInstance(): VoiceService {
    if (!VoiceService.instance) {
      VoiceService.instance = new VoiceService()
    }
    return VoiceService.instance
  }

  /**
   * 检查浏览器是否支持语音合成
   */
  private checkSupport() {
    this.supported.value = 'speechSynthesis' in window
  }

  /**
   * 加载可用语音列表
   */
  private loadVoices() {
    this.voices.value = this.synth.getVoices()
  }

  /**
   * 获取中文语音
   */
  private getChineseVoice(): SpeechSynthesisVoice | undefined {
    return this.voices.value.find(voice => 
      voice.lang.includes('zh') || voice.lang.includes('cmn')
    )
  }

  /**
   * 播报文本
   */
  speak(text: string, options?: {
    rate?: number      // 语速 0.1-10
    pitch?: number     // 音调 0-2
    volume?: number    // 音量 0-1
    lang?: string      // 语言
    voice?: SpeechSynthesisVoice
  }) {
    if (!this.supported.value) {
      console.warn('[VoiceService] 当前浏览器不支持语音播报')
      return false
    }

    // 取消当前播报
    this.stop()

    const utterance = new SpeechSynthesisUtterance(text)
    
    // 设置参数
    utterance.rate = options?.rate ?? 1
    utterance.pitch = options?.pitch ?? 1
    utterance.volume = options?.volume ?? 1
    utterance.lang = options?.lang ?? 'zh-CN'
    utterance.voice = options?.voice ?? this.getChineseVoice() ?? null

    // 事件监听
    utterance.onstart = () => {
      this.speaking.value = true
      this.paused.value = false
      EventManager.emit('voice:start', { text })
    }

    utterance.onend = () => {
      this.speaking.value = false
      this.currentUtterance = null
      EventManager.emit('voice:end', { text })
    }

    utterance.onerror = (event) => {
      this.speaking.value = false
      this.currentUtterance = null
      console.error('[VoiceService] 播报错误:', event)
      EventManager.emit('voice:error', { text, error: event })
    }

    utterance.onpause = () => {
      this.paused.value = true
      EventManager.emit('voice:pause')
    }

    utterance.onresume = () => {
      this.paused.value = false
      EventManager.emit('voice:resume')
    }

    this.currentUtterance = utterance
    this.synth.speak(utterance)
    
    return true
  }

  /**
   * 停止播报
   */
  stop() {
    if (this.speaking.value) {
      this.synth.cancel()
      this.speaking.value = false
      this.currentUtterance = null
    }
  }

  /**
   * 暂停播报
   */
  pause() {
    if (this.speaking.value && !this.paused.value) {
      this.synth.pause()
    }
  }

  /**
   * 恢复播报
   */
  resume() {
    if (this.paused.value) {
      this.synth.resume()
    }
  }

  /**
   * 获取所有可用语音
   */
  getVoices() {
    return this.voices.value
  }

  /**
   * 销毁服务
   */
  destroy() {
    this.stop()
  }
}

// 导出单例
export const voiceService = VoiceService.getInstance()

if (typeof window !== 'undefined') {
  ;(window as any).voiceService = voiceService
}