import { readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const panelSource = () =>
  readFileSync(join(process.cwd(), 'src', 'components', 'panels', 'HotStockEventMonitorPanel.vue'), 'utf8')

describe('HotStockEventMonitorPanel speech settings', () => {
  test('shows local voice select for local non-cloud speech engines', () => {
    const source = panelSource()

    expect(source).toContain('v-if="showSpeechVoiceSelect"')
    expect(source).toContain('v-model="speechVoice"')
    expect(source).toContain('speechEngine.value !== \'volcengine\'')
    expect(source).toContain('未检测到系统语音')
  })
})
