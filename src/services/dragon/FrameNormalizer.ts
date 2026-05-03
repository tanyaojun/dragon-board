import { dataLayer } from '../../services/DataLayer'
import { FORMAL_SNAPSHOT_READ_POLICY } from '../../services/snapshot/readPolicy'
import { snapshotFacade } from '../../services/snapshot/facade'
import type { SnapshotFrameBundle, SnapshotStockRow } from '../../services/snapshot/types'
import { dragonBreathAnalyzer } from '../../services/DragonBreathAnalyzer'
import type { MergedStock } from '@/types'
import {
  isRankTrendIntradaySnapshotType,
  isRankTrendSnapshotType,
  RANK_TREND_SNAPSHOT_TYPES,
} from '../../types/rankTrendDefaults'
import type { FrameSource, ReviewFrame, ReviewHotStock, ReviewSector } from './types'
import {
  buildHotStockFromMergedStock,
  buildThemeRefs,
  extractSnapshotDate,
  inferBoardHeight,
  normalizeDate,
} from './helpers'

function normalizeHotlistItem(item: SnapshotStockRow | any, rank: number): ReviewHotStock {
  return {
    code: item.code,
    name: item.name || item.code,
    rank: item.rank || rank,
    compRank: item.compRank || item.rank || rank,
    price: item.price || 0,
    change: item.change || 0,
    turnover: item.turnover || 0,
    turnoverRate: item.turnoverRate || 0,
    totalMV: item.totalMV || 0,
    cirMV: item.cirMV || 0,
    zlje: item.zlje || 0,
    volumeRatio: item.volumeRatio || 0,
    leadStatus: item.leadStatus || '',
    leadTimes: item.leadTimes || 0,
    lianbanStr: item.lianbanStr || item.lianban || '',
    popularity: item.popularity || 0,
    popularityChange: item.popularityChange || 0,
    institutionBuy: item.institutionBuy || 0,
    mainBuy: item.mainBuy || 0,
    mainSell: item.mainSell || 0,
    fengdan: item.fengdan || 0,
    maxFengdan: item.maxFengdan || 0,
    firstZtTime: item.firstZtTime || item.first_limit_up_time || '',
    lastZtTime: item.lastZtTime || item.last_limit_up_time || '',
    boardHeight: inferBoardHeight(item),
    highDays: item.highDays || item.continuousDays || 0,
    hotness: item.hotness || 0,
    themes: buildThemeRefs(item),
    isNew: item.isNew || false,
    mainTheme: item.mainTheme,
    themeHeat: item.themeHeat,
    themeLevel: item.themeLevel,
  }
}

function normalizeSectorItem(item: any): ReviewSector {
  return {
    code: item.code,
    name: item.name || item.themeName || item.code,
    strength: item.strength || item.heatScore || item.score || 0,
    change: item.change || 0,
    mainNetInflow: item.mainNetInflow || item.netInflow || 0,
    bigMoney300: item.bigMoney300 || 0,
    institutionBuy: item.institutionBuy || 0,
    volumeRatio: item.volumeRatio || 0,
    ztCount: item.ztCount || 0,
  }
}

function detectSource(type: string | undefined): FrameSource {
  return isRankTrendSnapshotType(type) ? type : 'close'
}

function buildFrameFromBundle(bundle: SnapshotFrameBundle, fallbackDate: string): ReviewFrame {
  const source = detectSource(bundle?.type)
  const snapshotDate = bundle.tradingDate || extractSnapshotDate(bundle?.displayKey || '') || fallbackDate
  const hotlist = Array.isArray(bundle?.hotlist)
    ? bundle.hotlist
        .map((item: SnapshotStockRow, index: number) => normalizeHotlistItem(item, index + 1))
        .sort((left, right) => (left.rank || 999) - (right.rank || 999))
    : []
  const sectors = Array.isArray(bundle?.sectors)
    ? bundle.sectors.map((item: any) => normalizeSectorItem(item))
    : []
  const marketStats = bundle?.marketStats || {}
  const sentiment = bundle?.sentiment || {}

  return {
    id: bundle.snapshotId || `${source}:${bundle?.timestamp || Date.now()}`,
    date: snapshotDate,
    source,
    timestamp: bundle?.timestamp || Date.now(),
    hotlist,
    sectors,
    marketStats: {
      upCount: marketStats.upCount || 0,
      downCount: marketStats.downCount || 0,
      ztCount: marketStats.ztCount || 0,
      dtCount: marketStats.dtCount || 0,
      totalAmo: marketStats.totalAmo || 0,
      zhabanRate: marketStats.zhabanRate || 0,
    },
    sentiment: {
      overall: sentiment.overall || 50,
      phase: sentiment.phase || sentiment.phaseName || 'start',
      phaseName: sentiment.phaseName || sentiment.phase || '启动',
      emotionValue: sentiment.emotionValue || marketStats.emotionValue || 0,
    },
    rawCoverage: {
      hasHotlist: hotlist.length > 0,
      hasSectors: sectors.length > 0,
      hasMarketStats: Boolean(marketStats),
    },
  }
}

function buildCloseFrame(stocks: MergedStock[], date: string, timestamp: number): ReviewFrame {
  // 收盘态是最后一道兜底帧。
  // 盘中快照不全时，后续“收盘门”仍需要一个统一来源来判断谁守住了领导权。
  const sentiment = dragonBreathAnalyzer.getMarketSentiment?.() || {
    overall: 50,
    phase: 'start',
    phaseName: '启动',
  }
  const marketData = dragonBreathAnalyzer.getMarketData?.() || {}
  const hotlist = [...stocks]
    .sort((a, b) => (a.compRank || 999) - (b.compRank || 999))
    .slice(0, 100)
    .map((stock, index) => buildHotStockFromMergedStock(stock, index + 1))
  const sectors = dataLayer.getJxbkBlocksSorted(30).map((item) => normalizeSectorItem(item))

  return {
    id: `close:${date}:${timestamp}`,
    date,
    source: 'close',
    timestamp,
    hotlist,
    sectors,
    marketStats: {
      upCount: marketData.upCount || 0,
      downCount: marketData.downCount || 0,
      ztCount: marketData.ztCount || 0,
      dtCount: marketData.dtCount || 0,
      totalAmo: marketData.totalAmo || 0,
      zhabanRate: marketData.zhaban?.rate || 0,
    },
    sentiment: {
      overall: sentiment.overall || 50,
      phase: sentiment.phase || sentiment.phaseName || 'start',
      phaseName: sentiment.phaseName || sentiment.phase || '启动',
      emotionValue: marketData.emotionValue || 0,
    },
    rawCoverage: {
      hasHotlist: hotlist.length > 0,
      hasSectors: sectors.length > 0,
      hasMarketStats: true,
    },
  }
}

export class FrameNormalizer {
  async normalize(date?: string): Promise<{ reviewDate: string; frames: ReviewFrame[]; missingData: string[] }> {
    const reviewDate = normalizeDate(date)
    const missingData: string[] = []
    const frames: ReviewFrame[] = []
    // 不同粒度快照在这里被压平成统一的 ReviewFrame，
    // 后续模块只消费标准化后的 frame，不再分支判断数据来源。
    const bundles = await snapshotFacade.listSnapshotFrameBundles({
      types: RANK_TREND_SNAPSHOT_TYPES,
      tradingDate: reviewDate,
      allowedCaptureModes: FORMAL_SNAPSHOT_READ_POLICY.allowedCaptureModes,
      excludeRestored: FORMAL_SNAPSHOT_READ_POLICY.excludeRestored,
      sort: 'asc',
    })

    for (const bundle of bundles) {
      frames.push(buildFrameFromBundle(bundle, reviewDate))
    }

    frames.sort((a, b) => a.timestamp - b.timestamp)

    if (!frames.some((frame) => frame.source === 'close')) {
      const stocks = dataLayer.getStocks()
      if (stocks.length > 0) {
        const lastTimestamp =
          frames.length > 0
            ? Math.max(...frames.map((frame) => frame.timestamp)) + 1
            : new Date(`${reviewDate}T15:00:00+08:00`).getTime()
        frames.push(buildCloseFrame(stocks, reviewDate, lastTimestamp))
      } else {
        missingData.push('close_frame')
      }
    }

    // 缺数只记录，不在这里中断流程。
    // 真龙复盘允许“部分完成”，由末端统一报告完整性和缺失项。
    if (!frames.some((frame) => isRankTrendIntradaySnapshotType(frame.source))) {
      missingData.push('intraday_frames')
    }

    if (!frames.some((frame) => frame.source === 'daily')) {
      missingData.push('daily_snapshot')
    }

    if (!frames.length) {
      missingData.push('review_frames')
    }

    return {
      reviewDate,
      frames: frames.sort((a, b) => a.timestamp - b.timestamp),
      missingData,
    }
  }
}

export const frameNormalizer = new FrameNormalizer()
