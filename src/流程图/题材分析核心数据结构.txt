// 1. 题材元数据 (state.themeList)
interface ThemeData {
  id: string;           // 题材ID
  name: string;         // 题材名称
  zsCode: string;       // 指数代码
  aliases: string[];    // 别名列表（用于查重合并）
}

// 2. 题材热度信息 (state.themeInfo)
interface ThemeInfo {
  heatScore: number;           // 热度分数
  heatLevel: '冷'|'温'|'热门';  // 热度等级
  leaders: any[];              // 龙头股列表
  totalLeader: any;            // 总龙头
  history: HeatPoint[];        // 历史热度点
  momentum: number;            // 动量值
  trend: number;               // 趋势值
  acceleration: number;        // 加速度
  lastUpdate: number;          // 最后更新时间
  stats: {                     // 统计数据
    ztCount: number;           // 涨停股数量
    leaderCount: number;       // 龙头股数量
    stockCount: number;        // 成分股数量
    totalContinuousDays: number; // 总连板天数
  };
}

// 3. 映射关系
state.stockThemeMap: Record<string, string[]>  // 股票代码 -> 题材ID列表
state.themeStockMap: Record<string, string[]>  // 题材ID -> 股票代码列表

// 4. 热门题材 (state.hotThemes)
interface HotTheme {
  id: string;
  name: string;
  heatScore: number;
  heatIcon: string;
  heatColor: string;
  heatLevel: string;
  stockCount: number;
  ztCount: number;
  leaderCount: number;
  momentum: number;
  trend: number;
  acceleration: number;
  rank: number;
}

// 5. 轮动信号 (state.sectorRotation)
interface RotationSignal {
  timestamp: number;
  sectors: Array<{
    id: string;
    name: string;
    heatScore: number;
    momentum: number;
    trend: number;
    acceleration: number;
    rotationState: string;  // '强势进攻'|'震荡上行'|'震荡'|'震荡下行'|'弱势退潮'
    rotationIcon: string;
    rotationColor: string;
    changes: string[];
    intensity: number;
  }>;
}