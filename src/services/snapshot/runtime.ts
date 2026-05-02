import { SnapshotBackupSync } from './backupSync'
import { SnapshotBackupSyncStateStore } from './backupSyncState'
import { snapshotBackendIngest } from './backendIngest'
import { SnapshotCloudBackup } from './cloudBackup'
import {
  arrayToCSV,
  buildDailySnapshot,
  buildHourlySnapshot,
  buildIntradaySnapshotBase,
  getSnapshotMacdCross,
  getSnapshotRankChange,
  type SnapshotBuildContext,
} from './builders'
import { buildSnapshotId, createSnapshotRecord, toLocalSlotTime, toLocalTradingDate } from './identity'
import { deriveSnapshotCoverageSeverity } from './health'
import {
  buildCanonicalProjectionBundle,
  compactSnapshotRecord,
} from './projectionBundle'
import { FORMAL_SNAPSHOT_READ_POLICY } from './readPolicy'
import {
  findLatestEligibleSnapshotSlot,
  getExpectedSlots,
  getScheduledSlotsForDate,
  slotTimeToMinutes,
} from './schedule'
import {
  isRankTrendSnapshotType,
  RANK_TREND_SNAPSHOT_TYPES,
  type RankTrendIntradaySnapshotType,
  type RankTrendSnapshotType,
} from '../../type/rankTrendDefaults'
import { isTradingTime } from '../../utils/time'
import {
  SnapshotFrameStore,
  SnapshotProjectionMetaStore,
  SnapshotProjectionWriter,
  SnapshotSectorRowStore,
  SnapshotStockRowStore,
  SnapshotStore,
} from './store'
import { digestJson } from './hash'
import type {
  SnapshotBackupSyncState,
  SnapshotBackupAlignmentResult,
  SnapshotCoverageRepairResult,
  SnapshotCoverageReport,
  SnapshotCoverageWindowItem,
  SnapshotFrameQueryOptions,
  SnapshotFrameRow,
  SnapshotHealthOverview,
  SnapshotProjectionRewriteResult,
  SnapshotProjectionBundle,
  SnapshotProjectionMeta,
  SnapshotQueryOptions,
  SnapshotRecord,
  SnapshotSectorRow,
  SnapshotSectorRowQueryOptions,
  SnapshotStorageMaintenanceResult,
  SnapshotStockRow,
  SnapshotStockRowQueryOptions,
  SnapshotType,
  SnapshotRawCompactionResult,
  SnapshotPollutionCleanupResult,
} from './types'

interface SnapshotRuntimeDeps {
  logger?: Pick<Console, 'log' | 'warn' | 'error' | 'debug'>
  primaryDbName: string
  primaryDbVersion: number
  primaryStoreName: string
  legacyBackupDbName: string
  bucketBackupDbName: string
  backupDbVersion: number
  backupStoreName: string
  backupBucketName: string
  minBackupCount: number
  abnormalRatio: number
  syncIntervalMs: number
  getStorageBucketManager: () => any | null
  getBuildContext: () => SnapshotBuildContext
}

// SnapshotRuntime 是快照模块的总编排层：
// 它负责生成、查询、coverage、备份调度和恢复入口，但不直接承载 IndexedDB 细节实现。
export class SnapshotRuntime {
  private static readonly BACKUP_SYNC_STATE_KEY = 'dragon_board_snapshot_backup_sync_state_v3'
  private static readonly QUARTER_HOUR_BACKFILL_WINDOW_MS = 20 * 60 * 1000
  private static readonly HALF_HOUR_BACKFILL_WINDOW_MS = 35 * 60 * 1000
  private static readonly HOURLY_BACKFILL_WINDOW_MS = 65 * 60 * 1000
  private static readonly DAILY_BACKFILL_WINDOW_MS = 2 * 60 * 60 * 1000
  private static readonly LEGACY_CLOUD_SYNC_STATE_KEY = 'dragon_board_snapshot_cloud_sync_state'
  private readonly logger: Pick<Console, 'log' | 'warn' | 'error' | 'debug'>
  private readonly syncIntervalMs: number
  private readonly getBuildContext: () => SnapshotBuildContext
  private readonly getStorageBucketManager: () => any | null
  private readonly legacyBackupDbName: string
  private readonly bucketBackupDbName: string
  private readonly backupDbVersion: number
  private readonly backupStoreName: string
  private readonly backupBucketName: string
  private readonly backupSyncStateStore = new SnapshotBackupSyncStateStore({
    storage: typeof localStorage === 'undefined' ? undefined : localStorage,
    storageKey: SnapshotRuntime.BACKUP_SYNC_STATE_KEY,
    maxTradingDates: 40,
  })
  private persistRequested = false
  private backupBucketPersistRequested = false
  private snapshotWriteQueue: Promise<void> = Promise.resolve()
  private timer: ReturnType<typeof setInterval> | null = null
  private snapshotSyncTimer: number | null = null
  private snapshotSchedulePromise: Promise<void> | null = null
  private projectionBackfillTimer: ReturnType<typeof setTimeout> | null = null
  private projectionBackfillPromise: Promise<void> | null = null
  private lastCloudSyncTradingDate = this.loadCloudSyncTradingDate()
  private readonly snapshotStore: SnapshotStore
  private readonly snapshotProjectionWriter: SnapshotProjectionWriter
  private readonly snapshotFrameStore: SnapshotFrameStore
  private readonly snapshotStockRowStore: SnapshotStockRowStore
  private readonly snapshotSectorRowStore: SnapshotSectorRowStore
  private readonly snapshotProjectionMetaStore: SnapshotProjectionMetaStore
  private readonly cloudBackup: SnapshotCloudBackup
  private readonly snapshotBackupSync: SnapshotBackupSync

  constructor(deps: SnapshotRuntimeDeps) {
    this.logger = deps.logger || console
    this.syncIntervalMs = deps.syncIntervalMs
    this.getBuildContext = deps.getBuildContext
    this.getStorageBucketManager = deps.getStorageBucketManager
    this.legacyBackupDbName = deps.legacyBackupDbName
    this.bucketBackupDbName = deps.bucketBackupDbName
    this.backupDbVersion = deps.backupDbVersion
    this.backupStoreName = deps.backupStoreName
    this.backupBucketName = deps.backupBucketName
    this.snapshotStore = new SnapshotStore({
      dbName: deps.primaryDbName,
      dbVersion: deps.primaryDbVersion,
      storeName: deps.primaryStoreName,
      redundantStores: ['daily_snapshots', 'snapshot_meta'],
    })
    this.snapshotProjectionWriter = new SnapshotProjectionWriter({
      dbName: deps.primaryDbName,
      dbVersion: deps.primaryDbVersion,
      snapshotStoreName: deps.primaryStoreName,
      redundantStores: ['daily_snapshots', 'snapshot_meta'],
    })
    this.snapshotFrameStore = new SnapshotFrameStore({
      dbName: deps.primaryDbName,
      dbVersion: deps.primaryDbVersion,
      snapshotStoreName: deps.primaryStoreName,
      redundantStores: ['daily_snapshots', 'snapshot_meta'],
    })
    this.snapshotStockRowStore = new SnapshotStockRowStore({
      dbName: deps.primaryDbName,
      dbVersion: deps.primaryDbVersion,
      snapshotStoreName: deps.primaryStoreName,
      redundantStores: ['daily_snapshots', 'snapshot_meta'],
    })
    this.snapshotSectorRowStore = new SnapshotSectorRowStore({
      dbName: deps.primaryDbName,
      dbVersion: deps.primaryDbVersion,
      snapshotStoreName: deps.primaryStoreName,
      redundantStores: ['daily_snapshots', 'snapshot_meta'],
    })
    this.snapshotProjectionMetaStore = new SnapshotProjectionMetaStore({
      dbName: deps.primaryDbName,
      dbVersion: deps.primaryDbVersion,
      snapshotStoreName: deps.primaryStoreName,
      redundantStores: ['daily_snapshots', 'snapshot_meta'],
    })
    this.cloudBackup = new SnapshotCloudBackup()
    this.snapshotBackupSync = new SnapshotBackupSync({
      primaryStore: this.snapshotStore,
      primaryProjectionWriter: this.snapshotProjectionWriter,
      primaryFrameStore: this.snapshotFrameStore,
      primaryStockRowStore: this.snapshotStockRowStore,
      primarySectorRowStore: this.snapshotSectorRowStore,
      bucketStoreProvider: async () => this.createBucketBackupSnapshotStore(),
      bucketFrameStoreProvider: async () => this.createBucketBackupFrameStore(),
      bucketStockRowStoreProvider: async () => this.createBucketBackupStockRowStore(),
      bucketSectorRowStoreProvider: async () => this.createBucketBackupSectorRowStore(),
      bucketProjectionWriterProvider: async () => this.createBucketBackupProjectionWriter(),
      bucketManagerProvider: () => this.getStorageBucketManager(),
      bucketName: deps.backupBucketName,
      minBackupCount: deps.minBackupCount,
      abnormalRatio: deps.abnormalRatio,
      cloudBackup: this.cloudBackup,
      logger: this.logger,
      onBucketSyncSuccess: (tradingDate, syncedAt) => this.recordBucketSyncSuccess(tradingDate, syncedAt),
      onBucketSyncError: (tradingDate, error) => this.recordBucketSyncError(tradingDate, error),
      onCloudBundleUploaded: (tradingDate, uploadedAt) =>
        this.recordCloudBundleUploaded(tradingDate, uploadedAt),
      onCloudBundleError: (tradingDate, error) => this.recordCloudBundleError(tradingDate, error),
    })
  }

  start() {
    this.startTimer()
    void this.ensurePersistentStorage()
    void this.cleanupLegacyPlainBackupDatabase()
    void this.migrateLegacyBucketBackupDatabase()
    void this.cleanupInvalidRuntimeSnapshots()
    void this.initializeSnapshotGuard()
    this.startSnapshotAutoSync()
    this.scheduleProjectionBackfill(1_000)
  }

  stop() {
    if (this.timer) {
      clearInterval(this.timer)
      this.timer = null
    }
    if (this.snapshotSyncTimer) {
      clearInterval(this.snapshotSyncTimer)
      this.snapshotSyncTimer = null
    }
    if (this.projectionBackfillTimer) {
      clearTimeout(this.projectionBackfillTimer)
      this.projectionBackfillTimer = null
    }
  }

  async saveQuarterHourSnapshot(snapshotTime?: Date): Promise<boolean> {
    try {
      const effectiveTime = this.resolveSnapshotTime('quarter_hour', snapshotTime)
      if (!effectiveTime) {
        this.logger.warn('[DataLayer] 跳过一刻快照保存：当前不在合法槽位')
        return false
      }
      if (!this.isSnapshotCaptureAllowed('quarter_hour', effectiveTime)) {
        this.logSnapshotCaptureSkipped('quarter_hour', effectiveTime)
        return false
      }
      const buildContext = this.getBuildContext()
      const snapshot = buildIntradaySnapshotBase(buildContext, effectiveTime, buildContext.stocks.length)
      const cleanSnapshot = JSON.parse(JSON.stringify(snapshot))
      const record = this.createManagedSnapshotRecord('quarter_hour', effectiveTime, cleanSnapshot)
      const saved = await this.saveSnapshotRecord(record, this.createProjectionBundle(record, buildContext))
      if (saved) {
        this.logger.log(`[DataLayer] ✅ 一刻快照已保存 (v2.1): ${record.displayKey}, 股票数: ${snapshot.hotlist.length}`)
      }
      return saved
    } catch (error) {
      this.logger.error('[DataLayer] ❌ 保存一刻快照失败:', error)
      return false
    }
  }

  async saveHalfHourSnapshot(snapshotTime?: Date): Promise<boolean> {
    try {
      const effectiveTime = this.resolveSnapshotTime('half_hour', snapshotTime)
      if (!effectiveTime) {
        this.logger.warn('[DataLayer] 跳过半小时快照保存：当前不在合法槽位')
        return false
      }
      if (!this.isSnapshotCaptureAllowed('half_hour', effectiveTime)) {
        this.logSnapshotCaptureSkipped('half_hour', effectiveTime)
        return false
      }
      const buildContext = this.getBuildContext()
      const snapshot = buildIntradaySnapshotBase(buildContext, effectiveTime, buildContext.stocks.length)
      const cleanSnapshot = JSON.parse(JSON.stringify(snapshot))
      const record = this.createManagedSnapshotRecord('half_hour', effectiveTime, cleanSnapshot)
      const saved = await this.saveSnapshotRecord(record, this.createProjectionBundle(record, buildContext))
      if (saved) {
        this.logger.log(`[DataLayer] ✅ 半小时快照已保存 (v2.1): ${record.displayKey}, 股票数: ${snapshot.hotlist.length}`)
      }
      return saved
    } catch (error) {
      this.logger.error('[DataLayer] ❌ 保存半小时快照失败:', error)
      return false
    }
  }

  async saveHourlySnapshot(snapshotTime?: Date): Promise<boolean> {
    try {
      const effectiveTime = this.resolveSnapshotTime('hourly', snapshotTime)
      if (!effectiveTime) {
        this.logger.warn('[DataLayer] 跳过小时快照保存：当前不在合法槽位')
        return false
      }
      if (!this.isSnapshotCaptureAllowed('hourly', effectiveTime)) {
        this.logSnapshotCaptureSkipped('hourly', effectiveTime)
        return false
      }
      const buildContext = this.getBuildContext()
      const snapshot = buildHourlySnapshot(buildContext, effectiveTime)
      const cleanSnapshot = JSON.parse(JSON.stringify(snapshot))
      const record = this.createManagedSnapshotRecord('hourly', effectiveTime, cleanSnapshot)
      const saved = await this.saveSnapshotRecord(record, this.createProjectionBundle(record, buildContext))
      if (saved) {
        this.logger.log(`[DataLayer] ✅ 整点快照已保存 (v2.1): ${record.displayKey}, 股票数: ${Math.min(buildContext.stocks.length, 100)}`)
      }
      return saved
    } catch (error) {
      this.logger.error('[DataLayer] ❌ 保存小时快照失败:', error)
      return false
    }
  }

  generateDailySnapshot(snapshotTime: Date = new Date()): any {
    return buildDailySnapshot(this.getBuildContext(), snapshotTime)
  }

  exportDailySnapshot(): string {
    return JSON.stringify(this.generateDailySnapshot(), null, 2)
  }

  async exportStockQuarterSnapshots(stockCode: string, stockName: string = ''): Promise<boolean> {
    try {
      const quarterSnapshots = await this.listSnapshots({ type: 'quarter_hour', sort: 'asc' })
      if (quarterSnapshots.length === 0) {
        this.logger.warn('[DataLayer] 没有一刻快照数据')
        return false
      }
      const stockData: any[] = []
      for (const record of quarterSnapshots) {
        const snapshot = record.payload
        if (snapshot?.hotlist) {
          const stock = snapshot.hotlist.find((s: any) => s.code === stockCode)
          if (stock) {
            stockData.push({
              快照时间: record.displayKey.replace('[一刻快照] ', ''),
              代码: stock.code,
              名称: stock.name || stockName,
              价格: stock.price,
              '涨幅%': stock.change,
              均榜: stock.avgRank,
              排名: stock.rank,
              变化: getSnapshotRankChange(stock),
              成交量: stock.volume,
              成交额: stock.turnover,
              '换手率%': stock.turnoverRate,
              主力净额: stock.zlje,
              量比: stock.volumeRatio,
              领涨状态: stock.leadStatus,
              连板: stock.lianbanStr,
              封单额: stock.fengdan,
              方向一致性: stock.signals?.direction?.signal || '',
              动量加速度: stock.signals?.acceleration?.signal || '',
              零线交叉: stock.signals?.cross?.signal || '',
              最终信号: stock.signals?.final?.signal,
              最终置信度: stock.signals?.final?.confidence,
              MACD金叉: getSnapshotMacdCross(stock),
            })
          }
        }
      }
      if (stockData.length === 0) {
        this.logger.warn(`[DataLayer] 未找到股票 ${stockCode} 的一刻快照数据`)
        return false
      }
      const headers = Object.keys(stockData[0])
      const csvRows: string[] = [headers.join(',')]
      for (const row of stockData) {
        csvRows.push(
          headers
            .map((header) => {
              const val = row[header]
              if (val === undefined || val === null) return ''
              const str = String(val)
              return str.includes(',') || str.includes('"') || str.includes('\n') ? `"${str.replace(/"/g, '""')}"` : str
            })
            .join(','),
        )
      }
      this.downloadTextFile(csvRows.join('\n'), `${stockCode}_${stockName || 'stock'}_quarter_snapshots.csv`, 'text/csv;charset=utf-8;')
      this.logger.log(`[DataLayer] ✅ 已导出 ${stockData.length} 条记录`)
      return true
    } catch (error) {
      this.logger.error('[DataLayer] ❌ 导出股票一刻快照失败:', error)
      return false
    }
  }

  async exportSnapshotToExcel(
    snapshotId: string,
    options?: {
      sheets?: ('hotlist' | 'sectors' | 'sentiment' | 'market')[]
      filename?: string
    },
  ): Promise<boolean> {
    try {
      const record = await this.getSnapshotById(snapshotId)
      const snapshot = record?.payload
      if (!record || !snapshot) {
        this.logger.error(`[DataLayer] ❌ 未找到快照: ${snapshotId}`)
        return false
      }
      const sheets = options?.sheets || ['hotlist', 'sectors', 'sentiment', 'market']
      const filename = options?.filename || `${record.displayKey.replace(/[\[\] :]/g, '_')}_export`
      const csvParts: string[] = []
      const sheetTitles: string[] = []

      if (sheets.includes('hotlist') && snapshot.hotlist?.length) {
        sheetTitles.push('热榜')
        const headers = ['排名','代码','名称','价格','涨幅%','成交额','换手率%','总市值','流通市值','主力净额','主力占比','超大单净额','超大单占比','市盈率','市净率','量比','涨速','领涨状态','连板','封单额','人气排名','人气变化','首次涨停','最后涨停','连板天数','热度值','标签','涨停原因','排名变化','资金穿透','主要题材','题材热度','题材等级','方向信号','方向置信度','加速信号','加速置信度','交叉信号','交叉置信度','最终信号','最终置信度','MACD信号']
        const rows = snapshot.hotlist.map((stock: any, idx: number) => [
          stock.rank || idx + 1, stock.code || '', stock.name || '', stock.price || 0, stock.change || 0,
          stock.turnover || 0, stock.turnoverRate || 0, stock.totalMV || 0, stock.cirMV || 0, stock.zlje || 0,
          stock.zljzb || 0, stock.cddje || 0, stock.cddjzb || 0, stock.pe || 0, stock.pb || 0, stock.volumeRatio || 0,
          stock.speed || 0, stock.leadStatus || '', stock.lianbanStr || '', stock.fengdan || 0, stock.popularity || 0,
          stock.popularityChange || 0, stock.firstZtTime || '', stock.lastZtTime || '', stock.highDays || 0, stock.hotness || 0,
          Array.isArray(stock.tags) ? stock.tags.map((t: any) => t.Name || t).join(';') : stock.tags || '', stock.reason || '',
          getSnapshotRankChange(stock), stock.fundPenetration || stock.technicalIndicators?.fundPenetration || 0,
          stock.mainTheme || '', stock.themeHeat || 0, stock.themeLevel || '', stock.signals?.direction?.signal || '',
          stock.signals?.direction?.confidence || 0, stock.signals?.acceleration?.signal || '', stock.signals?.acceleration?.confidence || 0,
          stock.signals?.cross?.signal || '', stock.signals?.cross?.confidence || 0, stock.signals?.final?.signal || '',
          stock.signals?.final?.confidence || 0, getSnapshotMacdCross(stock),
        ])
        csvParts.push(arrayToCSV([headers, ...rows]))
      }

      if (sheets.includes('sectors') && snapshot.sectors?.length) {
        sheetTitles.push('板块')
        const headers = ['代码', '名称', '强度', '涨幅%', '主力净额', '300W大单', '机构增仓', '量比', '涨停数']
        const rows = snapshot.sectors.map((sector: any) => [
          sector.code || '', sector.name || '', sector.strength || 0, sector.change || 0, sector.mainNetInflow || 0,
          sector.bigMoney300 || 0, sector.institutionBuy || 0, sector.volumeRatio || 0, sector.ztCount || 0,
        ])
        csvParts.push(arrayToCSV([headers, ...rows]))
      }

      if (sheets.includes('sentiment') && snapshot.sentiment) {
        sheetTitles.push('情绪')
        csvParts.push(arrayToCSV([['字段', '值'], ['情绪阶段', snapshot.sentiment.phaseName || '启动'], ['情绪代码', snapshot.sentiment.phase || 'start'], ['情绪值', snapshot.sentiment.emotionValue || 50]]))
      }

      if (sheets.includes('market') && snapshot.marketStats) {
        sheetTitles.push('市场')
        csvParts.push(arrayToCSV([['字段', '值'], ['上涨家数', snapshot.marketStats.upCount || 0], ['下跌家数', snapshot.marketStats.downCount || 0], ['涨停家数', snapshot.marketStats.ztCount || 0], ['跌停家数', snapshot.marketStats.dtCount || 0], ['成交额(亿)', ((snapshot.marketStats.totalAmo || 0) / 1e8).toFixed(0)], ['主力净额', snapshot.moneyFlow?.main || 0], ['散户净额', snapshot.moneyFlow?.retail || 0]]))
      }

      let finalCSV = ''
      for (let i = 0; i < csvParts.length; i++) {
        if (i > 0) finalCSV += `\n\n========== ${sheetTitles[i]} ==========\n\n`
        finalCSV += csvParts[i]
      }
      this.downloadTextFile('\uFEFF' + finalCSV, `${filename}.csv`, 'text/csv;charset=utf-8;')
      this.logger.log(`[DataLayer] ✅ 已导出 Excel: ${filename}.csv`)
      return true
    } catch (error) {
      this.logger.error('[DataLayer] ❌ 导出失败:', error)
      return false
    }
  }

  async exportSnapshotsRangeToExcel(startDate: string, endDate: string): Promise<boolean> {
    try {
      const filteredSnapshots = await this.listSnapshots({ startDate, endDate, sort: 'asc' })
      if (filteredSnapshots.length === 0) {
        this.logger.warn('[DataLayer] 指定范围内没有快照')
        return false
      }
      const allData: any[] = []
      for (const record of filteredSnapshots) {
        const snapshot = record.payload
        if (snapshot?.hotlist) {
          snapshot.hotlist.forEach((stock: any) => {
            allData.push({
              快照时间: record.displayKey,
              排名: stock.rank,
              代码: stock.code,
              名称: stock.name,
              价格: stock.price,
              '涨幅%': stock.change,
              成交额: stock.turnover,
              '换手率%': stock.turnoverRate,
              主力净额: stock.zlje,
              量比: stock.volumeRatio,
              领涨状态: stock.leadStatus,
              连板: stock.lianbanStr,
              最终信号: stock.signals?.final?.signal,
              最终置信度: stock.signals?.final?.confidence,
            })
          })
        }
      }
      if (allData.length === 0) {
        this.logger.warn('[DataLayer] 没有数据可导出')
        return false
      }
      const headers = Object.keys(allData[0])
      const rows = allData.map((row) => headers.map((h) => row[h]))
      this.downloadTextFile('\uFEFF' + arrayToCSV([headers, ...rows]), `snapshots_${startDate}_to_${endDate}.csv`, 'text/csv;charset=utf-8;')
      this.logger.log(`[DataLayer] ✅ 已导出 ${allData.length} 条记录`)
      return true
    } catch (error) {
      this.logger.error('[DataLayer] ❌ 导出失败:', error)
      return false
    }
  }

  async saveDailySnapshot(snapshotTime?: Date): Promise<boolean> {
    try {
      const effectiveTime = this.resolveSnapshotTime('daily', snapshotTime)
      if (!effectiveTime) {
        this.logger.warn('[DataLayer] 跳过日级快照保存：当前不在合法槽位')
        return false
      }
      if (!this.isSnapshotCaptureAllowed('daily', effectiveTime)) {
        this.logSnapshotCaptureSkipped('daily', effectiveTime)
        return false
      }
      const buildContext = this.getBuildContext()
      const snapshot = buildDailySnapshot(buildContext, effectiveTime)
      const cleanSnapshot = JSON.parse(JSON.stringify(snapshot))
      const record = this.createManagedSnapshotRecord('daily', effectiveTime, cleanSnapshot)
      return this.saveSnapshotRecord(record, this.createProjectionBundle(record, buildContext))
    } catch (error) {
      this.logger.error('[DataLayer] ❌ 保存失败:', error)
      return false
    }
  }

  async listSnapshots(options: SnapshotQueryOptions = {}): Promise<SnapshotRecord[]> {
    // coverage 过滤是“交易日级语义”，必须在拿到候选记录后再判断，
    // 不能交给 Store 层用单条记录过滤去偷实现。
    const requiresCoverage = options.requireCoverage === true
    const storeOptions: SnapshotQueryOptions = {
      ...options,
      requireCoverage: undefined,
      coverageTolerance: undefined,
      ...(requiresCoverage ? { limit: undefined } : {}),
    }
    const records = await this.snapshotStore.list(storeOptions)

    if (!requiresCoverage) {
      return records
    }

    return this.filterSnapshotsByCoverage(records, options)
  }

  async getSnapshotById(id: string): Promise<SnapshotRecord | null> {
    return this.snapshotStore.getById(id)
  }

  async getTradingDateSnapshot(type: SnapshotType, tradingDate: string): Promise<SnapshotRecord | null> {
    const snapshots = await this.listSnapshots({ type, tradingDate, sort: 'desc', limit: 1 })
    return snapshots[0] || null
  }

  async listSnapshotFrames(options: SnapshotFrameQueryOptions = {}): Promise<SnapshotFrameRow[]> {
    await this.ensureProjectedRawRecords(this.toRawSnapshotQueryFromFrameQuery(options))
    return this.snapshotFrameStore.list(options)
  }

  async listSnapshotStockRows(options: SnapshotStockRowQueryOptions = {}): Promise<SnapshotStockRow[]> {
    if (options.snapshotId) {
      const rawRecord = await this.snapshotStore.getById(options.snapshotId)
      if (rawRecord && rawRecord.type !== 'five_minute' && !(await this.isProjectionBundleCurrent(rawRecord.id))) {
        await this.snapshotProjectionWriter.saveBundle(await this.buildCanonicalPrimaryBundle(rawRecord))
      }
      return this.snapshotStockRowStore.list(options)
    }
    await this.ensureProjectedRawRecords(this.toRawSnapshotQueryFromStockQuery(options))
    return this.snapshotStockRowStore.list(options)
  }

  async listSnapshotSectorRows(options: SnapshotSectorRowQueryOptions = {}): Promise<SnapshotSectorRow[]> {
    if (options.snapshotId) {
      const rawRecord = await this.snapshotStore.getById(options.snapshotId)
      if (rawRecord && rawRecord.type !== 'five_minute' && !(await this.isProjectionBundleCurrent(rawRecord.id))) {
        await this.snapshotProjectionWriter.saveBundle(await this.buildCanonicalPrimaryBundle(rawRecord))
      }
      return this.snapshotSectorRowStore.list(options)
    }
    await this.ensureProjectedRawRecords(this.toRawSnapshotQueryFromSectorQuery(options))
    return this.snapshotSectorRowStore.list(options)
  }

  async getSnapshotProjectionMeta(): Promise<SnapshotProjectionMeta | null> {
    return this.snapshotProjectionMetaStore.get()
  }

  async rebuildSnapshotProjectionStores(
    options: SnapshotQueryOptions = {},
  ): Promise<SnapshotProjectionRewriteResult> {
    const records = await this.snapshotStore.list({
      ...options,
      sort: 'asc',
    })
    const formalRecords = records.filter((record) => record.type !== 'five_minute')
    const affectedTradingDates = new Set<string>()
    let rewritten = 0

    const currentMeta =
      (await this.snapshotProjectionMetaStore.get()) ||
      ({
        key: 'global',
        schemaVersion: 1,
        backfillStatus: 'idle',
      } satisfies SnapshotProjectionMeta)

    await this.snapshotProjectionMetaStore.put({
      ...currentMeta,
      backfillStatus: 'running',
      lastBackfillAt: Date.now(),
      lastError: undefined,
    })

    try {
      for (const record of formalRecords) {
        await this.snapshotProjectionWriter.saveBundle(await this.buildCanonicalPrimaryBundle(record))
        rewritten += 1
        if (record.tradingDate) {
          affectedTradingDates.add(record.tradingDate)
        }
      }

      await this.snapshotProjectionMetaStore.put({
        key: 'global',
        schemaVersion: 1,
        backfillStatus: 'completed',
        projectedBeforeTimestamp:
          formalRecords[formalRecords.length - 1]?.timestamp || currentMeta.projectedBeforeTimestamp,
        lastBackfillCursor:
          formalRecords[formalRecords.length - 1]?.id || currentMeta.lastBackfillCursor,
        lastBackfillAt: Date.now(),
      })
    } catch (error) {
      await this.snapshotProjectionMetaStore.put({
        key: 'global',
        schemaVersion: 1,
        backfillStatus: 'error',
        projectedBeforeTimestamp: currentMeta.projectedBeforeTimestamp,
        lastBackfillCursor: currentMeta.lastBackfillCursor,
        lastBackfillAt: Date.now(),
        lastError: error instanceof Error ? error.message : String(error),
      })
      throw error
    }

    return {
      scanned: formalRecords.length,
      rewritten,
      affectedTradingDates: Array.from(affectedTradingDates).sort(),
    }
  }

  async alignSnapshotBackups(
    options?: SnapshotQueryOptions & { includeCloud?: boolean },
  ): Promise<SnapshotBackupAlignmentResult> {
    const records = await this.snapshotStore.list({
      ...options,
      sort: 'asc',
    })
    const affectedTradingDates = Array.from(
      new Set(
        records
          .filter((record) => record.type !== 'five_minute')
          .map((record) => record.tradingDate)
          .filter(Boolean),
      ),
    ).sort()
    let localBundlesSynced = 0

    for (const record of records) {
      const bundle =
        record.type === 'five_minute'
          ? {
              record,
              frame: null,
              stockRows: [],
              sectorRows: [],
            }
          : await this.buildCanonicalPrimaryBundle(record)
      await this.snapshotBackupSync.saveToBackups(bundle, { overwrite: true })
      localBundlesSynced += 1
    }

    const cloudEnabled = options?.includeCloud !== false && (await this.cloudBackup.getHealth()).enabled === true
    const cloudUploadedTradingDates: string[] = []

    if (cloudEnabled) {
      for (const tradingDate of affectedTradingDates) {
        await this.syncPrimarySnapshotsToCloud({
          overwrite: true,
          tradingDate,
        })
        cloudUploadedTradingDates.push(tradingDate)
      }
    }

    return {
      processedSnapshots: records.length,
      localBundlesSynced,
      cloudEnabled,
      cloudUploadedTradingDates,
    }
  }

  async compactSnapshotRawRecords(options: SnapshotQueryOptions = {}): Promise<SnapshotRawCompactionResult> {
    const records = await this.snapshotStore.list({
      ...options,
      sort: 'asc',
    })
    const affectedTradingDates = new Set<string>()
    let rewritten = 0

    for (const record of records) {
      const compacted = compactSnapshotRecord(record)
      if (JSON.stringify(compacted.payload) === JSON.stringify(record.payload)) {
        continue
      }

      await this.snapshotStore.put(compacted)
      rewritten += 1
      if (record.tradingDate) {
        affectedTradingDates.add(record.tradingDate)
      }
    }

    return {
      scanned: records.length,
      rewritten,
      affectedTradingDates: Array.from(affectedTradingDates).sort(),
    }
  }

  async cleanupInvalidRuntimeSnapshots(
    options: SnapshotQueryOptions = {},
  ): Promise<SnapshotPollutionCleanupResult> {
    const records = await this.snapshotStore.list({
      ...options,
      allowedCaptureModes: options.allowedCaptureModes || ['real_time', 'delayed'],
      sort: 'asc',
    })
    const affectedTradingDates = new Set<string>()
    const deletedSnapshotIds: string[] = []

    for (const record of records) {
      if (!this.isInvalidRuntimeSnapshot(record)) continue
      const deleted = await this.deleteSnapshotRecord(record.id, {
        removeLocalBackups: false,
        removeBackupState: true,
      })
      if (!deleted) continue
      deletedSnapshotIds.push(record.id)
      if (record.tradingDate) affectedTradingDates.add(record.tradingDate)
    }

    const backupCleanup = await this.snapshotBackupSync.cleanupInvalidLocalBackups((record) =>
      this.isInvalidRuntimeSnapshot(record),
    )
    backupCleanup.affectedTradingDates.forEach((tradingDate) => affectedTradingDates.add(tradingDate))
    backupCleanup.affectedTradingDates.forEach((tradingDate) => this.backupSyncStateStore.remove(tradingDate))

    const result: SnapshotPollutionCleanupResult = {
      scanned: records.length + backupCleanup.scanned,
      deleted: deletedSnapshotIds.length,
      deletedFromPrimary: deletedSnapshotIds.length,
      deletedFromBucketBackup: backupCleanup.deleted,
      affectedTradingDates: Array.from(affectedTradingDates).sort(),
      deletedSnapshotIds: Array.from(new Set([...deletedSnapshotIds, ...backupCleanup.deletedSnapshotIds])),
    }

    if (result.deleted > 0) {
      this.logger.warn?.('[DataLayer] Snapshot pollution cleanup completed:', result)
    }

    return result
  }

  async runSnapshotStorageMaintenance(
    options?: SnapshotQueryOptions & { includeCloud?: boolean },
  ): Promise<SnapshotStorageMaintenanceResult> {
    const projectionRebuild = await this.rebuildSnapshotProjectionStores(options || {})
    const backupAlignmentBeforeCompaction = await this.alignSnapshotBackups(options)
    const rawCompaction = await this.compactSnapshotRawRecords(options || {})
    const backupAlignmentAfterCompaction = await this.alignSnapshotBackups(options)

    return {
      projectionRebuild,
      backupAlignmentBeforeCompaction,
      rawCompaction,
      backupAlignmentAfterCompaction,
    }
  }

  async getStockVolumeHistory(
    codes: string[],
    options?: { anchorTradingDate?: string; lookbackDays?: number },
  ): Promise<Map<string, number[]>> {
    const requestedCodes = Array.from(new Set((codes || []).filter(Boolean)))
    const result = new Map<string, number[]>()
    if (requestedCodes.length === 0) return result

    const lookbackDays = Math.max(1, Math.min(10, Number(options?.lookbackDays) || 3))

    // 量比正式口径固定走日级投影行，避免回退到全量快照扫描或盘中 close-slot 近似。
    await this.ensureProjectedRawRecords({
      type: 'daily',
      endDate: options?.anchorTradingDate,
      allowedCaptureModes: FORMAL_SNAPSHOT_READ_POLICY.allowedCaptureModes,
      excludeRestored: FORMAL_SNAPSHOT_READ_POLICY.excludeRestored,
      sort: 'desc',
    })

    await Promise.all(
      requestedCodes.map(async (code) => {
        const rows = await this.snapshotStockRowStore.list({
          code,
          type: 'daily',
          beforeTradingDate: options?.anchorTradingDate,
          allowedCaptureModes: FORMAL_SNAPSHOT_READ_POLICY.allowedCaptureModes,
          excludeRestored: FORMAL_SNAPSHOT_READ_POLICY.excludeRestored,
          sort: 'desc',
          limit: lookbackDays,
        })

        const volumesByDate = new Map<string, { volume: number; timestamp: number }>()
        for (const row of rows || []) {
          const tradingDate = String(row.tradingDate || '')
          const volume = Number(row.volume)
          if (!tradingDate || !Number.isFinite(volume) || volume <= 0) continue
          if (!volumesByDate.has(tradingDate)) {
            volumesByDate.set(tradingDate, {
              volume,
              timestamp: Number(row.timestamp) || 0,
            })
          }
        }

        const volumes = Array.from(volumesByDate.entries())
          .sort(([leftDate, left], [rightDate, right]) => {
            const dateOrder = rightDate.localeCompare(leftDate)
            return dateOrder !== 0 ? dateOrder : right.timestamp - left.timestamp
          })
          .slice(0, lookbackDays)
          .map(([, item]) => item.volume)

        if (volumes.length > 0) {
          result.set(code, volumes)
        }
      }),
    )

    return result
  }

  async getLatestSnapshotRecord(options?: {
    type?: SnapshotType
    beforeTradingDate?: string
    allowedCaptureModes?: Array<'real_time' | 'delayed' | 'restored'>
    excludeRestored?: boolean
  }): Promise<SnapshotRecord | null> {
    const snapshots = await this.listSnapshots({
      type: options?.type,
      beforeTradingDate: options?.beforeTradingDate,
      allowedCaptureModes: options?.allowedCaptureModes,
      excludeRestored: options?.excludeRestored,
      sort: 'desc',
      limit: 1,
    })
    return snapshots[0] || null
  }

  async exportSnapshotAsFile(id: string): Promise<void> {
    const record = await this.getSnapshotById(id)
    const snapshot = record?.payload
    if (!snapshot) {
      this.logger.warn(`[DataLayer] 未找到 ${id} 的快照`)
      return
    }
    this.downloadTextFile(JSON.stringify(snapshot, null, 2), `${record?.displayKey.replace(/[\[\] :]/g, '_') || 'snapshot'}.json`, 'application/json')
  }

  async exportAllSnapshots(): Promise<void> {
    const snapshots = await this.listSnapshots({ sort: 'desc' })
    if (snapshots.length === 0) {
      this.logger.warn('[DataLayer] 没有快照可导出')
      return
    }
    for (const snapshot of snapshots) {
      await this.exportSnapshotAsFile(snapshot.id)
      await new Promise((resolve) => setTimeout(resolve, 500))
    }
  }

  async deleteSnapshot(id: string): Promise<boolean> {
    try {
      return this.deleteSnapshotRecord(id, { removeLocalBackups: true, removeBackupState: false })
    } catch (error) {
      this.logger.error('[DataLayer] 删除失败:', error)
      return false
    }
  }

  async getSnapshotStorageStats() {
    return this.snapshotStore.getStats()
  }

  async getBackupSnapshotStorageStats() {
    return this.snapshotBackupSync.getBackupStats()
  }

  async getBackupBucketHealth() {
    return this.snapshotBackupSync.getBucketHealth()
  }

  async getCloudBackupHealth() {
    return this.snapshotBackupSync.getCloudHealth()
  }

  async getSnapshotBackupSyncState(tradingDate?: string): Promise<SnapshotBackupSyncState | null> {
    const effectiveTradingDate = tradingDate || (await this.resolveOverviewTradingDate())
    if (!effectiveTradingDate) return null
    return this.backupSyncStateStore.get(effectiveTradingDate) || { tradingDate: effectiveTradingDate }
  }

  async listSnapshotBackupSyncStates(limit?: number): Promise<SnapshotBackupSyncState[]> {
    return this.backupSyncStateStore.list(limit)
  }

  async getSnapshotHealthOverview(tradingDate?: string): Promise<SnapshotHealthOverview> {
    // UI 应优先消费这个总览，而不是各自拼 coverage、备份状态和正式样本口径。
    const effectiveTradingDate = tradingDate || (await this.resolveOverviewTradingDate())
    if (!effectiveTradingDate) {
      return {
        tradingDate: null,
        coverage: null,
        severity: 'warn',
        backupSyncState: null,
        formalReadPolicy: FORMAL_SNAPSHOT_READ_POLICY,
      }
    }

    const coverage = await this.inspectTradingDateSnapshotCoverage(effectiveTradingDate)
    return {
      tradingDate: effectiveTradingDate,
      coverage,
      severity: deriveSnapshotCoverageSeverity(coverage),
      backupSyncState:
        this.backupSyncStateStore.get(effectiveTradingDate) || { tradingDate: effectiveTradingDate },
      formalReadPolicy: FORMAL_SNAPSHOT_READ_POLICY,
    }
  }

  async restoreSnapshotsFromBackup(options?: { overwrite?: boolean; limit?: number }) {
    const result = await this.snapshotBackupSync.restorePrimaryFromBackups(options)
    if (result.restored > 0) {
      this.scheduleProjectionBackfill(100)
    }
    return result
  }

  async syncPrimarySnapshotsToBackup(options?: { overwrite?: boolean; limit?: number }) {
    return this.snapshotBackupSync.syncPrimaryToBackups(options)
  }

  async syncAllSnapshotStores(options?: { overwrite?: boolean; limit?: number }) {
    return this.snapshotBackupSync.syncAllStores({
      ...options,
      includeRemoteCloud: false,
    })
  }

  async runSnapshotAutoRecoveryCheck(options?: { minBackupCount?: number; abnormalRatio?: number; force?: boolean }) {
    return this.snapshotBackupSync.runAutoRecoveryCheck(options)
  }

  async inspectTradingDateSnapshotCoverage(tradingDate: string): Promise<SnapshotCoverageReport> {
    // 当前正式 coverage 固定为四桶，一次性产出给 UI、诊断和 requireCoverage 复用。
    const quarterRecords = await this.listSnapshots({ type: 'quarter_hour', tradingDate, sort: 'asc' })
    const halfRecords = await this.listSnapshots({ type: 'half_hour', tradingDate, sort: 'asc' })
    const hourlyRecords = await this.listSnapshots({ type: 'hourly', tradingDate, sort: 'asc' })
    const dailyRecords = await this.listSnapshots({ type: 'daily', tradingDate, sort: 'asc' })

    return {
      quarterHour: this.buildCoverageReport('quarter_hour', quarterRecords),
      halfHour: this.buildCoverageReport('half_hour', halfRecords),
      hourly: this.buildCoverageReport('hourly', hourlyRecords),
      daily: this.buildCoverageReport('daily', dailyRecords),
    }
  }

  async buildSnapshotCoverageWindow(options?: {
    startDate?: string
    endDate?: string
    limit?: number
  }): Promise<SnapshotCoverageWindowItem[]> {
    const records = await this.listSnapshots({
      startDate: options?.startDate,
      endDate: options?.endDate,
      sort: 'desc',
    })
    const tradingDates = Array.from(new Set(records.map((record) => record.tradingDate).filter(Boolean))).sort().reverse()
    const dates = tradingDates.slice(0, options?.limit && options.limit > 0 ? options.limit : tradingDates.length)
    const items: SnapshotCoverageWindowItem[] = []

    for (const tradingDate of dates) {
      const coverage = await this.inspectTradingDateSnapshotCoverage(tradingDate)
      const severity = deriveSnapshotCoverageSeverity(coverage)

      items.push({
        tradingDate,
        quarterHour: coverage.quarterHour,
        halfHour: coverage.halfHour,
        hourly: coverage.hourly,
        daily: coverage.daily,
        severity,
      })
    }

    return items
  }

  async repairTradingDateSnapshotCoverage(
    tradingDate: string,
    options?: {
      toleranceMinutes?: number
      deriveHalfHourFromQuarter?: boolean
    },
  ): Promise<SnapshotCoverageRepairResult> {
    // 这里的 repair 只返回内存候选，不写主库，不触发备份，也不生成 repair store。
    const toleranceMinutes = Math.max(1, Math.min(14, Number(options?.toleranceMinutes) || 10))
    const deriveHalfHourFromQuarter = options?.deriveHalfHourFromQuarter !== false
    const normalizedQuarterCandidates = []
    const derivedHalfHourCandidates = []
    const rejectedCandidates: SnapshotCoverageRepairResult['rejectedCandidates'] = []

    const quarterRecords = await this.listSnapshots({ type: 'quarter_hour', tradingDate, sort: 'asc' })
    const validQuarterSlots = new Set(getExpectedSlots('quarter_hour'))
    const existingQuarterSlots = new Set(quarterRecords.map((record) => record.slotTime))

    for (const record of quarterRecords) {
      if (validQuarterSlots.has(record.slotTime)) continue
      const nearest = this.findNearestExpectedSlot('quarter_hour', record.slotTime, toleranceMinutes)
      if (!nearest || existingQuarterSlots.has(nearest)) {
        rejectedCandidates.push({
          type: 'quarter_hour',
          tradingDate,
          slotTime: record.slotTime,
          reason: !nearest ? 'no_eligible_nearest_slot' : 'target_slot_already_exists',
        })
        continue
      }

      const repaired = this.cloneRecordToSlot(record, 'quarter_hour', tradingDate, nearest)
      existingQuarterSlots.delete(record.slotTime)
      existingQuarterSlots.add(nearest)
      normalizedQuarterCandidates.push({
        ...repaired,
        reason: `normalized_from_${record.slotTime}`,
      })
    }

    if (deriveHalfHourFromQuarter) {
      const repairedQuarterRecords = [
        ...quarterRecords.filter((record) => validQuarterSlots.has(record.slotTime)),
        ...normalizedQuarterCandidates,
      ].sort((left, right) => left.timestamp - right.timestamp)
      const halfRecords = await this.listSnapshots({ type: 'half_hour', tradingDate, sort: 'asc' })
      const existingHalfSlots = new Set(halfRecords.map((record) => record.slotTime))
      const expectedHalfSlots = getExpectedSlots('half_hour')
      const latestQuarterSlot = repairedQuarterRecords[repairedQuarterRecords.length - 1]?.slotTime || ''

      for (const slotTime of expectedHalfSlots) {
        if (latestQuarterSlot && this.slotTimeToMinutes(slotTime) > this.slotTimeToMinutes(latestQuarterSlot)) {
          continue
        }
        if (existingHalfSlots.has(slotTime)) continue
        const sourceQuarter = repairedQuarterRecords.find((record) => record.slotTime === slotTime)
        if (!sourceQuarter) {
          rejectedCandidates.push({
            type: 'half_hour',
            tradingDate,
            slotTime,
            reason: 'missing_source_quarter_hour',
          })
          continue
        }

        const derived = this.cloneRecordToSlot(sourceQuarter, 'half_hour', tradingDate, slotTime)
        existingHalfSlots.add(slotTime)
        derivedHalfHourCandidates.push({
          ...derived,
          reason: `derived_from_quarter_hour_${sourceQuarter.slotTime}`,
        })
      }
    }

    return {
      normalizedQuarterCandidates,
      derivedHalfHourCandidates,
      rejectedCandidates,
      reason: 'memory_only_repair_candidates',
      normalizedQuarter: normalizedQuarterCandidates.length,
      createdHalfHour: derivedHalfHourCandidates.length,
      skipped: rejectedCandidates.length,
    }
  }

  async syncPrimarySnapshotsToCloud(options?: {
    overwrite?: boolean
    limit?: number
    tradingDate?: string
    startDate?: string
    endDate?: string
  }) {
    const result = await this.snapshotBackupSync.syncPrimaryToCloud(options)
    if (options?.tradingDate) {
      const syncedState = this.backupSyncStateStore.get(options.tradingDate)
      if (result.queued > 0 || syncedState?.cloudBundleUploadedAt) {
        this.lastCloudSyncTradingDate = options.tradingDate
      }
    }
    return result
  }

  async saveFiveMinuteSnapshot(snapshotTime: Date = new Date()): Promise<boolean> {
    try {
      if (!this.isSnapshotCaptureAllowed('five_minute', snapshotTime)) {
        this.logSnapshotCaptureSkipped('five_minute', snapshotTime)
        return false
      }
      const recordId = buildSnapshotId('five_minute', toLocalTradingDate(snapshotTime), toLocalSlotTime(snapshotTime))
      const existing = await this.getSnapshotById(recordId)
      if (existing) return false
      const snapshot = {
        timestamp: snapshotTime.getTime(),
        type: 'five_minute',
        hotlist: this.getBuildContext().stocks.slice(0, 100).map((stock, index) => ({
          code: stock.code,
          name: stock.name,
          rank: index + 1,
          price: stock.price,
          change: stock.change,
        })),
      }
      const record = this.createManagedSnapshotRecord('five_minute', snapshotTime, snapshot)
      return this.saveSnapshotRecord(record)
    } catch (error) {
      this.logger.error('[DataLayer] 保存5分钟快照失败:', error)
      return false
    }
  }

  startTimer() {
    if (this.timer) return
    this.timer = setInterval(() => {
      void this.scheduleSnapshotSweep(new Date())
    }, 1000)
  }

  stopTimer() {
    this.stop()
  }

  private async ensurePersistentStorage(): Promise<void> {
    if (this.persistRequested || typeof navigator === 'undefined') return
    this.persistRequested = true
    try {
      const storageApi = (navigator as any).storage
      if (!storageApi?.persist) return
      const persisted = await storageApi.persist()
      this.logger.log(`[DataLayer] Storage persistence status: ${persisted ? 'granted' : 'not granted'}`)
    } catch (error) {
      this.logger.warn('[DataLayer] Failed to request persistent storage:', error)
    }
  }

  private async openBackupBucket(): Promise<any | null> {
    const manager = this.getStorageBucketManager()
    if (!manager?.open) return null
    try {
      const bucket = await manager.open(this.backupBucketName, { persisted: true, durability: 'strict' })
      if (!this.backupBucketPersistRequested && typeof bucket?.persist === 'function') {
        this.backupBucketPersistRequested = true
        try {
          await bucket.persist()
        } catch (persistError) {
          this.logger.warn('[DataLayer] Bucket persist request failed:', persistError)
        }
      }
      return bucket
    } catch (error) {
      this.logger.warn('[DataLayer] Storage Buckets unavailable:', error)
      return null
    }
  }

  private async createBucketBackupSnapshotStore(): Promise<SnapshotStore | null> {
    const bucket = await this.openBackupBucket()
    if (!bucket?.indexedDB) return null
    return new SnapshotStore({
      dbName: this.bucketBackupDbName,
      dbVersion: this.backupDbVersion,
      storeName: this.backupStoreName,
      factoryProvider: () => bucket.indexedDB,
    })
  }

  private async createBucketBackupProjectionWriter(): Promise<SnapshotProjectionWriter | null> {
    const bucket = await this.openBackupBucket()
    if (!bucket?.indexedDB) return null
    return new SnapshotProjectionWriter({
      dbName: this.bucketBackupDbName,
      dbVersion: this.backupDbVersion,
      snapshotStoreName: this.backupStoreName,
      factoryProvider: () => bucket.indexedDB,
    })
  }

  private async createBucketBackupFrameStore(): Promise<SnapshotFrameStore | null> {
    const bucket = await this.openBackupBucket()
    if (!bucket?.indexedDB) return null
    return new SnapshotFrameStore({
      dbName: this.bucketBackupDbName,
      dbVersion: this.backupDbVersion,
      snapshotStoreName: this.backupStoreName,
      factoryProvider: () => bucket.indexedDB,
    })
  }

  private async createBucketBackupStockRowStore(): Promise<SnapshotStockRowStore | null> {
    const bucket = await this.openBackupBucket()
    if (!bucket?.indexedDB) return null
    return new SnapshotStockRowStore({
      dbName: this.bucketBackupDbName,
      dbVersion: this.backupDbVersion,
      snapshotStoreName: this.backupStoreName,
      factoryProvider: () => bucket.indexedDB,
    })
  }

  private async createBucketBackupSectorRowStore(): Promise<SnapshotSectorRowStore | null> {
    const bucket = await this.openBackupBucket()
    if (!bucket?.indexedDB) return null
    return new SnapshotSectorRowStore({
      dbName: this.bucketBackupDbName,
      dbVersion: this.backupDbVersion,
      snapshotStoreName: this.backupStoreName,
      factoryProvider: () => bucket.indexedDB,
    })
  }

  private async createLegacyBucketBackupSnapshotStore(): Promise<SnapshotStore | null> {
    const bucket = await this.openBackupBucket()
    if (!bucket?.indexedDB) return null
    return new SnapshotStore({
      dbName: this.legacyBackupDbName,
      dbVersion: this.backupDbVersion,
      storeName: this.backupStoreName,
      factoryProvider: () => bucket.indexedDB,
    })
  }

  private async cleanupLegacyPlainBackupDatabase(): Promise<void> {
    if (typeof indexedDB?.deleteDatabase !== 'function') return

    try {
      await new Promise<void>((resolve, reject) => {
        const request = indexedDB.deleteDatabase(this.legacyBackupDbName)
        request.onerror = () => reject(request.error)
        request.onblocked = () =>
          this.logger.warn?.('[DataLayer] Legacy plain backup delete blocked:', this.legacyBackupDbName)
        request.onsuccess = () => resolve()
      })
    } catch (error) {
      this.logger.warn?.('[DataLayer] Legacy plain backup cleanup skipped:', error)
    }
  }

  private async migrateLegacyBucketBackupDatabase(): Promise<void> {
    if (this.bucketBackupDbName === this.legacyBackupDbName) return
    const bucket = await this.openBackupBucket()
    if (!bucket?.indexedDB?.deleteDatabase) return

    try {
      const legacyStore = await this.createLegacyBucketBackupSnapshotStore()
      const targetStore = await this.createBucketBackupSnapshotStore()
      if (!legacyStore || !targetStore) return

      const legacyRecords = await legacyStore.getAll()
      if (legacyRecords.length > 0) {
        for (const record of legacyRecords) {
          const existing = await targetStore.getById(record.id)
          if (!existing) {
            await targetStore.put(record)
          }
        }
        this.logger.log?.(
          `[DataLayer] Bucket backup migration completed: legacy=${legacyRecords.length}, targetDb=${this.bucketBackupDbName}`,
        )
      }

      await new Promise<void>((resolve, reject) => {
        const request = bucket.indexedDB.deleteDatabase(this.legacyBackupDbName)
        request.onerror = () => reject(request.error)
        request.onblocked = () =>
          this.logger.warn?.('[DataLayer] Legacy bucket backup delete blocked:', this.legacyBackupDbName)
        request.onsuccess = () => resolve()
      })
    } catch (error) {
      this.logger.warn?.('[DataLayer] Legacy bucket backup migration skipped:', error)
    }
  }

  private async saveSnapshotRecord(
    record: SnapshotRecord,
    bundle: SnapshotProjectionBundle | null = null,
  ): Promise<boolean> {
    let created = false
    // 写入必须串行，避免同一槽位在定时器和手工触发并发时落出重复记录。
    const task = this.snapshotWriteQueue.catch(() => undefined).then(async () => {
      const existing = await this.snapshotStore.getById(record.id)
      if (existing) {
        await this.replayBackendIngestIfPending(existing)
        return
      }
      await this.ensurePersistentStorage()
      const effectiveBundle = bundle || this.createProjectionBundle(record)
      await this.snapshotProjectionWriter.saveBundle(effectiveBundle)
      await this.pushSnapshotBundleToBackend(record, effectiveBundle)
      // 备份失败不会回滚主库，主库写成功仍然是唯一成功标准。
      void this.snapshotBackupSync.saveToBackups(effectiveBundle).catch((error) => {
        this.logger.warn?.('[DataLayer] Snapshot backup sync failed:', record.id, error)
      })
      const saved = await this.snapshotStore.getById(record.id)
      if (!saved) throw new Error(`snapshot_write_verify_failed:${record.id}`)
      created = true
    })
    this.snapshotWriteQueue = task.then(() => undefined, () => undefined)
    try {
      await task
      return created
    } catch (error) {
      this.logger.error('[DataLayer] Snapshot write queue failed:', record.id, error)
      return false
    }
  }

  private async replayBackendIngestIfPending(record: SnapshotRecord): Promise<void> {
    if (record.type === 'five_minute') return
    const state = this.backupSyncStateStore.get(record.tradingDate)
    const backendIngested = Number(state?.backendIngestedAt) > 0 && !state?.lastBackendIngestError
    if (backendIngested) return

    try {
      await this.pushSnapshotBundleToBackend(record, await this.buildCanonicalPrimaryBundle(record))
    } catch (error) {
      this.logger.warn?.('[DataLayer] Snapshot backend ingest replay failed:', record.id, error)
    }
  }

  private async pushSnapshotBundleToBackend(
    record: SnapshotRecord,
    bundle: SnapshotProjectionBundle,
  ): Promise<void> {
    if (typeof window === 'undefined') return
    if (record.type === 'five_minute') return
    try {
      const dayBundle = {
        version: 'v4' as const,
        tradingDate: record.tradingDate,
        items: [record],
        frames: bundle.frame ? [bundle.frame] : [],
        stockRows: bundle.stockRows || [],
        sectorRows: bundle.sectorRows || [],
      }
      const idempotencyKey = await digestJson({
        snapshotId: record.id,
        tradingDate: record.tradingDate,
        slotTime: record.slotTime,
        timestamp: record.timestamp,
        payload: record.payload,
        frame: bundle.frame,
        stockRows: bundle.stockRows,
        sectorRows: bundle.sectorRows,
      })
      const response = await snapshotBackendIngest.ingestDayBundle(dayBundle, {
        datasetId: 'dragonboard_live',
        idempotencyKey,
      })
      if (!response?.ok) {
        throw new Error(response?.status || 'snapshot_backend_ingest_failed')
      }
      this.backupSyncStateStore.markBackendIngested(record.tradingDate, Date.now())
    } catch (error) {
      this.logger.warn?.('[DataLayer] Snapshot backend ingest failed:', record.id, error)
      this.backupSyncStateStore.markError('backendIngest', record.tradingDate, error)
    }
  }

  private async deleteSnapshotRecord(
    id: string,
    options?: { removeLocalBackups?: boolean; removeBackupState?: boolean },
  ): Promise<boolean> {
    if (!id) return false
    const existing = await this.snapshotStore.getById(id)
    if (!existing) return false

    await Promise.all([
      existing.type === 'five_minute' ? Promise.resolve() : this.snapshotFrameStore.deleteBySnapshotId(id),
      existing.type === 'five_minute' ? Promise.resolve() : this.snapshotStockRowStore.deleteBySnapshotId(id),
      existing.type === 'five_minute' ? Promise.resolve() : this.snapshotSectorRowStore.deleteBySnapshotId(id),
    ])
    await this.snapshotStore.delete(id)

    if (options?.removeLocalBackups) {
      await this.snapshotBackupSync.deleteFromLocalBackups(id)
    }
    if (options?.removeBackupState && existing.tradingDate) {
      this.backupSyncStateStore.remove(existing.tradingDate)
    }
    return true
  }

  private isInvalidRuntimeSnapshot(record: SnapshotRecord): boolean {
    if (!record || record.captureMode === 'restored') return false
    if (record.source && record.source !== 'browser_runtime') return false
    return !this.isSnapshotCaptureAllowed(record.type, this.resolveRecordSnapshotTime(record))
  }

  private resolveRecordSnapshotTime(record: SnapshotRecord): Date {
    const slotDate = record.tradingDate && record.slotTime
      ? new Date(`${record.tradingDate}T${record.slotTime}:00`)
      : null
    if (slotDate && !Number.isNaN(slotDate.getTime())) return slotDate
    return new Date(Number(record.timestamp) || 0)
  }

  private filterSnapshotsByCoverage(
    records: SnapshotRecord[],
    options: SnapshotQueryOptions,
  ): SnapshotRecord[] {
    // 合格与否按 tradingDate 分桶判断；
    // 只要请求类型里有一种缺口超阈值或出现 malformed，该交易日整组样本就会被过滤掉。
    const requestedTypes = this.resolveCoverageRequestedTypes(options)
    if (requestedTypes.length === 0) {
      return this.applySnapshotLimit(records, options.limit)
    }

    const tolerance = Math.max(0, Math.floor(Number(options.coverageTolerance) || 0))
    const recordsByTradingDate = new Map<string, SnapshotRecord[]>()

    records.forEach((record) => {
      if (!record.tradingDate) return
      const bucket = recordsByTradingDate.get(record.tradingDate) || []
      bucket.push(record)
      recordsByTradingDate.set(record.tradingDate, bucket)
    })

    const qualifiedTradingDates = new Set<string>()
    recordsByTradingDate.forEach((tradingDateRecords, tradingDate) => {
      const qualified = requestedTypes.every((type) => {
        const coverage = this.buildCoverageReport(
          type,
          tradingDateRecords.filter((record) => record.type === type),
        )
        return coverage.malformed.length === 0 && coverage.missing.length <= tolerance
      })

      if (qualified) {
        qualifiedTradingDates.add(tradingDate)
      }
    })

    return this.applySnapshotLimit(
      records.filter((record) => qualifiedTradingDates.has(record.tradingDate)),
      options.limit,
    )
  }

  private applySnapshotLimit(records: SnapshotRecord[], limit?: number): SnapshotRecord[] {
    return limit && limit > 0 ? records.slice(0, limit) : records
  }

  private resolveCoverageRequestedTypes(
    options: SnapshotQueryOptions,
  ): RankTrendSnapshotType[] {
    const requestedTypes = options.type ? [options.type] : options.types?.length ? options.types : []
    const coverageTypes = requestedTypes.filter((type): type is RankTrendSnapshotType =>
      isRankTrendSnapshotType(type),
    )

    if (requestedTypes.length > 0) {
      return coverageTypes
    }

    return [...RANK_TREND_SNAPSHOT_TYPES]
  }

  private buildCoverageReport(
    type: RankTrendSnapshotType,
    records: SnapshotRecord[],
  ) {
    // expected 只计算到“当天已观测到的最晚槽位”为止，
    // 这样盘中查看时不会把未来槽位提前算成缺口。
    const expected = getExpectedSlots(type)
    const actual = records.map((record) => record.slotTime)
    const valid = new Set(expected)
    const malformed = actual.filter((slot) => !valid.has(slot))
    const delayed = records
      .filter((record) => record.captureMode === 'delayed')
      .map((record) => record.slotTime)
    const restored = records
      .filter((record) => record.captureMode === 'restored')
      .map((record) => record.slotTime)
    const latestObserved = actual.reduce(
      (latest, slot) => (this.slotTimeToMinutes(slot) > this.slotTimeToMinutes(latest) ? slot : latest),
      '',
    )
    const effectiveExpected = latestObserved
      ? expected.filter((slot) => this.slotTimeToMinutes(slot) <= this.slotTimeToMinutes(latestObserved))
      : expected

    return {
      expected: effectiveExpected,
      actual,
      missing: effectiveExpected.filter((slot) => !actual.includes(slot)),
      malformed,
      delayed,
      restored,
    }
  }

  private findNearestExpectedSlot(
    type: RankTrendIntradaySnapshotType,
    slotTime: string,
    toleranceMinutes: number,
  ): string | null {
    const targetMinutes = this.slotTimeToMinutes(slotTime)
    if (targetMinutes < 0) return null
    const expected = getExpectedSlots(type)
    let nearest = ''
    let nearestDistance = Number.POSITIVE_INFINITY

    for (const candidate of expected) {
      const candidateMinutes = this.slotTimeToMinutes(candidate)
      const distance = Math.abs(candidateMinutes - targetMinutes)
      if (distance < nearestDistance) {
        nearest = candidate
        nearestDistance = distance
      }
    }

    return nearestDistance <= toleranceMinutes ? nearest : null
  }

  private slotTimeToMinutes(slotTime: string): number {
    return slotTimeToMinutes(slotTime)
  }

  private cloneRecordToSlot(
    record: SnapshotRecord,
    type: SnapshotType,
    tradingDate: string,
    slotTime: string,
  ): SnapshotRecord {
    const slotDate = new Date(`${tradingDate}T${slotTime}:00`)
    const payload = JSON.parse(JSON.stringify(record.payload || {}))
    return createSnapshotRecord(type, slotDate, payload, {
      captureMode: record.captureMode,
      capturedAt: record.capturedAt,
      dataTimestamp: record.dataTimestamp,
      delayMs: record.delayMs,
      qualityFlags: record.qualityFlags,
      source: record.source,
    })
  }

  private resolveSnapshotTime(type: SnapshotType, snapshotTime?: Date): Date | null {
    const baseTime = snapshotTime ? new Date(snapshotTime) : new Date()
    const slotTime = findLatestEligibleSnapshotSlot(type, baseTime)
    if (!slotTime) return null

    if (
      snapshotTime &&
      (slotTime.getTime() !== baseTime.getTime() ||
        slotTime.getMinutes() !== baseTime.getMinutes() ||
        slotTime.getHours() !== baseTime.getHours())
    ) {
      this.logger.warn?.(
        `[DataLayer] ${type} snapshot time normalized: requested=${toLocalTradingDate(baseTime)} ${toLocalSlotTime(baseTime)} -> slot=${toLocalTradingDate(slotTime)} ${toLocalSlotTime(slotTime)}`,
      )
    }

    return slotTime
  }
  private scheduleSnapshotSweep(now: Date): void {
    if (this.snapshotSchedulePromise) return
    this.snapshotSchedulePromise = this.runScheduledSnapshotSweep(now).finally(() => {
      this.snapshotSchedulePromise = null
    })
  }

  private async runScheduledSnapshotSweep(now: Date): Promise<void> {
    const candidates = await this.collectPendingSnapshotSlots(now)
    for (const candidate of candidates) {
      await this.saveScheduledSnapshot(candidate.type, candidate.slotTime)
    }
  }

  private async collectPendingSnapshotSlots(now: Date): Promise<Array<{ type: SnapshotType; slotTime: Date }>> {
    const candidates: Array<{ type: SnapshotType; slotTime: Date }> = []
    const types: SnapshotType[] = [...RANK_TREND_SNAPSHOT_TYPES]

    // 每秒扫一次槽位，但真正允许补采的时间范围由各类型 backfill window 控制。
    for (const type of types) {
      const slots = getScheduledSlotsForDate(type, now)
        .filter((slot) => slot.getTime() <= now.getTime())
        .filter((slot) => this.isSnapshotCaptureAllowed(type, slot))
        .sort((left, right) => right.getTime() - left.getTime())

      for (const slotTime of slots) {
        if (!this.isSlotWithinBackfillWindow(type, slotTime, now)) {
          break
        }

        const snapshotId = buildSnapshotId(type, toLocalTradingDate(slotTime), toLocalSlotTime(slotTime))
        const existing = await this.snapshotStore.getById(snapshotId)
        if (!existing) {
          candidates.push({ type, slotTime })
        }
      }
    }

    return candidates.sort((left, right) => left.slotTime.getTime() - right.slotTime.getTime())
  }

  private isSlotWithinBackfillWindow(
    type: SnapshotType,
    slotTime: Date,
    now: Date,
  ): boolean {
    if (slotTime.getTime() > now.getTime()) return false

    const graceMs =
      type === 'quarter_hour'
        ? SnapshotRuntime.QUARTER_HOUR_BACKFILL_WINDOW_MS
        : type === 'half_hour'
          ? SnapshotRuntime.HALF_HOUR_BACKFILL_WINDOW_MS
          : type === 'hourly'
            ? SnapshotRuntime.HOURLY_BACKFILL_WINDOW_MS
            : SnapshotRuntime.DAILY_BACKFILL_WINDOW_MS
    return now.getTime() - slotTime.getTime() <= graceMs
  }

  private isSnapshotCaptureAllowed(type: SnapshotType, snapshotTime: Date): boolean {
    if (!(snapshotTime instanceof Date) || Number.isNaN(snapshotTime.getTime())) return false
    if (type === 'daily') {
      const closeTime = new Date(snapshotTime)
      closeTime.setHours(15, 0, 0, 0)
      return isTradingTime(closeTime)
    }
    return isTradingTime(snapshotTime)
  }

  private logSnapshotCaptureSkipped(type: SnapshotType, snapshotTime: Date): void {
    this.logger.warn?.(
      `[DataLayer] 跳过${type}快照保存：非交易日或非交易时段 ${toLocalTradingDate(snapshotTime)} ${toLocalSlotTime(snapshotTime)}`,
    )
  }

  private async saveScheduledSnapshot(type: SnapshotType, slotTime: Date): Promise<void> {
    if (type === 'quarter_hour') {
      await this.saveQuarterHourSnapshot(slotTime)
      return
    }
    if (type === 'half_hour') {
      await this.saveHalfHourSnapshot(slotTime)
      return
    }
    if (type === 'hourly') {
      await this.saveHourlySnapshot(slotTime)
      return
    }
    if (type === 'daily') {
      await this.saveDailySnapshot(slotTime)
    }
  }

  private async initializeSnapshotGuard(): Promise<void> {
    if (typeof window === 'undefined') return
    setTimeout(() => {
      void this.runSnapshotAutoRecoveryCheck()
    }, 3000)
  }

  private startSnapshotAutoSync() {
    if (this.snapshotSyncTimer || typeof window === 'undefined') return
    // 自动同步分成两条：高频 bucket 补同步 + 收盘后的日 bundle 上传。
    window.setTimeout(() => {
      void this.syncPrimarySnapshotsToBackup({ overwrite: false, limit: 20 })
      void this.runDailyCloudSyncIfDue()
    }, 10000)
    this.snapshotSyncTimer = window.setInterval(() => {
      void this.syncPrimarySnapshotsToBackup({ overwrite: false, limit: 20 })
      void this.runDailyCloudSyncIfDue()
    }, this.syncIntervalMs)
  }

  private async runDailyCloudSyncIfDue(): Promise<void> {
    // 云端正式归档只在 15:30 后触发，但一旦前几天漏传，也要顺手补齐，而不是永远只盯当天。
    const now = new Date()
    const tradingDate = toLocalTradingDate(now)
    const hour = now.getHours()
    const minute = now.getMinutes()
    const due = hour > 15 || (hour === 15 && minute >= 30)

    if (!due) return
    const pendingTradingDates = await this.collectPendingCloudSyncTradingDates(tradingDate)
    if (pendingTradingDates.length === 0) {
      this.lastCloudSyncTradingDate =
        this.backupSyncStateStore.getLatestCloudSyncedTradingDate() || this.lastCloudSyncTradingDate
      this.clearLegacyCloudSyncTradingDatePersistence()
      return
    }

    let syncingTradingDate = ''
    try {
      for (const pendingTradingDate of pendingTradingDates) {
        syncingTradingDate = pendingTradingDate
        const result = await this.syncPrimarySnapshotsToCloud({
          overwrite: false,
          tradingDate: pendingTradingDate,
        })
        const state = this.backupSyncStateStore.get(pendingTradingDate)
        if (!state?.cloudBundleUploadedAt && result.totalPrimary > 0 && result.queued === 0) {
          this.recordCloudBundleUploaded(pendingTradingDate, Date.now())
        }
      }
      this.lastCloudSyncTradingDate =
        this.backupSyncStateStore.getLatestCloudSyncedTradingDate() ||
        pendingTradingDates[pendingTradingDates.length - 1] ||
        tradingDate
      this.clearLegacyCloudSyncTradingDatePersistence()
      this.logger.log?.(
        `[DataLayer] Daily cloud sync completed for ${pendingTradingDates.join(', ')}`,
      )
    } catch (error) {
      this.lastCloudSyncTradingDate = this.backupSyncStateStore.getLatestCloudSyncedTradingDate()
      this.clearLegacyCloudSyncTradingDatePersistence()
      this.logger.warn?.(
        `[DataLayer] Daily cloud sync failed for ${syncingTradingDate || tradingDate}:`,
        error,
      )
    }
  }

  private async collectPendingCloudSyncTradingDates(currentTradingDate: string): Promise<string[]> {
    if (!currentTradingDate) return []
    const pendingByState = this.backupSyncStateStore
      .list(40)
      .filter((item) => item.tradingDate && item.tradingDate <= currentTradingDate)
      .filter((item) => Number(item.bucketSyncedAt) > 0 && !Number(item.cloudBundleUploadedAt))
      .map((item) => item.tradingDate)

    // 状态轻量存储可能因浏览器清理、历史迁移或失败中断缺项；这里从主库最近快照日期再兜一层。
    const recentSnapshots = await this.snapshotStore.list({
      endDate: currentTradingDate,
      allowedCaptureModes: ['real_time', 'delayed', 'restored'],
      sort: 'desc',
      limit: 40 * RANK_TREND_SNAPSHOT_TYPES.length * 20,
    })
    const recentTradingDates = Array.from(
      new Set(recentSnapshots.map((record) => record.tradingDate).filter(Boolean)),
    ).slice(0, 10)
    const cloudSyncedDates = new Set(
      this.backupSyncStateStore
        .list(40)
        .filter((item) => Number(item.cloudBundleUploadedAt) > 0)
        .map((item) => item.tradingDate),
    )
    const pendingByPrimary = recentTradingDates.filter((date) => !cloudSyncedDates.has(date))

    return Array.from(new Set([...pendingByState, ...pendingByPrimary])).sort((left, right) =>
      left.localeCompare(right),
    )
  }

  private createManagedSnapshotRecord(type: SnapshotType, snapshotTime: Date, payload: any): SnapshotRecord {
    const now = Date.now()
    const buildContext = this.getBuildContext()
    const dataTimestamp =
      Number(buildContext.marketData?.timestamp) ||
      Number(payload?.metadata?.timestamp) ||
      Number(payload?.timestamp) ||
      snapshotTime.getTime()
    const delayMs = Math.max(0, now - snapshotTime.getTime())
    const captureMode = delayMs > 30_000 ? 'delayed' : 'real_time'
    const qualityFlags = captureMode === 'delayed' ? ['delayed_capture'] : []

    // captureMode 在落库时一次性定稿，后续正式读取会直接依赖它做样本口径过滤。
    return createSnapshotRecord(type, snapshotTime, payload, {
      captureMode,
      capturedAt: now,
      dataTimestamp,
      delayMs,
      qualityFlags,
      source: 'browser_runtime',
    })
  }

  private createSourceStockMap(buildContext?: SnapshotBuildContext): Map<string, any> | undefined {
    const stocks = Array.isArray(buildContext?.stocks) ? buildContext?.stocks : []
    if (!stocks.length) return undefined
    return new Map(stocks.map((stock: any) => [String(stock.code || ''), stock]))
  }

  private createProjectionBundle(
    record: SnapshotRecord,
    buildContext?: SnapshotBuildContext,
  ): SnapshotProjectionBundle {
    const sourceStocksByCode = this.createSourceStockMap(buildContext)
    return buildCanonicalProjectionBundle(record, {
      sourceStocksByCode,
      buildContext,
    })
  }

  private toRawSnapshotQueryFromFrameQuery(options: SnapshotFrameQueryOptions): SnapshotQueryOptions {
    return {
      type: options.type,
      types: options.types,
      tradingDate: options.tradingDate,
      startDate: options.startDate,
      endDate: options.endDate,
      beforeTradingDate: options.beforeTradingDate,
      allowedCaptureModes: options.allowedCaptureModes,
      excludeRestored: options.excludeRestored,
      sort: options.sort,
      limit: options.limit,
    }
  }

  private toRawSnapshotQueryFromStockQuery(options: SnapshotStockRowQueryOptions): SnapshotQueryOptions {
    return {
      type: options.type,
      types: options.types,
      tradingDate: options.tradingDate,
      startDate: options.startDate,
      endDate: options.endDate,
      beforeTradingDate: options.beforeTradingDate,
      allowedCaptureModes: options.allowedCaptureModes,
      excludeRestored: options.excludeRestored,
      sort: options.sort,
      limit: options.limit,
    }
  }

  private toRawSnapshotQueryFromSectorQuery(options: SnapshotSectorRowQueryOptions): SnapshotQueryOptions {
    return {
      type: options.type,
      types: options.types,
      tradingDate: options.tradingDate,
      startDate: options.startDate,
      endDate: options.endDate,
      beforeTradingDate: options.beforeTradingDate,
      allowedCaptureModes: options.allowedCaptureModes,
      excludeRestored: options.excludeRestored,
      sort: options.sort,
      limit: options.limit,
    }
  }

  private async isProjectionBundleCurrent(snapshotId: string): Promise<boolean> {
    const frame = await this.snapshotFrameStore.getBySnapshotId(snapshotId)
    if (!frame) return false

    const [stockCount, sectorCount] = await Promise.all([
      this.snapshotStockRowStore.countBySnapshotId(snapshotId),
      this.snapshotSectorRowStore.countBySnapshotId(snapshotId),
    ])

    return stockCount === Number(frame.stockRowCount || 0) && sectorCount === Number(frame.sectorRowCount || 0)
  }

  private async buildCanonicalPrimaryBundle(record: SnapshotRecord): Promise<SnapshotProjectionBundle> {
    const [existingStockRows, existingSectorRows] = await Promise.all([
      this.snapshotStockRowStore.list({ snapshotId: record.id, sort: 'asc' }),
      this.snapshotSectorRowStore.list({ snapshotId: record.id, sort: 'asc' }),
    ])

    return buildCanonicalProjectionBundle(record, {
      existingStockRows,
      existingSectorRows,
    })
  }

  private async ensureProjectedRawRecords(options: SnapshotQueryOptions): Promise<void> {
    const rawRecords = await this.listSnapshots({
      ...options,
      requireCoverage: undefined,
      coverageTolerance: undefined,
      limit: undefined,
    })
    const missingBundles: SnapshotProjectionBundle[] = []

    for (const record of rawRecords) {
      if (record.type === 'five_minute') continue
      if (await this.isProjectionBundleCurrent(record.id)) continue
      missingBundles.push(await this.buildCanonicalPrimaryBundle(record))
    }

    if (missingBundles.length > 0) {
      await this.snapshotProjectionWriter.saveBundles(missingBundles)
    }
  }

  private scheduleProjectionBackfill(delayMs = 2_000): void {
    if (typeof window === 'undefined') return
    if (this.projectionBackfillTimer) {
      clearTimeout(this.projectionBackfillTimer)
    }
    this.projectionBackfillTimer = setTimeout(() => {
      if (this.projectionBackfillPromise) return
      this.projectionBackfillPromise = this.runProjectionBackfillPass().finally(() => {
        this.projectionBackfillPromise = null
      })
    }, delayMs)
  }

  private async runProjectionBackfillPass(): Promise<void> {
    const currentMeta =
      (await this.snapshotProjectionMetaStore.get()) ||
      ({
        key: 'global',
        schemaVersion: 1,
        backfillStatus: 'idle',
      } satisfies SnapshotProjectionMeta)

    await this.snapshotProjectionMetaStore.put({
      ...currentMeta,
      backfillStatus: 'running',
      lastBackfillAt: Date.now(),
      lastError: undefined,
    })

    try {
      const records = await this.snapshotStore.list({ sort: 'asc' })
      const pending: SnapshotProjectionBundle[] = []
      let latestProjectedTimestamp = Number(currentMeta.projectedBeforeTimestamp) || 0

      for (const record of records) {
        if (record.type === 'five_minute') continue
        if (await this.isProjectionBundleCurrent(record.id)) {
          latestProjectedTimestamp = Math.max(latestProjectedTimestamp, Number(record.timestamp) || 0)
          continue
        }
        pending.push(await this.buildCanonicalPrimaryBundle(record))
        latestProjectedTimestamp = Math.max(latestProjectedTimestamp, Number(record.timestamp) || 0)
        if (pending.length >= 20) {
          break
        }
      }

      if (pending.length > 0) {
        await this.snapshotProjectionWriter.saveBundles(pending)
      }

      const completed = pending.length < 20
      await this.snapshotProjectionMetaStore.put({
        key: 'global',
        schemaVersion: 1,
        backfillStatus: completed ? 'completed' : 'idle',
        projectedBeforeTimestamp: latestProjectedTimestamp || currentMeta.projectedBeforeTimestamp,
        lastBackfillCursor:
          pending[pending.length - 1]?.record.id || currentMeta.lastBackfillCursor,
        lastBackfillAt: Date.now(),
      })

      if (!completed) {
        this.scheduleProjectionBackfill(500)
      }
    } catch (error) {
      await this.snapshotProjectionMetaStore.put({
        key: 'global',
        schemaVersion: 1,
        backfillStatus: 'error',
        projectedBeforeTimestamp: currentMeta.projectedBeforeTimestamp,
        lastBackfillCursor: currentMeta.lastBackfillCursor,
        lastBackfillAt: Date.now(),
        lastError: error instanceof Error ? error.message : String(error),
      })
      this.logger.warn?.('[DataLayer] Snapshot projection backfill failed:', error)
    }
  }

  private loadCloudSyncTradingDate(): string {
    const syncedTradingDate = this.backupSyncStateStore.getLatestCloudSyncedTradingDate()
    if (syncedTradingDate) return syncedTradingDate
    if (typeof localStorage === 'undefined') return ''
    try {
      return String(localStorage.getItem(SnapshotRuntime.LEGACY_CLOUD_SYNC_STATE_KEY) || '')
    } catch {
      return ''
    }
  }

  private clearLegacyCloudSyncTradingDatePersistence(): void {
    if (typeof localStorage === 'undefined') return
    try {
      localStorage.removeItem(SnapshotRuntime.LEGACY_CLOUD_SYNC_STATE_KEY)
    } catch {
      // ignore persistence failures
    }
  }

  private async resolveOverviewTradingDate(): Promise<string | null> {
    const latestRecord = (await this.listSnapshots({ sort: 'desc', limit: 1 }))[0] || null
    if (latestRecord?.tradingDate) return latestRecord.tradingDate
    return this.backupSyncStateStore.list(1)[0]?.tradingDate || null
  }

  private recordBucketSyncSuccess(tradingDate: string, syncedAt: number): void {
    this.backupSyncStateStore.markBucketSynced(tradingDate, syncedAt)
  }

  private recordBucketSyncError(tradingDate: string, error: unknown): void {
    this.backupSyncStateStore.markError('bucket', tradingDate, error)
  }

  private recordCloudBundleUploaded(tradingDate: string, uploadedAt: number): void {
    this.lastCloudSyncTradingDate = tradingDate
    this.backupSyncStateStore.markCloudBundleUploaded(tradingDate, uploadedAt)
    this.clearLegacyCloudSyncTradingDatePersistence()
  }

  private recordCloudBundleError(tradingDate: string, error: unknown): void {
    this.backupSyncStateStore.markError('cloudBundle', tradingDate, error)
  }

  private downloadTextFile(content: string, filename: string, mimeType: string) {
    const blob = new Blob([content], { type: mimeType })
    const url = URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = filename
    link.click()
    URL.revokeObjectURL(url)
  }
}
