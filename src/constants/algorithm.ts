// src/constants/algorithm.ts
// 算法相关的常量（可选）

export const ALGORITHM_CATEGORIES = {
  comprehensive: { name: '综合型', icon: '⚖️', color: '#3498db' },
  leader: { name: '龙头型', icon: '👑', color: '#FFD700' },
  money: { name: '资金型', icon: '💰', color: '#2ed573' },
  technical: { name: '技术型', icon: '📈', color: '#ffa502' },
  sentiment: { name: '情绪型', icon: '🔥', color: '#ff7f50' },
  ml: { name: '机器学习', icon: '🤖', color: '#9b59b6' }
} as const

export const FACTOR_TYPES = {
  rank: { name: '排名', icon: '📊' },
  money: { name: '资金', icon: '💰' },
  technical: { name: '技术', icon: '📈' },
  sentiment: { name: '情绪', icon: '😊' },
  theme: { name: '题材', icon: '🎯' },
  breath: { name: '龙息', icon: '🌬️' }
} as const

export const PERFORMANCE_THRESHOLDS = {
  healthy: { minStability: 60, maxErrorRate: 0.1 },
  warning: { minStability: 40, maxErrorRate: 0.2 },
  critical: { minStability: 20, maxErrorRate: 0.3 }
} as const