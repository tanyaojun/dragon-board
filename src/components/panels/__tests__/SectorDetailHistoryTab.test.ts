import { existsSync, readFileSync } from 'node:fs'
import { join } from 'node:path'

import { describe, expect, test } from 'vitest'

const panelPath = () => join(process.cwd(), 'src', 'components', 'panels', 'SectorDetail.vue')
const panelSource = () => readFileSync(panelPath(), 'utf8')

function loadHistoryDataBody(source: string): string {
  const match = source.match(/async function loadHistoryData\(\)[\s\S]*?\n\}/)
  expect(match).toBeTruthy()
  return match![0]
}

describe('SectorDetail history tab source contract', () => {
  test('wires the history series service with structured failure states', () => {
    expect(existsSync(panelPath())).toBe(true)
    const source = panelSource()

    // 生产数据链：服务装配 + 两源独立成败提示
    expect(source).toMatch(/fetchThemeHistorySeries/)
    expect(source).not.toMatch(/generateHistoryData/)
    expect(source).toMatch(/historySourceHint/)
    expect(source).toMatch(/historyError/)
    expect(source).toMatch(/historyPoints\.length === 0/)
  })

  test('releases the loading state before rendering the chart so chartRef is mounted', () => {
    const source = panelSource()
    const body = loadHistoryDataBody(source)

    // 回归：renderChart() 依赖 v-else 分支中的 chartRef 容器；
    // historyLoading 仍为 true 时容器未挂载，renderChart 会在 !chartRef.value 处静默跳过。
    const releaseIdx = body.indexOf('historyLoading.value = false')
    const nextTickIdx = body.indexOf('await nextTick()')
    const renderIdx = body.lastIndexOf('renderChart()')

    expect(releaseIdx).toBeGreaterThan(-1)
    expect(nextTickIdx).toBeGreaterThan(releaseIdx)
    expect(renderIdx).toBeGreaterThan(nextTickIdx)
  })

  test('guards stale responses and missing block code', () => {
    const source = panelSource()
    const body = loadHistoryDataBody(source)

    expect(body).toMatch(/if \(!blockCode\.value \|\| !props\.sectorName\) return/)
    expect(body).toMatch(/if \(requestId !== historyRequestId\) return/)
  })

  test('re-creates the chart when its container element is remounted', () => {
    const source = panelSource()
    const renderMatch = source.match(/function renderChart\(\)[\s\S]*?\n\}/)
    expect(renderMatch).toBeTruthy()
    const body = renderMatch![0]

    // loading/error/空态的 v-if 状态链会卸载并重挂 chartRef 容器（如切换时间范围）；
    // 旧 ECharts 实例此时绑定的是已分离 DOM，必须检测并 dispose 重建，
    // 否则 setOption 落在分离节点上、图表空白。
    expect(body).toMatch(/getDom\(\) !== chartRef\.value/)
    expect(body).toMatch(/chart\.dispose\(\)/)
  })

  test('removes the window resize listener on unmount', () => {
    const source = panelSource()

    // 面板是 v-if 挂载的浮层：匿名 resize 监听器无法移除，反复开关面板会累积
    // 监听器并闭包引用已 dispose 的 chart 实例。
    expect(source).toMatch(/window\.addEventListener\('resize', handleWindowResize\)/)
    expect(source).toMatch(/window\.removeEventListener\('resize', handleWindowResize\)/)

    const unmountMatch = source.match(/onUnmounted\(\(\) => \{[\s\S]*?\n  \}\)/)
    expect(unmountMatch).toBeTruthy()
    expect(unmountMatch![0]).toContain("removeEventListener('resize', handleWindowResize)")
  })
})
