// scripts/updateThemeMapping.js
/**
 * 题材映射表更新脚本
 * 从API获取最新题材数据，生成静态映射文件
 *
 * 使用方法：
 * npm run update-themes
 *
 * 或者直接运行：
 * node scripts/updateThemeMapping.js
 */

import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'
import fetch from 'node-fetch'

// 获取当前文件的目录路径（ES模块替代__dirname）
const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// ========== 配置 ==========
// scripts/updateThemeMapping.js

const CONFIG = {
  // API 接口地址 - 从 vite.config.ts 可以确定是 localhost:3000
  API_BASE_URL: process.env.API_BASE_URL || 'http://localhost:3000',

  // 输出文件路径
  OUTPUT_PATH: path.join(__dirname, '../public/data/theme_stock_mapping.json'),

  // 请求配置
  REQUEST_TIMEOUT: 30000,
  MAX_RETRIES: 3,

  // 并发控制
  BATCH_SIZE: 10,
  BATCH_DELAY: 500,

  // 是否压缩输出
  MINIFY: false,
}

// ========== 日志工具 ==========
const logger = {
  info: (...args) => console.log('\x1b[36m%s\x1b[0m', '[INFO]', ...args),
  success: (...args) => console.log('\x1b[32m%s\x1b[0m', '[SUCCESS]', ...args),
  warn: (...args) => console.log('\x1b[33m%s\x1b[0m', '[WARN]', ...args),
  error: (...args) => console.log('\x1b[31m%s\x1b[0m', '[ERROR]', ...args),
  debug: (...args) => process.env.DEBUG && console.log('[DEBUG]', ...args),
}

// ========== 工具函数 ==========

/**
 * 延迟函数
 */
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

/**
 * 规范化股票代码
 */
const normalizeCode = (code) => {
  if (!code) return ''
  return String(code).replace(/[^\d]/g, '').padStart(6, '0')
}

/**
 * 获取带超时的 fetch
 */
async function fetchWithTimeout(url, options, timeout = CONFIG.REQUEST_TIMEOUT) {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    })
    clearTimeout(timeoutId)
    return response
  } catch (error) {
    clearTimeout(timeoutId)
    throw error
  }
}

/**
 * 带重试的请求
 */
async function requestWithRetry(url, options = {}, retries = CONFIG.MAX_RETRIES) {
  let lastError

  for (let i = 0; i <= retries; i++) {
    try {
      const response = await fetchWithTimeout(url, options)

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`)
      }

      return await response.json()
    } catch (error) {
      lastError = error
      logger.warn(`请求失败 (${i + 1}/${retries + 1}): ${error.message}`)

      if (i < retries) {
        const waitTime = 1000 * Math.pow(2, i) // 指数退避
        logger.info(`等待 ${waitTime}ms 后重试...`)
        await delay(waitTime)
      }
    }
  }

  throw lastError
}

// ========== 数据获取 ==========

/**
 * 获取所有题材列表
 */
async function fetchAllThemes() {
  logger.info('获取题材列表...')

  const data = await requestWithRetry(`${CONFIG.API_BASE_URL}/api/themes/list`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  })

  // 根据实际API返回结构调整
  const themes = data.data || data.themes || data.list || data

  if (!Array.isArray(themes)) {
    throw new Error('API返回格式错误：不是数组')
  }

  logger.success(`获取到 ${themes.length} 个题材`)
  return themes
}

/**
 * 批量获取题材详情
 */
async function fetchThemesBatch(themeIds) {
  if (!themeIds.length) return []

  logger.debug(`批量获取 ${themeIds.length} 个题材详情...`)

  const data = await requestWithRetry(`${CONFIG.API_BASE_URL}/api/themes/batch`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ ids: themeIds }),
  })

  return data.data || data.results || data
}

/**
 * 获取单个题材详情（备用方案）
 */
async function fetchThemeDetail(themeId) {
  logger.debug(`获取题材详情: ${themeId}`)

  return await requestWithRetry(`${CONFIG.API_BASE_URL}/api/theme/${themeId}`, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    },
  })
}

// ========== 数据处理 ==========

/**
 * 处理股票列表，提取代码
 */
function extractStockCodes(stockList) {
  if (!Array.isArray(stockList)) return []

  return stockList
    .map((stock) => {
      // 处理不同字段名
      const code = stock.code || stock.stockCode || stock.stock_id || stock.StockID || stock.id
      return normalizeCode(code)
    })
    .filter((code) => code && code !== '000000')
}

/**
 * 构建题材映射
 */
async function buildThemeMapping(themes) {
  logger.info('开始构建题材映射...')

  const mapping = {
    version: '1.0.0',
    lastUpdate: new Date().toISOString().split('T')[0],
    themes: [],
  }

  let successCount = 0
  let failCount = 0

  // 分批处理，避免请求过多
  for (let i = 0; i < themes.length; i += CONFIG.BATCH_SIZE) {
    const batch = themes.slice(i, i + CONFIG.BATCH_SIZE)
    const batchIds = batch.map((t) => t.id || t.ID).filter(Boolean)

    logger.info(
      `处理批次 ${i + 1}-${Math.min(i + CONFIG.BATCH_SIZE, themes.length)}/${themes.length}`,
    )

    try {
      // 尝试批量获取
      let batchResults = []
      try {
        batchResults = await fetchThemesBatch(batchIds)
      } catch (error) {
        logger.warn(`批量获取失败，尝试单个获取: ${error.message}`)
      }

      // 处理批次结果
      for (let j = 0; j < batch.length; j++) {
        const theme = batch[j]
        const themeId = theme.id || theme.ID
        const themeName = theme.name || theme.Name

        if (!themeId || !themeName) {
          logger.warn(`跳过无效题材: ${JSON.stringify(theme)}`)
          failCount++
          continue
        }

        let stockCodes = []

        // 从批量结果中查找
        if (batchResults[j]?.StockList) {
          stockCodes = extractStockCodes(batchResults[j].StockList)
        }

        // 如果批量结果没有，尝试单个获取
        if (stockCodes.length === 0) {
          try {
            const detail = await fetchThemeDetail(themeId)
            if (detail?.StockList) {
              stockCodes = extractStockCodes(detail.StockList)
            }
          } catch (error) {
            logger.debug(`获取题材 ${themeId} 详情失败: ${error.message}`)
          }
        }

        // 如果还是没有，使用空数组
        if (stockCodes.length === 0) {
          logger.warn(`题材 ${themeName} (${themeId}) 没有股票数据`)
        }

        mapping.themes.push({
          id: String(themeId),
          name: String(themeName).trim(),
          stocks: stockCodes,
        })

        successCount++
      }
    } catch (error) {
      logger.error(`批次处理失败:`, error)
      failCount += batch.length
    }

    // 批次间延迟
    if (i + CONFIG.BATCH_SIZE < themes.length) {
      await delay(CONFIG.BATCH_DELAY)
    }
  }

  logger.success(`处理完成: 成功 ${successCount}, 失败 ${failCount}`)
  return mapping
}

// ========== 文件操作 ==========

/**
 * 确保目录存在
 */
function ensureDirectoryExistence(filePath) {
  const dirname = path.dirname(filePath)
  if (fs.existsSync(dirname)) {
    return true
  }
  ensureDirectoryExistence(dirname)
  fs.mkdirSync(dirname, { recursive: true })
}

/**
 * 保存映射文件
 */
function saveMappingFile(mapping) {
  logger.info(`保存到文件: ${CONFIG.OUTPUT_PATH}`)

  // 确保目录存在
  ensureDirectoryExistence(CONFIG.OUTPUT_PATH)

  // 生成 JSON 字符串
  const jsonString = CONFIG.MINIFY ? JSON.stringify(mapping) : JSON.stringify(mapping, null, 2)

  // 写入文件
  fs.writeFileSync(CONFIG.OUTPUT_PATH, jsonString, 'utf8')

  // 获取文件大小
  const stats = fs.statSync(CONFIG.OUTPUT_PATH)
  const fileSize = (stats.size / 1024).toFixed(2)

  logger.success(`文件已保存，大小: ${fileSize} KB`)
}

// ========== 主函数 ==========

async function main() {
  console.log('\n' + '='.repeat(60))
  console.log(' 题材映射表更新脚本 v1.0.0')
  console.log('='.repeat(60) + '\n')

  const startTime = Date.now()

  try {
    // 1. 获取所有题材列表
    const themes = await fetchAllThemes()

    if (themes.length === 0) {
      throw new Error('没有获取到任何题材')
    }

    // 2. 构建映射
    const mapping = await buildThemeMapping(themes)

    // 3. 添加统计信息
    const stockSet = new Set()
    mapping.themes.forEach((theme) => {
      theme.stocks.forEach((code) => stockSet.add(code))
    })

    mapping.stats = {
      themeCount: mapping.themes.length,
      stockCount: stockSet.size,
      generatedAt: new Date().toISOString(),
    }

    // 4. 保存文件
    saveMappingFile(mapping)

    // 5. 输出统计
    const duration = ((Date.now() - startTime) / 1000).toFixed(2)
    console.log('\n' + '='.repeat(60))
    console.log(' 更新完成！')
    console.log('='.repeat(60))
    console.log(` 📊 题材数量: ${mapping.stats.themeCount}`)
    console.log(` 📈 股票数量: ${mapping.stats.stockCount}`)
    console.log(` ⏱️  耗时: ${duration}秒`)
    console.log(` 📁 文件路径: ${CONFIG.OUTPUT_PATH}`)
    console.log('='.repeat(60) + '\n')
  } catch (error) {
    logger.error('更新失败:', error)
    process.exit(1)
  }
}

// 运行主函数
main()

// ========== 导出供其他脚本使用 ==========
export { fetchAllThemes, fetchThemeDetail, fetchThemesBatch, buildThemeMapping, saveMappingFile }
