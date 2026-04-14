// 引入 axios (如果没安装，先运行: npm install axios)
import axios from 'axios';

// 1. 配置你的信息
const API_TOKEN = 'ebe0ff3be9e7ffc4635ac975b5c34dfa-c-app'; // <-- 替换成你的真实token
const BASE_URL = 'https://quote.alltick.io/quote-stock-b-api';

// 2. 构建 query 参数对象 (基于你提供的格式)
const queryObject = {
    data: {
        code: "000001.SZ",      // 股票代码，可以换成你需要的，注意带上市场后缀 .SZ 或 .SH
        kline_type: "8",        // 8 可能代表日K线，具体含义需看文档
        kline_timestamp_end: "0", // 0 可能代表最新
        query_kline_num: "1",    // 获取1条数据
        adjust_type: "0"         // 0 可能代表不复权
    }
};

// 3. 将 query 对象转换为 JSON 字符串
const queryString = JSON.stringify(queryObject);

// 4. 构建完整的请求 URL
const url = `${BASE_URL}/kline?token=${API_TOKEN}&query=${encodeURIComponent(queryString)}`;

// 5. 发送请求
async function testAllTick() {
    try {
        console.log('正在请求:', url.replace(API_TOKEN, '***')); // 打印URL（隐藏token）
        
        const response = await axios.get(url, {
            headers: {
                'Accept': 'application/json'
            },
            timeout: 10000 // 10秒超时
        });

        console.log('✅ 请求成功！');
        console.log('返回数据:', JSON.stringify(response.data, null, 2));

    } catch (error) {
        console.error('❌ 请求失败:');
        if (error.response) {
            // 服务器返回了错误状态码
            console.error('状态码:', error.response.status);
            console.error('错误详情:', error.response.data);
        } else if (error.request) {
            console.error('无响应（网络或超时问题）:', error.request);
        } else {
            console.error('请求设置错误:', error.message);
        }
    }
}

// 运行测试
testAllTick();