// src/test/dataQualityChecker.ts
// 数据质量检查工具 - 用于验证增强版快照数据的完整性和正确性

import { dataLayer } from '../services/DataLayer'

/**
 * 数据质量检查器
 * 用于验证增强版快照数据的完整性和正确性
 */
export class DataQualityChecker {
  private readonly REQUIRED_METADATA_FIELDS = [
    'version',
    'totalStocks',
    'marketMode',
    'dataVersion',
    'timestamp',
  ]

  private readonly REQUIRED_TECHNICAL_INDICATORS = [
    'ma5',
    'ma10',
    'maTrend',
    'macd',
    'macdSignal',
    'macdHistogram',
    'macdCross',
    'percentile',
    'fundPenetration',
  ]

  private readonly REQUIRED_SIGNALS = ['direction', 'acceleration', 'cross', 'final']

  /**
   * 检查单个快照的数据质量
   */
  async checkSnapshotQuality(snapshotKey: string): Promise<{
    isValid: boolean
    issues: string[]
    stats: {
      totalStocks: number
      hasMetadata: boolean
      hasTechnicalIndicators: boolean
      hasSignals: boolean
      metadataVersion: string
      dataVersion: number
    }
  }> {
    const issues: string[] = []
    const snapshot = await dataLayer.getSnapshotFromDB(snapshotKey)

    if (!snapshot) {
      return {
        isValid: false,
        issues: [`快照不存在: ${snapshotKey}`],
        stats: {
          totalStocks: 0,
          hasMetadata: false,
          hasTechnicalIndicators: false,
          hasSignals: false,
          metadataVersion: 'unknown',
          dataVersion: 0,
        },
      }
    }

    // 检查快照类型
    const snapshotType = snapshot.type || 'unknown'
    console.log(`[DataQuality] 检查快照: ${snapshotKey}, 类型: ${snapshotType}`)

    // 1. 检查元数据
    const metadata = snapshot.metadata
    const hasMetadata = !!metadata
    let metadataVersion = 'unknown'
    let dataVersion = 0

    if (hasMetadata) {
      metadataVersion = metadata.version || 'unknown'
      dataVersion = metadata.dataVersion || 0

      // 检查必需字段
      for (const field of this.REQUIRED_METADATA_FIELDS) {
        if (metadata[field] === undefined) {
          issues.push(`元数据缺少字段: ${field}`)
        }
      }

      // 检查版本
      if (metadataVersion !== '2.0') {
        issues.push(`元数据版本不是2.0: ${metadataVersion}`)
      }
    } else {
      issues.push('快照缺少元数据字段')
    }

    // 2. 检查热榜数据
    const hotlist = snapshot.hotlist || []
    const totalStocks = hotlist.length

    if (totalStocks === 0) {
      issues.push('热榜数据为空')
    }

    // 3. 检查技术指标和信号
    let hasTechnicalIndicators = false
    let hasSignals = false
    let checkedStocks = 0

    for (const stock of hotlist.slice(0, 10)) {
      // 只检查前10只股票
      checkedStocks++

      // 检查技术指标
      const techIndicators = stock.technicalIndicators
      if (techIndicators) {
        hasTechnicalIndicators = true
        for (const field of this.REQUIRED_TECHNICAL_INDICATORS) {
          if (techIndicators[field] === undefined) {
            issues.push(`股票 ${stock.code} 缺少技术指标字段: ${field}`)
          }
        }
      } else {
        issues.push(`股票 ${stock.code} 缺少technicalIndicators字段`)
      }

      // 检查信号
      const signals = stock.signals
      if (signals) {
        hasSignals = true
        for (const signalType of this.REQUIRED_SIGNALS) {
          const signal = signals[signalType]
          if (!signal || signal.signal === undefined) {
            issues.push(`股票 ${stock.code} 缺少信号: ${signalType}`)
          }
        }
      } else {
        issues.push(`股票 ${stock.code} 缺少signals字段`)
      }
    }

    // 4. 检查数据一致性
    if (hasMetadata && metadata.totalStocks !== totalStocks) {
      issues.push(`元数据totalStocks(${metadata.totalStocks})与实际股票数(${totalStocks})不一致`)
    }

    // 5. 检查时间戳
    const snapshotTimestamp = snapshot.timestamp
    if (!snapshotTimestamp) {
      issues.push('快照缺少时间戳')
    }

    const isValid = issues.length === 0

    return {
      isValid,
      issues,
      stats: {
        totalStocks,
        hasMetadata,
        hasTechnicalIndicators,
        hasSignals,
        metadataVersion,
        dataVersion,
      },
    }
  }

  /**
   * 检查所有快照的数据质量
   */
  async checkAllSnapshots(): Promise<{
    totalSnapshots: number
    validSnapshots: number
    invalidSnapshots: number
    snapshotTypes: Record<string, number>
    issuesByType: Record<string, string[]>
    summary: {
      v1Snapshots: number
      v2Snapshots: number
      hasTechnicalIndicators: number
      hasSignals: number
    }
  }> {
    const snapshotDates = await dataLayer.getSnapshotDates()
    const totalSnapshots = snapshotDates.length

    console.log(`[DataQuality] 开始检查 ${totalSnapshots} 个快照`)

    let validSnapshots = 0
    let invalidSnapshots = 0
    const snapshotTypes: Record<string, number> = {}
    const issuesByType: Record<string, string[]> = {}
    let v1Snapshots = 0
    let v2Snapshots = 0
    let hasTechnicalIndicators = 0
    let hasSignals = 0

    for (const snapshotKey of snapshotDates) {
      const result = await this.checkSnapshotQuality(snapshotKey)
      const snapshot = await dataLayer.getSnapshotFromDB(snapshotKey)
      const type = snapshot?.type || 'unknown'

      // 统计快照类型
      snapshotTypes[type] = (snapshotTypes[type] || 0) + 1

      // 统计版本
      if (result.stats.metadataVersion === '2.0') {
        v2Snapshots++
      } else {
        v1Snapshots++
      }

      // 统计技术指标和信号
      if (result.stats.hasTechnicalIndicators) hasTechnicalIndicators++
      if (result.stats.hasSignals) hasSignals++

      if (result.isValid) {
        validSnapshots++
      } else {
        invalidSnapshots++
        if (!issuesByType[type]) issuesByType[type] = []
        issuesByType[type].push(...result.issues.slice(0, 3)) // 只记录前3个问题
      }

      // 每检查10个快照输出一次进度
      if ((validSnapshots + invalidSnapshots) % 10 === 0) {
        console.log(`[DataQuality] 进度: ${validSnapshots + invalidSnapshots}/${totalSnapshots}`)
      }
    }

    return {
      totalSnapshots,
      validSnapshots,
      invalidSnapshots,
      snapshotTypes,
      issuesByType,
      summary: {
        v1Snapshots,
        v2Snapshots,
        hasTechnicalIndicators,
        hasSignals,
      },
    }
  }

  /**
   * 生成数据质量报告
   */
  async generateQualityReport(): Promise<string> {
    const result = await this.checkAllSnapshots()
    const now = new Date()

    let report = `=== 数据质量检查报告 ===\n`
    report += `生成时间: ${now.toISOString()}\n`
    report += `\n`

    report += `📊 总体统计:\n`
    report += `总快照数: ${result.totalSnapshots}\n`
    report += `有效快照: ${result.validSnapshots}\n`
    report += `无效快照: ${result.invalidSnapshots}\n`
    report += `有效率: ${((result.validSnapshots / result.totalSnapshots) * 100).toFixed(1)}%\n`
    report += `\n`

    report += `📈 版本分布:\n`
    report += `v1.0 快照: ${result.summary.v1Snapshots}\n`
    report += `v2.0 快照: ${result.summary.v2Snapshots}\n`
    report += `\n`

    report += `🔧 功能支持:\n`
    report += `支持技术指标: ${result.summary.hasTechnicalIndicators}\n`
    report += `支持完整信号: ${result.summary.hasSignals}\n`
    report += `\n`

    report += `📁 快照类型分布:\n`
    for (const [type, count] of Object.entries(result.snapshotTypes)) {
      report += `  ${type}: ${count} 个\n`
    }
    report += `\n`

    if (result.invalidSnapshots > 0) {
      report += `⚠️ 问题汇总:\n`
      for (const [type, issues] of Object.entries(result.issuesByType)) {
        report += `  ${type} 类型的问题:\n`
        const uniqueIssues = [...new Set(issues)]
        for (const issue of uniqueIssues.slice(0, 5)) {
          // 只显示前5个问题
          report += `    - ${issue}\n`
        }
        if (uniqueIssues.length > 5) {
          report += `    ... 还有 ${uniqueIssues.length - 5} 个问题\n`
        }
      }
    } else {
      report += `✅ 所有快照数据质量良好！\n`
    }

    report += `\n`
    report += `💡 建议:\n`
    if (result.summary.v1Snapshots > 0) {
      report += `1. 有 ${result.summary.v1Snapshots} 个v1.0快照，建议重新保存为v2.0格式\n`
    }
    if (result.summary.hasTechnicalIndicators < result.totalSnapshots) {
      report += `2. 部分快照缺少技术指标，建议检查数据保存逻辑\n`
    }
    if (result.summary.hasSignals < result.totalSnapshots) {
      report += `3. 部分快照缺少完整信号，建议检查RankTrendAnalyzer\n`
    }

    return report
  }

  /**
   * 修复数据问题（如果可能）
   */
  async fixDataIssues(): Promise<{
    fixed: number
    failed: number
    details: string[]
  }> {
    const snapshotDates = await dataLayer.getSnapshotDates()
    const details: string[] = []
    let fixed = 0
    let failed = 0

    console.log(`[DataQuality] 开始修复 ${snapshotDates.length} 个快照`)

    for (const snapshotKey of snapshotDates) {
      try {
        const snapshot = await dataLayer.getSnapshotFromDB(snapshotKey)
        if (!snapshot) continue

        const type = snapshot.type
        let needsFix = false

        // 检查是否需要修复
        if (!snapshot.metadata) {
          needsFix = true
          details.push(`${snapshotKey}: 缺少元数据`)
        } else if (snapshot.metadata.version !== '2.0') {
          needsFix = true
          details.push(`${snapshotKey}: 版本不是2.0 (${snapshot.metadata.version})`)
        }

        // 如果需要修复，重新保存快照
        if (needsFix) {
          console.log(`[DataQuality] 尝试修复: ${snapshotKey}`)

          // 这里可以添加具体的修复逻辑
          // 例如：重新计算缺失的字段，然后重新保存

          details.push(`${snapshotKey}: 标记为需要修复`)
          failed++ // 暂时标记为修复失败，需要手动处理
        } else {
          fixed++
        }
      } catch (error) {
        console.error(`[DataQuality] 修复失败: ${snapshotKey}`, error)
        failed++
        details.push(`${snapshotKey}: 修复失败 - ${error}`)
      }
    }

    return {
      fixed,
      failed,
      details: details.slice(0, 20), // 只返回前20个详情
    }
  }

  /**
   * 导出数据质量报告到文件
   */
  async exportReportToFile(): Promise<void> {
    try {
      const report = await this.generateQualityReport()
      const blob = new Blob([report], { type: 'text/plain;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `data_quality_report_${new Date().toISOString().slice(0, 10)}.txt`
      link.click()
      URL.revokeObjectURL(url)
      console.log('[DataQuality] ✅ 报告已导出')
    } catch (error) {
      console.error('[DataQuality] ❌ 导出报告失败:', error)
    }
  }
}

// 导出单例
export const dataQualityChecker = new DataQualityChecker()

// 如果是在浏览器环境中，添加到全局对象
if (typeof window !== 'undefined') {
  ;(window as any).dataQualityChecker = dataQualityChecker
}

// 测试函数
export async function runDataQualityCheck() {
  console.log('=== 开始数据质量检查 ===')
  const checker = new DataQualityChecker()

  try {
    // 1. 生成报告
    const report = await checker.generateQualityReport()
    console.log(report)

    // 2. 导出报告
    await checker.exportReportToFile()

    // 3. 尝试修复问题
    const fixResult = await checker.fixDataIssues()
    console.log('修复结果:', fixResult)

    return { success: true, report }
  } catch (error) {
    console.error('数据质量检查失败:', error)
    return {
      success: false,
      error: error instanceof Error ? error.message : String(error),
    }
  }
}
