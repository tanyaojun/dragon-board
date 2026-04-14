// 从 API 加载所有题材
async function loadAllThemesFromAPI() {
  console.log('🚀 开始从 API 加载所有题材...')
  
  const state = sectorAnalyzer.debug.getState()
  const themeList = state.themeList
  
  console.log('总题材数:', themeList.length)
  
  let success = 0
  let totalMappings = 0
  
  for (let i = 0; i < themeList.length; i++) {
    const theme = themeList[i]
    console.log(`[${i+1}/${themeList.length}] 加载: ${theme.name}`)
    
    try {
      // 直接调用 getThemeDetail，它会触发 updateStockMapping
      const detail = await sectorAnalyzer.getThemeDetail(theme.name)
      
      if (detail) {
        success++
        totalMappings += detail.stocks?.length || 0
      }
      
      // 每10个题材同步一次
      if (i % 10 === 0) {
        sectorAnalyzer.syncThemesToStocks()
        console.log(`中间同步: 当前有题材股票数 ${dataLayer.getStocks().filter(s => s.themes?.length > 0).length}`)
      }
    } catch (e) {
      console.warn(`加载失败: ${theme.name}`, e.message)
    }
  }
  
  // 最后同步一次
  const updated = sectorAnalyzer.syncThemesToStocks()
  
  console.log(`✅ 加载完成: 成功 ${success}/${themeList.length} 个题材`)
  console.log(`📊 总股票-题材映射数: ${totalMappings}`)
  
  // 最终统计
  const stocks = dataLayer.getStocks()
  const withThemes = stocks.filter(s => s.themes?.length > 0)
  console.log('最终有题材的股票数:', withThemes.length)
  console.log('覆盖率:', ((withThemes.length / stocks.length) * 100).toFixed(2) + '%')
  
  return { success, totalMappings }
}

// 执行（会耗时较长，建议分批执行）
loadAllThemesFromAPI()