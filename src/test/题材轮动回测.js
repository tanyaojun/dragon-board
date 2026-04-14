// 直接在浏览器控制台运行这个脚本

async function runStrategyThemeRotation() {
  console.log('=== 策略1：题材强度轮动 ===');
  console.log('加载数据中...');
  
  // 1. 从 IndexedDB 读取所有快照
  const snapshots = await getAllSnapshotsFromDB();
  console.log(`加载了 ${snapshots.length} 天的数据`);
  
  if (snapshots.length < 6) {
    console.log('数据不足，需要至少6天数据');
    return;
  }
  
  // 2. 运行策略
  const results = [];
  
  for (let i = 0; i < snapshots.length - 5; i++) {
    const today = snapshots[i];
    const sellDay = snapshots[i + 5];
    
    // 获取最强板块
    const sectors = today.sectors || [];
    if (sectors.length === 0) continue;
    
    const topSector = sectors[0];
    const sectorName = topSector.name;
    const strength = topSector.strength;
    
    // 找该板块的龙头
    const leaders = today.leaders || [];
    const sectorLeader = leaders.find(l => l.block === sectorName);
    
    if (!sectorLeader) continue;
    
    // 找卖出价
    const sellStock = sellDay.hotlist?.find(s => s.code === sectorLeader.code);
    if (!sellStock) continue;
    
    const buyPrice = sectorLeader.price;
    const sellPrice = sellStock.price;
    const profit = ((sellPrice - buyPrice) / buyPrice * 100).toFixed(2);
    
    results.push({
      date: today.date,
      sector: sectorName,
      strength: strength,
      leader: sectorLeader.name,
      level: sectorLeader.level,
      buyPrice: buyPrice,
      sellPrice: sellPrice,
      profit: profit + '%'
    });
  }
  
  // 3. 显示结果
  console.log('\n=== 最近10笔交易 ===');
  results.slice(-10).forEach(t => {
    console.log(`${t.date} | ${t.sector} | ${t.leader}(${t.level}) | 收益:${t.profit}`);
  });
  
  // 4. 统计
  const profits = results.map(r => parseFloat(r.profit));
  const wins = profits.filter(p => p > 0);
  const losses = profits.filter(p => p < 0);
  
  console.log('\n=== 策略统计 ===');
  console.log(`总交易次数: ${results.length}`);
  console.log(`盈利次数: ${wins.length}`);
  console.log(`亏损次数: ${losses.length}`);
  console.log(`胜率: ${(wins.length / results.length * 100).toFixed(1)}%`);
  console.log(`平均收益: ${(profits.reduce((a,b) => a + b, 0) / profits.length).toFixed(2)}%`);
  console.log(`总收益: ${profits.reduce((a,b) => a + b, 0).toFixed(2)}%`);
  
  return results;
}

// 辅助函数：从 IndexedDB 读取所有快照
async function getAllSnapshotsFromDB() {
  const dbName = 'DragonBoardData';
  const storeName = 'daily_snapshots';
  
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(dbName);
    
    request.onerror = () => reject(request.error);
    request.onsuccess = () => {
      const db = request.result;
      const transaction = db.transaction([storeName], 'readonly');
      const store = transaction.objectStore(storeName);
      const getAllRequest = store.getAll();
      
      getAllRequest.onerror = () => reject(getAllRequest.error);
      getAllRequest.onsuccess = () => {
        const snapshots = getAllRequest.result;
        snapshots.sort((a, b) => a.date.localeCompare(b.date));
        db.close();
        resolve(snapshots);
      };
    };
  });
}

// 运行策略
await runStrategyThemeRotation();