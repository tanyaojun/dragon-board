// 完整的字段映射测试（包含所有字段的原始值）
console.clear()
console.log('========== 完整字段映射测试（包含原始值对比）==========\n')

async function testFullFieldMapping() {
  console.log('测试时间:', new Date().toLocaleString())
  console.log('='.repeat(120))

  try {
    // 1. 获取原始API数据
    console.log('📡 1. 原始API数据字段值:\n')

    const testCode = '002261' //拓维信息

    const [tencentRes, sinaRes, eastmoneyRes] = await Promise.allSettled([
      apiService.get(`/api/quotes/tencent?codes=${testCode}`, { context: 'test' }),
      apiService.get(`/api/quotes/sina?codes=${testCode}`, { context: 'test' }),
      apiService.get(`/api/quotes/eastmoney?codes=${testCode}`, { context: 'test' }),
    ])

    // 腾讯数据
    console.log('🔵 腾讯API原始值:')
    if (tencentRes.status === 'fulfilled' && tencentRes.value?.data?.diff?.[0]) {
      const t = tencentRes.value.data.diff[0]
      console.log(`   f2  (price)       : ${t.f2}`)
      console.log(`   f3  (change)      : ${t.f3}`)
      console.log(`   f5  (turnover)    : ${t.f5}`)
      console.log(`   f6  (volume)      : ${t.f6}`)
      console.log(`   f8  (turnoverRate): ${t.f8}`)
      console.log(`   f9  (pe)          : ${t.f9}`)
      console.log(`   f14 (name)        : ${t.f14}`)
      console.log(`   f20 (totalMV)     : ${t.f20}`)
      console.log(`   f21 (cirMV)       : ${t.f21}`)
      console.log(`   f23 (pb)          : ${t.f23}`)
      console.log(`   f62 (zlje)        : ${t.f62}`)
      console.log(`   f184 (zljzb)      : ${t.f184}`)
      console.log(`   f66 (cddje)       : ${t.f66}`)
      console.log(`   f69 (cddjzb)      : ${t.f69}`)
    }

    // 新浪数据
    console.log('\n🔴 新浪API原始值:')
    if (sinaRes.status === 'fulfilled' && sinaRes.value?.data?.diff?.[0]) {
      const s = sinaRes.value.data.diff[0]
      console.log(`   f2  (price)       : ${s.f2}`)
      console.log(`   f3  (change)      : ${s.f3}`)
      console.log(`   f5  (turnover)    : ${s.f5}`)
      console.log(`   f6  (volume)      : ${s.f6}`)
      console.log(`   f8  (turnoverRate): ${s.f8}`)
      console.log(`   f9  (pe)          : ${s.f9}`)
      console.log(`   f14 (name)        : ${s.f14}`)
      console.log(`   f20 (totalMV)     : ${s.f20}`)
      console.log(`   f21 (cirMV)       : ${s.f21}`)
      console.log(`   f23 (pb)          : ${s.f23}`)
      console.log(`   f62 (zlje)        : ${s.f62}`)
      console.log(`   f184 (zljzb)      : ${s.f184}`)
      console.log(`   f66 (cddje)       : ${s.f66}`)
      console.log(`   f69 (cddjzb)      : ${s.f69}`)
    }

    // 东财数据
    console.log('\n🟢 东财API原始值:')
    if (eastmoneyRes.status === 'fulfilled' && eastmoneyRes.value?.data?.diff?.[0]) {
      const e = eastmoneyRes.value.data.diff[0]
      console.log(`   f2  (price)       : ${e.f2}`)
      console.log(`   f3  (change)      : ${e.f3}`)
      console.log(`   f5  (turnover)    : ${e.f5}`)
      console.log(`   f6  (volume)      : ${e.f6}`)
      console.log(`   f8  (turnoverRate): ${e.f8}`)
      console.log(`   f9  (pe)          : ${e.f9}`)
      console.log(`   f14 (name)        : ${e.f14}`)
      console.log(`   f20 (totalMV)     : ${e.f20}`)
      console.log(`   f21 (cirMV)       : ${e.f21}`)
      console.log(`   f23 (pb)          : ${e.f23}`)
      console.log(`   f62 (zlje)        : ${e.f62}`)
      console.log(`   f184 (zljzb)      : ${e.f184}`)
      console.log(`   f66 (cddje)       : ${e.f66}`)
      console.log(`   f69 (cddjzb)      : ${e.f69}`)
    }

    // 2. 获取合并后的数据
    console.log('\n📊 2. 合并后数据:')
    const merged = await quoteService.getQuote(testCode, true)

    // 3. 详细对比每个字段
    console.log('\n🔍 3. 字段映射详细对比:')
    console.log('='.repeat(120))
    console.log(
      '字段名        | 合并后值          | 腾讯原始值        | 新浪原始值        | 东财原始值        | 实际来源',
    )
    console.log('-'.repeat(120))

    const fields = [
      { name: 'price', tencent: 'f2', sina: 'f2', eastmoney: 'f2' },
      { name: 'change', tencent: 'f3', sina: 'f3', eastmoney: 'f3' },
      { name: 'volume', tencent: 'f6', sina: 'f6', eastmoney: 'f6' },
      { name: 'turnover', tencent: 'f5', sina: 'f5', eastmoney: 'f5' },
      { name: 'name', tencent: 'f14', sina: 'f14', eastmoney: 'f14' },
      { name: 'turnoverRate', tencent: 'f8', sina: 'f8', eastmoney: 'f8' },
      { name: 'pe', tencent: 'f9', sina: 'f9', eastmoney: 'f9' },
      { name: 'totalMV', tencent: 'f20', sina: 'f20', eastmoney: 'f20' },
      { name: 'cirMV', tencent: 'f21', sina: 'f21', eastmoney: 'f21' },
      { name: 'pb', tencent: 'f23', sina: 'f23', eastmoney: 'f23' },
      { name: 'zlje', tencent: 'f62', sina: 'f62', eastmoney: 'f62' },
      { name: 'zljzb', tencent: 'f184', sina: 'f184', eastmoney: 'f184' },
      { name: 'cddje', tencent: 'f66', sina: 'f66', eastmoney: 'f66' },
      { name: 'cddjzb', tencent: 'f69', sina: 'f69', eastmoney: 'f69' },
    ]

    const tData = tencentRes.status === 'fulfilled' ? tencentRes.value?.data?.diff?.[0] : null
    const sData = sinaRes.status === 'fulfilled' ? sinaRes.value?.data?.diff?.[0] : null
    const eData = eastmoneyRes.status === 'fulfilled' ? eastmoneyRes.value?.data?.diff?.[0] : null

    fields.forEach((field) => {
      const mergedValue = merged?.[field.name]
      const tencentValue = tData?.[field.tencent]
      const sinaValue = sData?.[field.sina]
      const eastmoneyValue = eData?.[field.eastmoney]

      // 判断实际来源
      let source = '未知'
      if (mergedValue === tencentValue) source = '腾讯'
      else if (mergedValue === sinaValue) source = '新浪'
      else if (mergedValue === eastmoneyValue) source = '东财'
      else if (mergedValue === 0 && eastmoneyValue === 0) source = '默认0'

      // 格式化输出
      console.log(
        `${field.name.padEnd(12)} | ` +
          `${String(mergedValue).padEnd(16)} | ` +
          `${String(tencentValue ?? '-').padEnd(16)} | ` +
          `${String(sinaValue ?? '-').padEnd(16)} | ` +
          `${String(eastmoneyValue ?? '-').padEnd(16)} | ` +
          `${source}`,
      )
    })

    // 4. 统计不同来源的字段数量
    console.log('\n📊 4. 来源统计:')
    console.log('-'.repeat(120))

    let tencentCount = 0,
      sinaCount = 0,
      eastmoneyCount = 0,
      defaultCount = 0

    fields.forEach((field) => {
      const mergedValue = merged?.[field.name]
      const tencentValue = tData?.[field.tencent]
      const sinaValue = sData?.[field.sina]
      const eastmoneyValue = eData?.[field.eastmoney]

      if (mergedValue === tencentValue) tencentCount++
      else if (mergedValue === sinaValue) sinaCount++
      else if (mergedValue === eastmoneyValue) eastmoneyCount++
      else if (mergedValue === 0) defaultCount++
    })

    console.log(`   腾讯来源字段: ${tencentCount}个`)
    console.log(`   新浪来源字段: ${sinaCount}个`)
    console.log(`   东财来源字段: ${eastmoneyCount}个`)
    console.log(`   默认0字段: ${defaultCount}个`)
    console.log(`   总字段数: ${fields.length}个`)

    // 5. 验证数据源标记
    console.log('\n🔖 5. 数据源标记:')
    console.log('-'.repeat(120))
    console.log(`   sources: [${merged?.sources?.join(', ')}]`)
    console.log(`   confidence: ${merged?.confidence}%`)

    return { merged, tData, sData, eData }
  } catch (error) {
    console.error('测试失败:', error)
  }
}

// 执行测试
testFullFieldMapping().then(() => {
  console.log('\n✅ 完整字段映射测试完成')
})
