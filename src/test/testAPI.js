const axios = require('axios');

async function testTDX() {
  console.log('🔍 测试 TDX 接口...\n');
  
  const payload = [{ listType: '0', cycle: '0' }];
  
  // 测试1：直接访问
  try {
    console.log('1️⃣ 直接访问原始接口:');
    const start = Date.now();
    const directRes = await axios.post(
      'https://pul.tdx.com.cn/TQLEX?Entry=JNLPSE.hotStockList&RI=',
      payload,
      { headers: { 'Content-Type': 'application/json' }, timeout: 5000 }
    );
    console.log(`   ✅ 成功 (${Date.now() - start}ms)`);
    console.log('   数据预览:', JSON.stringify(directRes.data).slice(0, 200));
  } catch (error) {
    console.log(`   ❌ 失败: ${error.message}`);
    if (error.response) {
      console.log(`   状态码: ${error.response.status}`);
    }
  }
  
  // 测试2：通过代理
  try {
    console.log('\n2️⃣ 通过代理访问:');
    const start = Date.now();
    const proxyRes = await axios.post(
      'http://localhost:3000/api/tdx/hot',
      payload,
      { timeout: 5000 }
    );
    console.log(`   ✅ 成功 (${Date.now() - start}ms)`);
    console.log('   数据预览:', JSON.stringify(proxyRes.data).slice(0, 200));
  } catch (error) {
    console.log(`   ❌ 失败: ${error.message}`);
    if (error.response) {
      console.log(`   状态码: ${error.response.status}`);
      console.log('   错误信息:', error.response.data);
    }
  }
}

testTDX();