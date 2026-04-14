// src/services/Algorithm/index.ts
export { AlgorithmManager, algorithmManager } from './AlgorithmManager'
export { AlgorithmPerformanceMonitor } from './AlgorithmPerformanceMonitor'
//export { AlgorithmWarmupManager } from './AlgorithmWarmupManager'
export { AlgorithmHealthChecker } from './AlgorithmHealthChecker'
export { AlgorithmABTestManager } from './AlgorithmABTestManager'
export { CalculationQueue, calculationQueue } from './CalculationQueue'
export { ConsistencyManager, consistencyManager } from './ConsistencyManager'

// 重新导出类型
export type { IAlgorithmManager } from './AlgorithmManager'
export type {
  PerformanceMetrics,
  FactorPerformance,
  FactorHealth,
  //WarmupStrategy,
  ABTest,
  HealthCheckResult,
} from '@/types/algorithm'
