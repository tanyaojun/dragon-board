# RankTrendAnalyzer 验证工具

这个目录包含了验证 RankTrendAnalyzer 4个信号计算逻辑的工具。

## 验证内容

验证 RankTrendAnalyzer 的4个核心信号：

1. **MACD信号** - 技术指标确认信号
2. **方向一致性信号** - 排名趋势方向信号
3. **零线交叉信号** - 动量零线交叉信号
4. **动量加速度信号** - 排名变化加速度信号

## 可用验证函数

### 1. `validateRankTrendAnalyzerConsole()` (推荐)

- 文件：`consoleValidator.js`
- 类型：纯JavaScript，可直接在控制台中运行
- 功能：完整的4个信号验证，包含详细统计和错误检查

**使用方法：**

```javascript
// 在浏览器控制台中输入
validateRankTrendAnalyzerConsole()
```

### 2. `simpleRankTrendAnalyzerTest()`

- 文件：`simpleTest.js`
- 类型：纯JavaScript，简单测试
- 功能：基本的功能测试，输出前5个股票的信号

**使用方法：**

```javascript
// 在浏览器控制台中输入
simpleRankTrendAnalyzerTest()
```

### 3. `validateRankTrendAnalyzer()` (TypeScript版本)

- 文件：`validateRankTrendAnalyzer.ts`
- 类型：TypeScript，需要编译
- 功能：完整的TypeScript验证脚本

**注意**：这个函数可能因为加载问题不可用，建议使用前两个。

## 快速开始

### 方法1：直接运行验证函数

1. 打开浏览器开发者工具 (F12)
2. 切换到 Console 标签页
3. 输入以下命令之一：

   ```javascript
   // 推荐：完整验证
   validateRankTrendAnalyzerConsole()

   // 简单测试
   simpleRankTrendAnalyzerTest()
   ```

### 方法2：粘贴代码运行

如果函数未定义，可以直接粘贴以下代码到控制台：

```javascript
// 完整的验证函数代码
async function validateRankTrendAnalyzerConsole() {
  console.log('🧪 开始验证RankTrendAnalyzer的4个信号计算逻辑...')

  // ... 完整的函数代码
  // 可以从 consoleValidator.js 文件中复制
}

// 运行验证
validateRankTrendAnalyzerConsole()
```

## 验证输出示例

成功运行后，您将看到类似以下输出：

```
🧪 开始验证RankTrendAnalyzer的4个信号计算逻辑...
✅ 必要的全局对象存在
📊 当前股票数量: 150
🔍 获取排名趋势分析结果...
✅ 获取到 150 个股票的排名趋势分析结果

📈 信号验证结果：
- MACD信号: 45 个股票 (30.0%)
- 方向一致性信号: 120 个股票 (80.0%)
- 零线交叉信号: 90 个股票 (60.0%)
- 动量加速度信号: 75 个股票 (50.0%)

🔍 前10个股票的详细信号：
1. 002263 大东南
   MACD: none
   方向: buy
   交叉: hold
   加速度: hold
   最终信号: buy (置信度: 75%)

📊 验证总结：
- 总股票数: 150
- 验证耗时: 1200ms
- 发现错误: 0 个

🎉 验证成功！所有信号计算逻辑正常
```

## 错误处理

如果验证发现错误，会输出详细的错误信息，包括：

- 置信度超出范围
- 信号不一致（同时有多个买信号和卖信号）
- 最终信号无效

## 文件说明

- `consoleValidator.js` - 主验证函数，推荐使用
- `simpleTest.js` - 简单测试函数
- `validateRankTrendAnalyzer.ts` - TypeScript版本验证脚本
- `README.md` - 本说明文件

## 注意事项

1. 确保应用已加载完成，`rankTrendAnalyzer` 和 `dataLayer` 全局对象可用
2. 验证需要股票数据，确保数据已加载
3. 验证过程可能需要几秒钟时间，取决于股票数量
4. 如果遇到函数未定义错误，请使用直接粘贴代码的方式
