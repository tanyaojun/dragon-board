determineRotationState(momentum, trend) {
  if (trend > 50 && momentum > 20)  // 主升浪
  if (trend < -50 && momentum < -20) // 主跌浪
  if (momentum > 20)  // 强势进攻
  if (momentum > 10)  // 震荡上行
  if (momentum < -10 && momentum >= -20) // 震荡下行
  if (momentum < -20) // 弱势退潮
  else // 震荡
}