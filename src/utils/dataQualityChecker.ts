// src/utils/dataQualityChecker.ts
/**
 * 数据质量检查工具
 * 用于验证增强版快照数据的完整性和正确性
 */

import { dataLayer } from '../services/DataLayer'

export interface DataQualityReport {
  timestamp: number
