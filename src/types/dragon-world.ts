// src/types/dragon-world.ts
// 龙头看板 · 东方龙族世界艺术化类型
// 注：此文件仅添加艺术化包装，不替代现有类型

import type { MarketPhase } from './core'
import type { LeaderLevelType, LeaderInfo } from './dragon'
import { 
  MARKET_PHASES, 
  LEADER_LEVELS, 
  BREATH_FACTORS_META,
  THEME_FACTORS_META,
  AppEvents 
} from './config'

// ========== 1. 龙族法器映射 ==========
// 将现有功能映射到龙族法器
export const DragonArtifactMap = {
  // 核心导航
  market: { 
    id: 'market', 
    name: '龙吟九州', 
    icon: '🌍🐉', 
    clan: 'candle',
    tooltip: '纵观全局，龙吟天下',
    element: '光'
  },
  dragon: { 
    id: 'dragon', 
    name: '潜龙在渊', 
    icon: '🐲⬆️', 
    clan: 'response',
    tooltip: '发掘潜龙，待时而动',
    element: '风'
  },
  emotion: { 
    id: 'emotion', 
    name: '龙息吐纳', 
    icon: '🔥🌬️', 
    clan: 'kui',
    tooltip: '感知情绪，如龙呼吸',
    element: '雷'
  },
  sector: { 
    id: 'sector', 
    name: '九龙夺嫡', 
    icon: '👑⚔️', 
    clan: 'pan',
    tooltip: '群龙争鼎，题材争锋',
    element: '土'
  },
  algorithm: { 
    id: 'algorithm', 
    name: '龙脉推演', 
    icon: '🧠⚙️', 
    clan: 'azure',
    tooltip: '推演龙脉，预知未来',
    element: '木'
  },
  
  // 工具栏
  breath: { 
    id: 'breath', 
    name: '龙息感知', 
    icon: '🌫️🔥', 
    clan: 'kui',
    tooltip: '感知市场呼吸，把握情绪脉搏',
    element: '雷'
  },
  trend: { 
    id: 'trend', 
    name: '龙脉走势', 
    icon: '📈🗺️', 
    clan: 'azure',
    tooltip: '追踪龙脉，预判趋势',
    element: '木'
  },
  favorite: { 
    id: 'favorite', 
    name: '龙珠收藏', 
    icon: '💎⭐', 
    clan: 'flood',
    tooltip: '如龙护珠，珍藏心仪个股',
    element: '水'
  },
  monitor: { 
    id: 'monitor', 
    name: '龙宫巡查', 
    icon: '🏯👀', 
    clan: 'chi',
    tooltip: '巡查龙宫，系统健康',
    element: '玉'
  },
  refresh: {
    id: 'refresh',
    name: '龙息刷新',
    icon: '↻🌀',
    clan: 'candle',
    tooltip: '如龙吐息，吐故纳新',
    element: '光'
  }
} as const

export type DragonArtifact = keyof typeof DragonArtifactMap

// ========== 2. 龙族部属 ==========
export const DragonClanMap = {
  candle: { 
    id: 'candle', 
    name: '烛龙', 
    domain: '时间', 
    element: '光', 
    symbol: '🕯️',
    color: '#FFD700',
    desc: '掌时间之龙，睁眼为昼，闭眼为夜'
  },
  response: { 
    id: 'response', 
    name: '应龙', 
    domain: '腾飞', 
    element: '风', 
    symbol: '🪶',
    color: '#3498db',
    desc: '掌腾飞之龙，有翼能飞，主升势'
  },
  kui: { 
    id: 'kui', 
    name: '夔龙', 
    domain: '雷声', 
    element: '雷', 
    symbol: '⚡',
    color: '#f39c12',
    desc: '掌雷声之龙，声如雷，主情绪'
  },
  pan: { 
    id: 'pan', 
    name: '蟠龙', 
    domain: '盘踞', 
    element: '土', 
    symbol: '⛰️',
    color: '#27ae60',
    desc: '掌盘踞之龙，无升天之功，主题材'
  },
  azure: { 
    id: 'azure', 
    name: '青龙', 
    domain: '东方', 
    element: '木', 
    symbol: '🌳',
    color: '#2ecc71',
    desc: '掌东方之龙，四象之首，主算法'
  },
  fire: { 
    id: 'fire', 
    name: '火龙', 
    domain: '炽热', 
    element: '火', 
    symbol: '🔥',
    color: '#e74c3c',
    desc: '掌炽热之龙，主预警风险'
  },
  flood: { 
    id: 'flood', 
    name: '蛟龙', 
    domain: '蜕变', 
    element: '水', 
    symbol: '💧',
    color: '#1abc9c',
    desc: '掌蜕变之龙，能发洪水，主自选'
  },
  chi: { 
    id: 'chi', 
    name: '螭龙', 
    domain: '辅助', 
    element: '玉', 
    symbol: '💎',
    color: '#9b59b6',
    desc: '掌辅助之龙，无角，主监控'
  },
  qiu: { 
    id: 'qiu', 
    name: '囚牛', 
    domain: '音律', 
    element: '音', 
    symbol: '🎵',
    color: '#e67e22',
    desc: '掌音律之龙，喜音乐，主设置'
  }
} as const

export type DragonClan = keyof typeof DragonClanMap

// ========== 3. 龙族品级（包装现有龙头级别）==========
export const DragonRankMap = {
  [LEADER_LEVELS.TOTAL.name]: { 
    rank: 'true-dragon', 
    name: '真龙', 
    icon: '👑🐉',
    color: '#FFD700',
    description: '九五之尊，万龙之首',
    chapter: '乾卦·九五'
  },
  [LEADER_LEVELS.CONTINUOUS.name]: { 
    rank: 'soaring-dragon', 
    name: '飞龙', 
    icon: '📈🐲',
    color: '#e74c3c',
    description: '飞龙在天，势不可挡',
    chapter: '乾卦·九五'
  },
  [LEADER_LEVELS.SECTOR.name]: { 
    rank: 'territory-dragon', 
    name: '盘龙', 
    icon: '🏆🐉',
    color: '#3498db',
    description: '一方霸主，割据为王',
    chapter: '坤卦·六二'
  },
  [LEADER_LEVELS.MIDDLE.name]: { 
    rank: 'middle-dragon', 
    name: '中军龙', 
    icon: '⚔️🐲',
    color: '#9b59b6',
    description: '中流砥柱，稳如泰山',
    chapter: '师卦'
  },
  [LEADER_LEVELS.EMOTION.name]: { 
    rank: 'emotion-dragon', 
    name: '情绪龙', 
    icon: '🔥🐉',
    color: '#f39c12',
    description: '乘势而起，随波逐流',
    chapter: '随卦'
  },
  'potential': {
    rank: 'dive-dragon',
    name: '潜龙',
    icon: '🌊🐲',
    color: '#7f8c8d',
    description: '潜龙勿用，阳气潜藏',
    chapter: '乾卦·初九'
  },
  'normal': {
    rank: 'dragon-cub',
    name: '龙子',
    icon: '🐲',
    color: '#95a5a6',
    description: '龙子龙孙，待时而动',
    chapter: '屯卦'
  }
} as const

export type DragonRank = typeof DragonRankMap[keyof typeof DragonRankMap]['rank']

// ========== 4. 龙息阶段（包装现有市场阶段）==========
export const DragonBreathMap: Record<string, { 
  phase: string; 
  name: string; 
  icon: string;
  color: string;
  description: string;
  suggestion: string;
}> = {
  [MARKET_PHASES.ICE.name]: {
    phase: 'dragon-sleep',
    name: '龙眠期',
    icon: '😴🐉',
    color: '#7f8c8d',
    description: '神龙沉睡，万物寂静，市场冰点',
    suggestion: '潜龙勿用，空仓观望'
  },
  [MARKET_PHASES.START.name]: {
    phase: 'dragon-wake',
    name: '龙醒期',
    icon: '👀🐲',
    color: '#3498db',
    description: '潜龙初醒，蠢蠢欲动，情绪回暖',
    suggestion: '见龙在田，轻仓试错'
  },
  [MARKET_PHASES.FERMENT.name]: {
    phase: 'dragon-breath',
    name: '龙息期',
    icon: '🌫️🔥',
    color: '#f39c12',
    description: '龙息吐纳，气运流转，题材发酵',
    suggestion: '终日乾乾，紧跟主线'
  },
  [MARKET_PHASES.CLIMAX.name]: {
    phase: 'dragon-roar',
    name: '龙吟期',
    icon: '🗣️🐉',
    color: '#e74c3c',
    description: '龙吟九天，威震四方，情绪高潮',
    suggestion: '飞龙在天，持股为主'
  },
  [MARKET_PHASES.RETREAT.name]: {
    phase: 'dragon-hide',
    name: '龙隐期',
    icon: '🌫️🐲',
    color: '#9b59b6',
    description: '神龙见首，藏形隐迹，情绪退潮',
    suggestion: '亢龙有悔，减仓防守'
  },
} as const

export type DragonBreathPhase = typeof DragonBreathMap[keyof typeof DragonBreathMap]['phase']

// ========== 5. 龙族气象（状态栏数据）==========
export interface DragonWeather {
  // 龙息时效（数据新鲜度）
  breathFreshness: {
    status: 'fresh' | 'aging' | 'stale';
    lastUpdate: Date;
    ageSeconds: number;
    icon: '🌬️✨' | '🌬️' | '🌫️';
    message: string;
  };
  
  // 龙脉连通（WebSocket状态）
  veinStatus: {
    connected: boolean;
    type: 'websocket' | 'http' | 'mock';
    latency: number;
    icon: '🔗🐉' | '⚠️🔗' | '🔌';
    message: string;
  };
  
  // 龙子龙孙（股票统计）
  progenyCount: {
    total: number;
    trueDragons: number;      // 总龙头
    soaringDragons: number;    // 飞龙（连板龙头）
    territoryDragons: number;  // 盘龙（板块龙头）
    middleDragons: number;     // 中军龙
    emotionDragons: number;    // 情绪龙
    diveDragons: number;       // 潜龙
    message: string;
  };
  
  // 龙宫时辰（交易时间）
  palaceTime: {
    current: Date;
    period: 'trading' | 'pre-trading' | 'post-trading' | 'closed';
    nextEvent?: string;
    message: string;
  };
}

// ========== 6. 龙族箴言库 ==========
export const DragonWisdom = {
  success: [
    { text: '✨ 真龙现身，机缘已至', chapter: '乾卦·九五', clan: 'response' },
    { text: '🐉 潜龙出渊，一飞冲天', chapter: '乾卦·九二', clan: 'response' },
    { text: '💫 龙气汇聚，财运亨通', chapter: '坤卦·六五', clan: 'pan' },
    { text: '🌟 龙珠到手，气运加身', chapter: '既济卦', clan: 'flood' },
    { text: '🔥 龙息正盛，势不可挡', chapter: '大有卦', clan: 'kui' },
  ],
  warning: [
    { text: '⚠️ 龙息不稳，谨慎行事', chapter: '乾卦·九三', clan: 'kui' },
    { text: '🌪️ 风云变幻，潜龙勿用', chapter: '乾卦·初九', clan: 'candle' },
    { text: '⚡ 龙威难测，注意风险', chapter: '震卦', clan: 'fire' },
    { text: '🌊 惊龙扰海，波动加剧', chapter: '坎卦', clan: 'flood' },
  ],
  error: [
    { text: '❌ 龙脉阻塞，稍后再试', chapter: '蹇卦', clan: 'chi' },
    { text: '🌊 惊龙扰海，系统波动', chapter: '坎卦', clan: 'flood' },
    { text: '🔥 龙怒天威，请重试', chapter: '离卦', clan: 'fire' },
  ],
  info: [
    { text: '📊 龙鳞闪烁，数据更新', chapter: '革卦', clan: 'candle' },
    { text: '🔄 龙息吐纳，刷新完成', chapter: '复卦', clan: 'kui' },
    { text: '🎯 龙眼锁定，目标确认', chapter: '晋卦', clan: 'response' },
    { text: '🏯 龙宫巡查，系统健康', chapter: '泰卦', clan: 'chi' },
  ],
} as const

export interface DragonWisdomItem {
  text: string;
  chapter: string;
  clan?: DragonClan;
}

// ========== 7. 龙族数据增强 ==========
export interface DragonStock extends LeaderInfo {
  dragonRank: DragonRank;
  dragonRankInfo: typeof DragonRankMap[keyof typeof DragonRankMap];
  dragonClans: DragonClan[];
  dragonBreath: number;        // 龙息强度 0-100
  dragonPearl?: boolean;        // 是否被收藏（龙珠）
  dragonWisdom?: string;        // 个股箴言
}

// ========== 8. 工具函数 ==========

/**
 * 获取龙族法器信息
 */
export function getDragonArtifact(id: string) {
  return DragonArtifactMap[id as DragonArtifact] || null
}

/**
 * 获取龙族部属信息
 */
export function getDragonClan(id: DragonClan) {
  return DragonClanMap[id]
}

/**
 * 根据龙头级别获取龙族品级
 */
export function getDragonRank(leaderLevelName: string): typeof DragonRankMap[keyof typeof DragonRankMap] {
  return DragonRankMap[leaderLevelName] || DragonRankMap['normal']
}

/**
 * 根据股票信息获取龙族品级
 */
export function getDragonRankFromStock(stock: LeaderInfo): typeof DragonRankMap[keyof typeof DragonRankMap] {
  if (stock.score >= LEADER_LEVELS.TOTAL.minScore) return DragonRankMap[LEADER_LEVELS.TOTAL.name]
  if (stock.score >= LEADER_LEVELS.CONTINUOUS.minScore) return DragonRankMap[LEADER_LEVELS.CONTINUOUS.name]
  if (stock.score >= LEADER_LEVELS.SECTOR.minScore) return DragonRankMap[LEADER_LEVELS.SECTOR.name]
  if (stock.score >= LEADER_LEVELS.MIDDLE.minScore) return DragonRankMap[LEADER_LEVELS.MIDDLE.name]
  if (stock.score >= LEADER_LEVELS.EMOTION.minScore) return DragonRankMap[LEADER_LEVELS.EMOTION.name]
  if (stock.score >= 40) return DragonRankMap['potential']
  return DragonRankMap['normal']
}

/**
 * 获取龙息阶段信息
 */
export function getDragonBreathPhase(marketPhaseName: string): typeof DragonBreathMap[keyof typeof DragonBreathMap] {
  return DragonBreathMap[marketPhaseName] || DragonBreathMap[MARKET_PHASES.FERMENT.name]
}

/**
 * 获取随机龙族箴言
 */
export function getRandomWisdom(type: keyof typeof DragonWisdom): DragonWisdomItem {
  const wisdoms = DragonWisdom[type]
  return wisdoms[Math.floor(Math.random() * wisdoms.length)]
}

/**
 * 获取龙族气象消息
 */
export function getDragonWeatherMessage(weather: Partial<DragonWeather>): string {
  const parts = []
  
  if (weather.breathFreshness) {
    parts.push(weather.breathFreshness.message)
  }
  
  if (weather.veinStatus) {
    parts.push(weather.veinStatus.message)
  }
  
  if (weather.progenyCount) {
    parts.push(weather.progenyCount.message)
  }
  
  if (weather.palaceTime) {
    parts.push(weather.palaceTime.message)
  }
  
  return parts.join(' · ')
}

/**
 * 格式化龙族数量显示
 */
export function formatDragonCount(count: number, unit: string = '只'): string {
  if (count >= 10000) return `${(count / 10000).toFixed(2)}万${unit}`
  if (count >= 1000) return `${(count / 1000).toFixed(1)}千${unit}`
  return `${count}${unit}`
}

// ========== 9. 导出龙族事件 ==========
export const DragonEvents = {
  WEATHER_UPDATED: 'dragon:weather-updated',
  WISDOM_SPOKEN: 'dragon:wisdom-spoken',
  ARTIFACT_ACTIVATED: 'dragon:artifact-activated',
  DRAGON_RANK_CHANGED: 'dragon:rank-changed',
  BREATH_PHASE_CHANGED: 'dragon:breath-phase-changed',
} as const

// ========== 10. 挂载到 window（开发调试用）==========
if (typeof window !== 'undefined') {
  ;(window as any).DragonWorld = {
    artifacts: DragonArtifactMap,
    clans: DragonClanMap,
    ranks: DragonRankMap,
    breaths: DragonBreathMap,
    wisdom: DragonWisdom,
    getRandomWisdom,
    getDragonRank,
    getDragonBreathPhase
  }
}
