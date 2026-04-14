// calculateMomentum 函数
动量 = (
  百分比变化 * PCT_WEIGHT +
  趋势斜率 * TREND_WEIGHT +
  加速度 * ACCEL_WEIGHT
)

// 参数
CONFIG.MOMENTUM = {
  SHORT_WINDOW: 5,    // 短期窗口
  LONG_WINDOW: 10,    // 长期窗口
  TREND_WINDOW: 8,    // 趋势窗口
  PCT_WEIGHT: 0.5,    // 百分比权重
  TREND_WEIGHT: 0.3,  // 趋势权重
  ACCEL_WEIGHT: 0.2   // 加速度权重
}