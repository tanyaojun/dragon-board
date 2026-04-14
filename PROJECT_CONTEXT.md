# Dragon Board 项目说明文档

## 1. 项目概述

Dragon Board 是一个高级的股票市场分析工具，旨在为专业投资者和分析师提供一个强大、实时、可定制的数据监控与决策支持平台。它通过聚合来自多个（八个）主流财经平台的热榜数据，结合先进的算法分析，帮助用户识别市场龙头、追踪题材热点、分析市场情绪，并最终发现潜在的投资机会。

该项目前端采用 Vue 3 和 Vite 构建，具有现代化的 UI 和高性能的渲染。其核心架构围绕一个响应式的数据流展开，从数据加载、合并、计算、存储，到多维度分析、策略优化，再到最终的可视化呈现，形成了一个完整的闭环。

## 2. 技术栈

- **前端框架**: [Vue 3](https://vuejs.org/) (采用 `<script setup>` 语法)
- **构建工具**: [Vite](https://vitejs.dev/)
- **状态管理**: [Pinia](https://pinia.vuejs.org/)
- **路由**: [Vue Router](https://router.vuejs.org/)
- **UI 组件**:
  - **表格**: `@visactor/vtable` - 一个高性能的表格组件库。
  - **图表**: `ECharts` - 用于数据可视化。
  - **自定义组件**: 项目包含大量自定义的 Vue 组件，用于构建各种面板、控件和视图。
- **语言**: [TypeScript](https://www.typescriptlang.org/)
- **核心依赖**:
  - `lodash-es`: 提供实用的工具函数。
  - `fuse.js`: 用于模糊搜索。
  - `pinyin`: 用于汉字转拼音，增强搜索功能。
- **代码风格与规范**:
  - `ESLint` 和 `Prettier` 用于代码检查和格式化。
  - `.editorconfig` 保证跨编辑器的编码风格一致。

## 3. 项目结构

```
/
├── public/              # 静态资源
├── scripts/             # Node.js 脚本 (例如: updateThemeMapping.js)
├── src/
│   ├── assets/          # 样式、字体等静态资源
│   ├── components/      # 可复用的 Vue 组件 (公共组件、面板、主题切换等)
│   ├── composables/     # Vue Composition API 的可复用逻辑
│   ├── config/          # 静态配置文件 (例如: 因子定义)
│   ├── constants/       # 全局常量 (例如: 主题定义)
│   ├── data/            # 模拟或静态数据
│   ├── router/          # Vue Router 路由配置
│   ├── services/        # **核心业务逻辑层 (关键)**
│   │   ├── Algorithm/   # 算法管理与配置
│   │   ├── apiService.ts # API 请求服务
│   │   ├── adapters.ts  # 各平台数据适配器
│   │   ├── dataLoader.ts # 数据加载与编排
│   │   ├── DataLayer.ts  # 中心化数据存储层
│   │   ├── ...Analyzer.ts # 各种分析器 (龙头、情绪、板块等)
│   │   └── ...Manager.ts # 管理器 (刷新、缓存、股票代码等)
│   ├── stores/          # Pinia 状态管理模块
│   ├── themes/          # 主题相关的样式和定义
│   ├── types/           # TypeScript 类型定义
│   │── utils/           # 通用工具函数 (事件、错误处理等)
│   ├── views/           # 页面级组件
│   ├── App.vue          # 根组件
│   └── main.ts          # 应用入口文件
├── package.json         # 项目依赖与脚本
├── vite.config.ts       # Vite 配置文件
└── tsconfig.json        # TypeScript 配置文件
```

## 4. 核心架构与数据流

项目采用分层架构，数据流清晰，自顶向下分别是 UI 层、调度层、分析层和数据层。

![架构图](https://user-images.githubusercontent.com/36199763/223933335-13158513-a423-432c-9e1a-8d30a6f130a0.png)
*(这是一个简化的概念图，实际依赖关系更复杂)*

### 4.1. 数据层 (Data Layer)

- **`DataLayer.ts`**: 这是整个应用的心脏，作为一个**中心化的内存数据库 (In-Memory DB)**。它存储了从各个数据源获取并处理后的所有状态，包括原始数据、合并后的股票列表、实时行情、题材信息、分析结果等。所有其他服务都依赖于 `DataLayer` 来获取和更新数据。
- **`LRUCache.ts`**: 实现了一个 LRU (最近最少使用) 缓存机制，用于缓存 API 请求、股票数据等，以提高性能和减少不必要的网络请求。
- **IndexedDB 集成**: `DataLayer` 能够将历史数据快照持久化到浏览器的 IndexedDB 中，为历史回测和趋势分析提供数据基础。

### 4.2. 分析层 (Analysis Layer)

这是项目的“大脑”，包含一系列专门的分析服务，它们从 `DataLayer` 获取数据，进行计算和分析，然后将结果写回 `DataLayer`。

- **`dataLoader.ts`**: 负责从八个不同的外部 API (通过 `apiService` 和 `adapters.ts`) 获取热榜数据，获取实时行情，然后进行数据清洗、合并、排序，并计算出综合排名 (`compRank`)。它是所有分析的起点。
- **`RankTrendAnalyzer.ts`**: 分析历史排名快照，计算移动平均线 (MA)、MACD 等技术指标，并基于排名的动量和一致性生成交易信号 (`buy`, `sell`, `hold`)。
- **`ParameterOptimizer.ts`**: 提供策略回测和参数优化工具。它可以使用网格搜索、贝叶斯优化或 AI 引导的方式，对 `RankTrendAnalyzer` 中的策略参数进行优化，以找到在历史数据上表现最佳的参数组合。
- **其他分析器**:
  - `DragonAnalyzer`: 识别市场龙头股。
  - `DragonBreathAnalyzer`: 分析市场情绪。
  - `sectorAnalyzer`: 进行题材和板块分析。
  - `ThemeCorrelationAnalyzer`: 分析题材之间的联动关系。

### 4.3. 调度层 (Scheduling Layer)

- **`RefreshCoordinator.ts` / `RefreshManager.ts`**: 负责管理和协调所有数据和分析服务的更新生命周期。它确保各个服务按照正确的依赖顺序执行刷新操作，例如，必须先加载数据 (`dataLoader`)，然后才能进行龙头分析 (`DragonAnalyzer`)。它还管理自动刷新和手动刷新逻辑。

### 4.4. UI 层 (UI Layer)

- **Vue 3 Components**: 负责展示数据和与用户交互。UI 组件通过 Pinia Stores 从数据层获取状态。
- **Pinia Stores (`/stores`)**: 作为 UI 层和数据/服务层之间的桥梁。
  - `useUIStore`: 管理表格的显示状态，如排序、过滤、分页。
  - `useSelectorStore`: 管理全局的股票选中状态。
  - `useConfigStore`: 管理应用的所有配置项。
  - `useFavoriteStore`: 管理用户的自选股和板块。
  - `useThemeStore`: 管理应用的主题和样式。
- **`App.vue`**: 作为根组件，它负责初始化所有服务、加载配置，并编排所有 UI 组件和面板的显示逻辑。

## 5. 关键服务模块详解

- **`dataLoader.ts`**: 核心数据入口。`loadAllPlatforms()` 方法并行获取所有平台的数据，`loadStockDetails()` 批量获取股票详情，`mergeData()` 将所有信息整合成统一的数据结构存入 `DataLayer`。
- **`DataLayer.ts`**: 单例模式，全局唯一。通过 `getStocks()`、`getStock()` 等方法提供数据访问接口，通过 `updateStocks()` 等方法更新数据。
- **`RankTrendAnalyzer.ts`**: 核心算法模块。`calculateSignals()` 方法是其关键，它遍历历史快照，计算排名百分位，然后应用技术分析方法生成信号。
- **`ParameterOptimizer.ts`**: 回测引擎。`gridSearch()` 和 `bayesianOptimization()` 等方法通过模拟历史交易来评估不同参数集的表现，并找出最优解。
- **`RefreshManager.ts`**: 定时任务管理器。`init()` 和 `start()` 方法启动定时器，根据用户配置的策略（积极、均衡、保守）来决定刷新频率和刷新的内容。

## 6. 本地开发与运行

1.  **环境准备**:
    - 确保已安装 [Node.js](https://nodejs.org/) (建议 v18 或更高版本)。
    - 推荐使用 `pnpm` 作为包管理器以获得更好的性能。

2.  **安装依赖**:
    ```bash
    # 使用 pnpm (推荐)
    pnpm install

    # 或者使用 npm
    npm install
    ```

3.  **启动开发服务器**:
    ```bash
    pnpm dev
    ```
    此命令会启动 Vite 开发服务器，默认地址为 `http://localhost:5173`。项目支持热模块更换 (HMR)，修改代码后页面会自动更新。

4.  **构建生产版本**:
    ```bash
    pnpm build
    ```
    构建产物将输出到 `dist` 目录。

5.  **预览生产版本**:
    ```bash
    pnpm preview
    ```
    此命令会在本地启动一个静态服务器来预览 `dist` 目录中的内容。

6.  **其他脚本**:
    - `pnpm run update-themes`: 运行 `scripts/updateThemeMapping.js` 脚本，用于更新主题相关的映射文件。
