import { apiService } from '../apiService'
import { realtimeSubscriptionRegistry } from '../realtime/RealtimeSubscriptionRegistry'
import { normalizeHotStockCode, type TdxBlockFileSummary } from './hotStockEventTypes'

const TDX_BLOCK_OWNER = 'eventRadar.tdxBlock'
const TDX_BLOCK_FILES_ENDPOINT = '/api/tdx-blocks'
const TDX_BLOCK_CODES_ENDPOINT = '/api/tdx-blocks/codes'
const TDX_BLOCK_SELECTION_ENDPOINT = '/api/tdx-blocks/selection'

export interface TdxBlockPoolSnapshot {
  codes: string[]
  files: TdxBlockFileSummary[]
  selectedFiles: string[]
  directory: string
  issueCount: number
  lastLoadedAt: number | null
  error: string | null
}

export interface TdxBlockPoolRefreshResult extends TdxBlockPoolSnapshot {}

interface TdxBlockPoolApi {
  get: <T = any>(url: string, options?: any) => Promise<T>
  post?: <T = any>(url: string, data?: any, options?: any) => Promise<T>
}

interface TdxBlockPoolRegistry {
  setOwnerCodes: (owner: string, codes: string[]) => void
  clearOwner: (owner: string) => void
}

export interface TdxBlockPoolServiceOptions {
  api?: TdxBlockPoolApi
  registry?: TdxBlockPoolRegistry
  now?: () => number
}

type TdxBlockPoolResponse = {
  ok?: boolean
  data?: {
    codes?: unknown[]
    files?: TdxBlockFileSummary[]
    selectedFiles?: unknown[]
    directory?: string
    issueCount?: number
  }
}

type TdxBlockSelectionResponse = {
  ok?: boolean
  data?: {
    selectedFiles?: unknown[]
  }
}

type TdxBlockPoolRefreshOptions = {
  apply?: boolean
}

function getErrorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error)
}

function normalizeCodes(codes: unknown[]): string[] {
  return [...new Set(codes.map(normalizeHotStockCode).filter(Boolean))].sort()
}

export class TdxBlockPoolService {
  private readonly api: TdxBlockPoolApi
  private readonly registry: TdxBlockPoolRegistry
  private readonly now: () => number
  private selectedFilesInitialized = false
  private snapshot: TdxBlockPoolSnapshot = {
    codes: [],
    files: [],
    selectedFiles: [],
    directory: '',
    issueCount: 0,
    lastLoadedAt: null,
    error: null,
  }

  constructor(options: TdxBlockPoolServiceOptions = {}) {
    this.api = options.api || apiService
    this.registry = options.registry || realtimeSubscriptionRegistry
    this.now = options.now || Date.now
  }

  getSnapshot(): TdxBlockPoolSnapshot {
    return {
      ...this.snapshot,
      codes: [...this.snapshot.codes],
      files: this.snapshot.files.map(file => ({ ...file })),
      selectedFiles: [...this.snapshot.selectedFiles],
    }
  }

  getCodes(): string[] {
    return [...this.snapshot.codes]
  }

  applyCodes(codes: readonly unknown[]) {
    const normalized = normalizeCodes([...codes])
    this.snapshot = {
      ...this.snapshot,
      codes: normalized,
      error: null,
      lastLoadedAt: this.now(),
    }
    this.registry.setOwnerCodes(TDX_BLOCK_OWNER, normalized)
  }

  clear() {
    this.selectedFilesInitialized = false
    this.snapshot = {
      codes: [],
      files: [],
      selectedFiles: [],
      directory: this.snapshot.directory,
      issueCount: 0,
      lastLoadedAt: this.now(),
      error: null,
    }
    this.registry.clearOwner(TDX_BLOCK_OWNER)
  }

  async refresh(options: TdxBlockPoolRefreshOptions = {}): Promise<TdxBlockPoolRefreshResult> {
    try {
      await this.ensureSelectedFilesInitialized()
      const response = await this.api.get<TdxBlockPoolResponse>(this.buildCodesEndpoint(), {
        context: 'tdx',
        timeout: 5000,
        retries: 1,
        silent: true,
      })
      const data = response?.data || {}
      const codes = normalizeCodes(Array.isArray(data.codes) ? data.codes : [])
      const selectedFiles = this.normalizeSelectedFiles(data.selectedFiles)
      this.selectedFilesInitialized = Object.prototype.hasOwnProperty.call(data, 'selectedFiles')
      this.snapshot = {
        codes,
        files: this.mergeFiles(data.files, selectedFiles),
        selectedFiles,
        directory: typeof data.directory === 'string' ? data.directory : '',
        issueCount: Number(data.issueCount) || 0,
        lastLoadedAt: this.now(),
        error: null,
      }
      if (options.apply !== false) {
        this.registry.setOwnerCodes(TDX_BLOCK_OWNER, codes)
      }
      return this.getSnapshot()
    } catch (error) {
      this.snapshot = {
        ...this.snapshot,
        codes: [],
        error: getErrorMessage(error),
        lastLoadedAt: this.now(),
      }
      this.registry.clearOwner(TDX_BLOCK_OWNER)
      throw error
    }
  }

  async refreshFiles(): Promise<TdxBlockPoolSnapshot> {
    const response = await this.api.get<TdxBlockPoolResponse>(TDX_BLOCK_FILES_ENDPOINT, {
      context: 'tdx',
      timeout: 5000,
      retries: 1,
      silent: true,
    })
    const data = response?.data || {}
    const selectedFiles = this.normalizeSelectedFiles(data.selectedFiles)
    this.selectedFilesInitialized = true
    this.snapshot = {
      ...this.snapshot,
      files: this.normalizeFiles(data.files, selectedFiles),
      selectedFiles,
      directory: typeof data.directory === 'string' ? data.directory : this.snapshot.directory,
      error: null,
      lastLoadedAt: this.now(),
    }
    return this.getSnapshot()
  }

  async setSelectedFiles(files: readonly string[]): Promise<TdxBlockPoolRefreshResult> {
    this.selectedFilesInitialized = true
    const selectedFiles = await this.saveSelectedFiles(files)
    this.snapshot = {
      ...this.snapshot,
      selectedFiles,
      files: this.normalizeFiles(this.snapshot.files, selectedFiles),
    }
    return this.refresh()
  }

  clearSubscription() {
    this.registry.clearOwner(TDX_BLOCK_OWNER)
  }

  private buildCodesEndpoint(): string {
    if (this.selectedFilesInitialized) {
      if (!this.snapshot.selectedFiles.length) return `${TDX_BLOCK_CODES_ENDPOINT}?files=`
      const query = new URLSearchParams()
      query.set('files', this.snapshot.selectedFiles.join(','))
      return `${TDX_BLOCK_CODES_ENDPOINT}?${query.toString()}`
    }
    return TDX_BLOCK_CODES_ENDPOINT
  }

  private async ensureSelectedFilesInitialized() {
    if (this.selectedFilesInitialized) return
    await this.refreshFiles()
  }

  private normalizeSelectedFiles(files: unknown): string[] {
    return Array.isArray(files)
      ? files.filter((file): file is string => typeof file === 'string' && Boolean(file.trim()))
      : []
  }

  private async saveSelectedFiles(files: readonly string[]): Promise<string[]> {
    if (!this.api.post) return [...files]
    const response = await this.api.post<TdxBlockSelectionResponse>(
      TDX_BLOCK_SELECTION_ENDPOINT,
      { files: [...files] },
      {
        context: 'tdx',
        timeout: 5000,
        retries: 1,
        silent: true,
      },
    )
    const selectedFiles = this.normalizeSelectedFiles(response?.data?.selectedFiles)
    return selectedFiles
  }

  private normalizeFiles(files: unknown, selectedFiles: unknown): TdxBlockFileSummary[] {
    const selectedList = this.normalizeSelectedFiles(selectedFiles)
    const selected = new Set(selectedList)
    return Array.isArray(files)
      ? files.map(file => {
        const item = file as TdxBlockFileSummary
        const selectedByPath = Boolean(item.path && selected.has(item.path))
        const selectedByName = selected.has(item.name)
        return {
          ...item,
          selected: selectedList.length ? selectedByPath || selectedByName : false,
        }
      })
      : []
  }

  private mergeFiles(files: unknown, selectedFiles: readonly string[]): TdxBlockFileSummary[] {
    const incoming = this.normalizeFiles(files, selectedFiles)
    if (!this.snapshot.files.length) return incoming

    const byKey = new Map<string, TdxBlockFileSummary>()
    for (const file of this.snapshot.files) {
      byKey.set(file.path || file.name, file)
    }
    for (const file of incoming) {
      byKey.set(file.path || file.name, file)
    }
    return this.normalizeFiles([...byKey.values()], selectedFiles)
  }
}

export const tdxBlockPoolService = new TdxBlockPoolService()
