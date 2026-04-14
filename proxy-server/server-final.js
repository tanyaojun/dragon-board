// D:\dragon-board\proxy-server\server-final.js
import express from 'express';
import cors from 'cors';
import axios from 'axios';
import { wrapper } from 'axios-cookiejar-support';
import { CookieJar } from 'tough-cookie';
import crypto from 'crypto';
import iconv from 'iconv-lite';
import { fileURLToPath } from 'url';
import { dirname } from 'path';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

const app = express();
const PORT = 3000;

const jar = new CookieJar();
const client = wrapper(axios.create({ jar, withCredentials: true, maxRedirects: 5 }));

app.use(cors({ origin: '*', methods: ['GET', 'POST'] }));
app.use(express.json());

app.use((req, res, next) => {
  console.log(`[${new Date().toLocaleTimeString()}] ${req.method} ${req.url}`);
  next();
});

// ========== 健康检查 ==========
app.get('/health', (req, res) => {
  res.json({ status: 'ok', time: new Date().toLocaleString() });
});

// ========== 行情接口（直接使用腾讯财经） ==========
app.get('/api/quotes', async (req, res) => {
  try {
    const { codes } = req.query;
    if (!codes || typeof codes !== 'string') {
      return res.status(400).json({ error: '缺少 codes 参数' });
    }

    const codeList = codes.split(',').filter(code => code && code.length >= 6);

    if (codeList.length === 0) {
      return res.json({ data: { diff: [] } });
    }

    console.log(`[腾讯行情] 请求 ${codeList.length} 只股票`);

    const tencentCodes = codeList.map(code => {
      return code.startsWith('6') ? `sh${code}` : `sz${code}`;
    }).join(',');

    const url = `http://qt.gtimg.cn/q=${tencentCodes}`;
    
    const response = await axios.get(url, {
      timeout: 5000,
      responseType: 'arraybuffer'
    });

    const text = iconv.decode(response.data, 'gbk');
    const lines = text.split('\n');
    const results = [];

    lines.forEach(line => {
      if (!line || !line.includes('~')) return;
      const match = line.match(/v_[^=]+="([^"]+)"/);
      if (!match) return;
      
      const parts = match[1].split('~');
      if (parts.length < 40) return;

      results.push({
        f12: parts[2],
        f14: parts[1],
        f2: parseFloat(parts[3]) || 0,
        f3: parseFloat(parts[32]) || 0,
        f6: (parseFloat(parts[36]) || 0) * 10000,
        f8: parseFloat(parts[38]) || 0,
      });
    });

    console.log(`[腾讯行情] 成功获取 ${results.length} 条数据`);

    res.json({
      rc: 0,
      data: {
        diff: results
      }
    });

  } catch (error) {
    console.error('[腾讯行情错误]', error.message);
    res.status(500).json({
      rc: -1,
      error: error.message,
      data: { diff: [] }
    });
  }
});

// ========== 测试接口 ==========
app.get('/api/test', (req, res) => {
  res.json({
    message: '代理服务器工作正常',
    time: new Date().toLocaleString(),
    apis: ['/api/quotes?codes=000001,600519']
  });
});

// ========== 启动服务器 ==========
app.listen(PORT, () => {
  console.log('\n' + '='.repeat(60));
  console.log('🚀 股票数据代理服务器启动成功！');
  console.log('='.repeat(60));
  console.log(`📍 本地地址: http://localhost:${PORT}`);
  console.log('='.repeat(60));
  console.log('\n📡 可用接口:');
  console.log('   GET  /health                 - 健康检查');
  console.log('   GET  /api/test                - 接口测试');
  console.log('   GET  /api/quotes?codes=...    - 批量行情');
  console.log('='.repeat(60));
});