// scripts/updateThemeMapping.js
import fs from 'fs'
import path from 'path'
import { fileURLToPath } from 'url'

const __filename = fileURLToPath(import.meta.url)
const __dirname = path.dirname(__filename)

// ========== 配置 ==========
const CONFIG = {
  // API地址
  API_BASE_URL: process.env.API_BASE_URL || 'http://localhost:3000',
  
  // 输出文件路径
  OUTPUT_PATH: path.join(__dirname, '../public/data/theme_base_mapping.json'),
  
  // 请求配置
  REQUEST_TIMEOUT: 30000,
  MAX_RETRIES: 3,
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
const delay = (ms) => new Promise(resolve => setTimeout(resolve, ms))

const normalizeCode = (code) => {
  if (!code) return ''
  return String(code).replace(/[^\d]/g, '').padStart(6, '0')
}

async function fetchWithTimeout(url, options, timeout = CONFIG.REQUEST_TIMEOUT) {
  const controller = new AbortController()
  const timeoutId = setTimeout(() => controller.abort(), timeout)
  
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal
    })
    clearTimeout(timeoutId)
    return response
  } catch (error) {
    clearTimeout(timeoutId)
    throw error
  }
}

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
        const waitTime = 1000 * Math.pow(2, i)
        await delay(waitTime)
      }
    }
  }
  
  throw lastError
}

// ========== 从KPL获取题材列表 ==========
async function fetchThemeListFromKPL() {
  logger.info('从 KPL 获取题材列表...')
  
  try {
    const url = `${CONFIG.API_BASE_URL}/api/kpl/hot`
    const data = await requestWithRetry(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
      }
    })
    
    // KPL返回的数据格式可能不同，需要根据实际情况调整
    const themes = data.data || data.list || data
    
    if (Array.isArray(themes) && themes.length > 0) {
      const themeList = themes.map(item => ({
        id: String(item.ID || item.id || item.ThemeID || ''),
        name: item.Name || item.name || item.ThemeName || ''
      })).filter(t => t.id && t.name)
      
      logger.success(`从 KPL 获取到 ${themeList.length} 个题材`)
      return themeList
    }
    
    throw new Error('返回数据格式错误')
  } catch (error) {
    logger.error('从 KPL 获取失败:', error)
    throw error
  }
}

// ========== 从全局变量获取题材列表（开发环境）==========
async function fetchThemeListFromGlobal() {
  logger.info('尝试从全局变量获取题材列表...')
  
  // 注意：这个只能在浏览器环境运行，脚本中不能用
  // 这里只是占位，实际使用时需要从其他来源获取
  throw new Error('不能在 Node.js 环境获取全局变量')
}

// ========== 获取题材详情 ==========
async function fetchThemeDetail(themeId) {
  logger.debug(`获取题材详情: ${themeId}`)
  
  const url = `${CONFIG.API_BASE_URL}/api/theme/${themeId}`
  const data = await requestWithRetry(url, {
    method: 'GET',
    headers: {
      'Content-Type': 'application/json',
    }
  })
  
  if (data.errcode !== '0') {
    throw new Error(`API error: ${data.errcode}`)
  }
  
  return data
}

// ========== 批量获取题材详情 ==========
async function fetchThemesBatch(themeIds) {
  if (!themeIds.length) return []
  
  logger.debug(`批量获取 ${themeIds.length} 个题材详情...`)
  
  try {
    const data = await requestWithRetry(`${CONFIG.API_BASE_URL}/api/themes/batch`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ ids: themeIds })
    })
    
    return data.results || data
  } catch (error) {
    logger.error('批量获取失败，转为单个获取')
    
    // 降级为单个获取
    const results = []
    for (const id of themeIds) {
      try {
        const detail = await fetchThemeDetail(id)
        results.push({ id, data: detail, success: true })
        await delay(200)
      } catch (err) {
        results.push({ id, success: false, error: err.message })
      }
    }
    return results
  }
}

// ========== 提取股票代码 ==========
function extractStockCodes(themeData) {
  const codes = new Set()
  
  // 从 StockList 提取
  if (themeData.StockList && Array.isArray(themeData.StockList)) {
    themeData.StockList.forEach(stock => {
      if (stock.StockID) {
        codes.add(normalizeCode(stock.StockID))
      }
    })
  }
  
  // 从 Table 结构提取
  if (themeData.Table && Array.isArray(themeData.Table)) {
    themeData.Table.forEach(item => {
      // Level1
      if (item.Level1?.Stocks) {
        item.Level1.Stocks.forEach(stock => {
          if (stock.StockID) {
            codes.add(normalizeCode(stock.StockID))
          }
        })
      }
      
      // Level2
      if (item.Level2) {
        item.Level2.forEach(l2 => {
          if (l2.Stocks) {
            l2.Stocks.forEach(stock => {
              if (stock.StockID) {
                codes.add(normalizeCode(stock.StockID))
              }
            })
          }
        })
      }
    })
  }
  
  return Array.from(codes)
}

// ========== 构建映射数据 ==========
async function buildMapping(themes) {
  logger.info('开始构建题材映射...')
  
  const mapping = {
    version: '1.0.0',
    lastUpdate: new Date().toISOString().split('T')[0],
    totalThemes: themes.length,
    themes: []
  }
  
  const stockSet = new Set()
  let successCount = 0
  let failCount = 0
  
  // 分批处理
  for (let i = 0; i < themes.length; i += CONFIG.BATCH_SIZE) {
    const batch = themes.slice(i, i + CONFIG.BATCH_SIZE)
    const batchIds = batch.map(t => t.id)
    
    logger.info(`处理批次 ${i + 1}-${Math.min(i + CONFIG.BATCH_SIZE, themes.length)}/${themes.length}`)
    
    const results = await fetchThemesBatch(batchIds)
    
    results.forEach((result, index) => {
      if (result.success && result.data) {
        const theme = batch[index]
        const stockCodes = extractStockCodes(result.data)
        
        // 添加到股票集合
        stockCodes.forEach(code => stockSet.add(code))
        
        mapping.themes.push({
          id: theme.id,
          name: theme.name,
          stocks: stockCodes
        })
        
        successCount++
      } else {
        // 失败时使用旧数据？这里先跳过
        logger.warn(`题材 ${batch[index]?.id} 获取失败`)
        failCount++
      }
    })
    
    // 批次间延迟
    if (i + CONFIG.BATCH_SIZE < themes.length) {
      await delay(CONFIG.BATCH_DELAY)
    }
  }
  
  logger.success(`处理完成: 成功 ${successCount}, 失败 ${failCount}, 共 ${stockSet.size} 只股票`)
  
  return mapping
}

// ========== 保存文件 ==========
function saveMapping(mapping) {
  logger.info(`保存到文件: ${CONFIG.OUTPUT_PATH}`)
  
  // 确保目录存在
  const dirname = path.dirname(CONFIG.OUTPUT_PATH)
  if (!fs.existsSync(dirname)) {
    fs.mkdirSync(dirname, { recursive: true })
  }
  
  // 生成 JSON 字符串
  const jsonString = CONFIG.MINIFY 
    ? JSON.stringify(mapping)
    : JSON.stringify(mapping, null, 2)
  
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
  console.log(' 题材基础映射更新脚本 v1.0.0')
  console.log('='.repeat(60) + '\n')
  
  const startTime = Date.now()
  
  try {
    // 1. 获取题材列表
    let themes = []
    
    // 优先从 API 获取
    try {
      themes = await fetchThemeListFromKPL()
    } catch (error) {
      logger.warn('从 API 获取失败，尝试从本地文件读取旧数据')
      
      // 如果 API 失败，读取旧文件作为基础
      if (fs.existsSync(CONFIG.OUTPUT_PATH)) {
        const oldData = JSON.parse(fs.readFileSync(CONFIG.OUTPUT_PATH, 'utf8'))
        themes = oldData.themes.map(t => ({ id: t.id, name: t.name }))
        logger.info(`从旧文件读取 ${themes.length} 个题材`)
      } else {
        throw new Error('无法获取题材列表')
      }
    }
    
    if (themes.length === 0) {
      throw new Error('没有获取到任何题材')
    }
    
    logger.success(`获取到 ${themes.length} 个题材`)
    
    // 2. 构建映射
    const mapping = await buildMapping(themes)
    
    // 3. 保存文件
    saveMapping(mapping)
    
    // 4. 输出统计
    const duration = ((Date.now() - startTime) / 1000).toFixed(2)
    console.log('\n' + '='.repeat(60))
    console.log(' 更新完成！')
    console.log('='.repeat(60))
    console.log(` 📊 题材数量: ${mapping.totalThemes}`)
    console.log(` 📈 股票数量: ${mapping.themes.reduce((sum, t) => sum + t.stocks.length, 0)}`)
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