import { debugLog } from '@/utils/logger'
// src/services/Algorithm/AlgorithmABTestManager.ts
// AB测试管理模块

import type { IAlgorithmManager } from './AlgorithmManager'
import type { ABTest, ABTestResult } from '@/types/algorithm'

import { ALGORITHMS } from '@/config/algorithms'
import { EventManager } from '@/utils/eventManager'
import { hashCode, calculateConfidence } from '@/utils/algorithmHelpers'
import { dataLayer } from '@/services/DataLayer'

export class AlgorithmABTestManager {
  private algorithmManager: IAlgorithmManager
  private tests: Map<string, ABTest> = new Map()
  private results: Map<string, ABTestResult[]> = new Map()
  private assignmentCache: Map<string, string> = new Map() // stockCode -> testAlgorithm
  private readonly STORAGE_KEY = 'algorithm_ab_tests'

  constructor(algorithmManager: IAlgorithmManager) {
    this.algorithmManager = algorithmManager
  }

  /**
   * 保存测试
   */
  private saveTests(): void {
    try {
      const tests = Array.from(this.tests.values())
      localStorage.setItem(this.STORAGE_KEY, JSON.stringify(tests))
    } catch (e) {
      console.warn('[AlgorithmABTest] 保存测试失败:', e)
    }
  }

  /**
   * 创建AB测试
   */
  createTest(config: Omit<ABTest, 'id' | 'metrics' | 'status' | 'startTime'>): string {
    // 验证算法是否存在
    if (!ALGORITHMS[config.controlAlgorithm]) {
      throw new Error(`对照组算法不存在: ${config.controlAlgorithm}`)
    }
    if (!ALGORITHMS[config.testAlgorithm]) {
      throw new Error(`测试组算法不存在: ${config.testAlgorithm}`)
    }

    const testId = `test_${Date.now()}_${Math.random().toString(36).substr(2, 9)}`

    const test: ABTest = {
      id: testId,
      ...config,
      metrics: {
        controlAvgScore: 0,
        testAvgScore: 0,
        controlSuccessRate: 0,
        testSuccessRate: 0,
        sampleSize: 0,
        confidence: 0,
      },
      status: 'draft',
      startTime: Date.now(),
    }

    this.tests.set(testId, test)
    this.results.set(testId, [])
    this.saveTests()

    debugLog(`[AlgorithmABTest] 📝 创建测试: ${test.name} (${testId})`)
    return testId
  }

  /**
   * 启动测试
   */
  startTest(testId: string): boolean {
    const test = this.tests.get(testId)
    if (!test) return false

    test.status = 'running'
    this.assignmentCache.clear()
    this.saveTests()

    debugLog(`[AlgorithmABTest] ▶️ 启动测试: ${test.name}`)
    debugLog(`   ├─ 对照组: ${test.controlAlgorithm}`)
    debugLog(`   ├─ 实验组: ${test.testAlgorithm}`)
    debugLog(`   └─ 流量占比: ${test.traffic}%`)

    EventManager.emit('algorithm:ab-test-started', { ...test })
    return true
  }

  /**
   * 停止测试
   */
  stopTest(testId: string): boolean {
    const test = this.tests.get(testId)
    if (!test) return false

    test.status = 'stopped'
    test.endTime = Date.now()
    this.assignmentCache.clear()
    this.saveTests()

    debugLog(`[AlgorithmABTest] ⏹️ 停止测试: ${test.name}`)
    EventManager.emit('algorithm:ab-test-stopped', { ...test })
    return true
  }

  /**
   * 完成测试
   */
  completeTest(testId: string): ABTest | null {
    const test = this.tests.get(testId)
    if (!test) return null

    test.status = 'completed'
    test.endTime = Date.now()
    this.updateTestMetrics(testId)
    this.assignmentCache.clear()
    this.saveTests()

    const report = this.getTestReport(testId)
    debugLog(`[AlgorithmABTest] 📊 测试完成: ${test.name}`, report)

    EventManager.emit('algorithm:ab-test-completed', { ...test, report })
    return test
  }

  /**
   * 获取股票应该使用的算法
   */
  getAlgorithmForStock(stockCode: string): string {
    // 检查缓存
    const cached = this.assignmentCache.get(stockCode)
    if (cached) return cached

    // 找出正在运行的测试
    const runningTests = Array.from(this.tests.values()).filter((t) => t.status === 'running')

    for (const test of runningTests) {
      const hash = hashCode(stockCode) % 100
      if (hash < test.traffic) {
        this.assignmentCache.set(stockCode, test.testAlgorithm)
        return test.testAlgorithm
      }
    }

    return this.algorithmManager.getCurrentAlgorithm().id
  }

  /**
   * 记录测试结果（根据算法ID查找对应的运行中测试）
   */
  recordResult(algorithmId: string, result: Omit<ABTestResult, 'testId' | 'timestamp'>): void {
    const runningTests = this.getRunningTests()
    const test = runningTests.find(
      (t) => t.testAlgorithm === algorithmId || t.controlAlgorithm === algorithmId
    )
    if (!test) return

    const results = this.results.get(test.id) || []

    const fullResult: ABTestResult = {
      ...result,
      testId: test.id,
      timestamp: Date.now(),
    }

    results.push(fullResult)
    this.results.set(test.id, results)

    if (results.length % 100 === 0) {
      this.updateTestMetrics(test.id)
    }
  }

  /**
   * 更新测试指标
   */
  private updateTestMetrics(testId: string): void {
    const test = this.tests.get(testId)
    const results = this.results.get(testId)
    if (!test || !results || results.length === 0) return

    // 分离对照组和测试组结果
    const controlResults = results.filter((r) => r.algorithmId === test.controlAlgorithm)
    const testResults = results.filter((r) => r.algorithmId === test.testAlgorithm)

    if (controlResults.length === 0 || testResults.length === 0) return

    // 计算平均分
    const controlAvgScore =
      controlResults.reduce((sum, r) => sum + r.score, 0) / controlResults.length
    const testAvgScore = testResults.reduce((sum, r) => sum + r.score, 0) / testResults.length

    // 计算成功率
    const controlSuccessRate =
      (controlResults.filter((r) => r.success).length / controlResults.length) * 100
    const testSuccessRate = (testResults.filter((r) => r.success).length / testResults.length) * 100

    // 计算置信度
    const confidence = calculateConfidence(
      controlResults.filter((r) => r.success).length,
      testResults.filter((r) => r.success).length,
      Math.min(controlResults.length, testResults.length),
    )

    test.metrics = {
      controlAvgScore,
      testAvgScore,
      controlSuccessRate,
      testSuccessRate,
      sampleSize: results.length,
      confidence,
    }

    this.saveTests()
  }

  /**
   * 获取测试报告
   */
  getTestReport(testId: string): any {
    const test = this.tests.get(testId)
    const results = this.results.get(testId)
    if (!test) return null

    const controlResults = results?.filter((r) => r.algorithmId === test.controlAlgorithm) || []
    const testResults = results?.filter((r) => r.algorithmId === test.testAlgorithm) || []

    // 判断是否有显著差异
    const improvement = test.metrics.testAvgScore - test.metrics.controlAvgScore
    const hasSignificantImprovement = test.metrics.confidence > 95 && improvement > 5

    return {
      ...test,
      results: {
        control: {
          count: controlResults.length,
          avgScore: test.metrics.controlAvgScore.toFixed(2),
          successRate: test.metrics.controlSuccessRate.toFixed(2) + '%',
        },
        test: {
          count: testResults.length,
          avgScore: test.metrics.testAvgScore.toFixed(2),
          successRate: test.metrics.testSuccessRate.toFixed(2) + '%',
        },
      },
      analysis: {
        improvement: improvement.toFixed(2),
        confidence: test.metrics.confidence.toFixed(2) + '%',
        hasSignificantImprovement,
        recommendation: hasSignificantImprovement ? '建议采用测试组算法' : '建议继续观察或停止测试',
      },
    }
  }

  /**
   * 获取所有测试
   */
  getAllTests(): ABTest[] {
    return Array.from(this.tests.values())
  }

  /**
   * 获取运行中的测试
   */
  getRunningTests(): ABTest[] {
    return Array.from(this.tests.values()).filter((t) => t.status === 'running')
  }

  /**
   * 删除测试
   */
  deleteTest(testId: string): boolean {
    const deleted = this.tests.delete(testId)
    this.results.delete(testId)
    this.assignmentCache.clear()
    if (deleted) {
      this.saveTests()
    }
    return deleted
  }

  /**
   * 导出测试数据
   */
  exportTestData(testId: string): any {
    const test = this.tests.get(testId)
    const results = this.results.get(testId)

    return {
      test,
      results,
      exportTime: Date.now(),
    }
  }

  /**
   * 停止所有运行中的测试，供 AlgorithmManager 销毁时调用。
   */
  stop(): void {
    this.getRunningTests().forEach((test) => {
      this.stopTest(test.id)
    })
    this.assignmentCache.clear()
  }
}
