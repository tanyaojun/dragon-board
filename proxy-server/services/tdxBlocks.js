import { mkdir, readdir, readFile, stat, writeFile } from 'node:fs/promises'
import { basename, dirname, extname, isAbsolute, join, relative, resolve } from 'node:path'

const DEFAULT_TDX_BLOCK_DIR = 'D:\\APP_SOFT\\TDX\\T0002\\blocknew'
export const DUPLICATE_REASON = 'duplicate'

function isLikelyAshareCode(code, marketPrefix = '') {
  if (!/^\d{6}$/.test(code)) return false
  if (code.startsWith('88')) return false
  if (marketPrefix === '1') return code.startsWith('60') || code.startsWith('68')
  if (marketPrefix === '0' || marketPrefix === '3') {
    return code.startsWith('00') ||
      code.startsWith('30') ||
      code.startsWith('4') ||
      code.startsWith('8')
  }
  return code.startsWith('00') ||
    code.startsWith('30') ||
    code.startsWith('60') ||
    code.startsWith('68') ||
    code.startsWith('8') ||
    code.startsWith('4')
}

export function normalizeTdxBlockCode(raw) {
  let text = String(raw || '').replace(/\D/g, '')
  let marketPrefix = ''
  if (text.length === 7 && ['0', '1', '3'].includes(text[0])) {
    marketPrefix = text[0]
    text = text.slice(-6)
  } else if (text.length !== 6) {
    return null
  }

  return isLikelyAshareCode(text, marketPrefix) ? text : null
}

export function parseTdxBlockLines(path, lines) {
  const codes = []
  const issues = []
  const seen = new Set()

  lines.forEach((line, index) => {
    const raw = String(line || '').trim()
    if (!raw) return
    const code = normalizeTdxBlockCode(raw)
    if (!code) {
      issues.push({ lineNumber: index + 1, rawLine: raw, reason: 'invalid_code' })
      return
    }
    if (seen.has(code)) {
      issues.push({ lineNumber: index + 1, rawLine: raw, reason: DUPLICATE_REASON })
      return
    }
    seen.add(code)
    codes.push({ rawCode: raw, code })
  })

  if (!codes.length && !issues.length) {
    issues.push({ lineNumber: 0, rawLine: '', reason: 'empty_file' })
  }

  return { path, codes, issues }
}

function getSettingsPath(readConfig) {
  const configured = readConfig?.('TDX_BLOCK_SETTINGS_PATH') || process.env.TDX_BLOCK_SETTINGS_PATH
  if (configured) return resolve(String(configured))
  const appData = readConfig?.('APPDATA') || process.env.APPDATA
  return appData
    ? join(appData, 'DragonBoard', 'YiDongJingLing', 'settings.json')
    : ''
}

async function readDesktopSettings(readConfig) {
  const settingsPath = getSettingsPath(readConfig)
  if (!settingsPath) return {}
  try {
    const content = await readFile(settingsPath, 'utf8')
    const parsed = JSON.parse(content)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

async function readDesktopSettingsWithPath(readConfig) {
  const settingsPath = getSettingsPath(readConfig)
  if (!settingsPath) return { settingsPath: '', settings: {} }
  try {
    const content = await readFile(settingsPath, 'utf8')
    const parsed = JSON.parse(content)
    return {
      settingsPath,
      settings: parsed && typeof parsed === 'object' ? parsed : {},
    }
  } catch {
    return { settingsPath, settings: {} }
  }
}

function getSettingsString(settings, pascalName, camelName) {
  const value = settings?.[pascalName] ?? settings?.[camelName]
  return typeof value === 'string' ? value.trim() : ''
}

function getSettingsStringArray(settings, pascalName, camelName) {
  const value = settings?.[pascalName] ?? settings?.[camelName]
  return Array.isArray(value) ? value.filter(item => typeof item === 'string' && item.trim()) : []
}

function resolveBlockDirectory(readConfig, settings) {
  const configured = readConfig?.('TDX_BLOCK_DIR') || process.env.TDX_BLOCK_DIR
  const settingsDirectory = getSettingsString(settings, 'BlockDirectory', 'blockDirectory')
  return resolve(String(configured || settingsDirectory || DEFAULT_TDX_BLOCK_DIR))
}

function resolveRequestedPath(directory, value) {
  const raw = String(value || '').trim()
  if (!raw) return null
  const candidate = isAbsolute(raw) ? resolve(raw) : resolve(directory, raw)
  const relativePath = relative(directory, candidate)
  const insideDirectory = Boolean(relativePath) &&
    !relativePath.startsWith('..') &&
    !isAbsolute(relativePath)
  return insideDirectory && extname(candidate).toLowerCase() === '.blk' ? candidate : null
}

function splitRequestedFiles(files) {
  if (!files) return []
  if (Array.isArray(files)) return files
  return String(files).split(',').map(item => item.trim()).filter(Boolean)
}

function resolveSelectedFiles(directory, settings) {
  return getSettingsStringArray(settings, 'SelectedBlockFiles', 'selectedBlockFiles')
    .map(item => resolveRequestedPath(directory, item))
    .filter(Boolean)
}

function applySelectedFileState(files, selectedFiles) {
  const selectedSet = new Set(selectedFiles.map(file => resolve(file).toLowerCase()))
  return files.map(file => ({
    ...file,
    selected: selectedSet.has(resolve(file.path).toLowerCase()),
  }))
}

async function parseBlockFile(path) {
  const content = await readFile(path, 'utf8')
  const result = parseTdxBlockLines(path, content.split(/\r?\n/))
  const info = await stat(path)
  return {
    result,
    file: {
      name: basename(path),
      path,
      length: info.size,
      lastWriteTime: info.mtime.toISOString(),
      stockCount: result.codes.length,
      issueCount: result.issues.length,
    },
  }
}

export async function scanTdxBlockFiles(options = {}) {
  const settings = await readDesktopSettings(options.readConfig)
  const directory = resolveBlockDirectory(options.readConfig, settings)
  const selectedFiles = resolveSelectedFiles(directory, settings)
  const entries = await readdir(directory, { withFileTypes: true })
  const files = entries
    .filter(entry => entry.isFile() && entry.name.toLowerCase().endsWith('.blk'))
    .map(entry => join(directory, entry.name))
    .sort((left, right) => basename(left).localeCompare(basename(right), 'zh-CN'))

  const summaries = []
  for (const file of files) {
    const parsed = await parseBlockFile(file)
    summaries.push(parsed.file)
  }

  return { directory, selectedFiles, files: applySelectedFileState(summaries, selectedFiles) }
}

export async function loadTdxBlockCodes(options = {}) {
  const settings = await readDesktopSettings(options.readConfig)
  const directory = resolveBlockDirectory(options.readConfig, settings)
  const requestedFiles = splitRequestedFiles(options.files)
  const requested = requestedFiles
    .map(item => resolveRequestedPath(directory, item))
    .filter(Boolean)
  const hasRequestedFiles = Object.prototype.hasOwnProperty.call(options, 'files') && options.files !== undefined
  const selectedFiles = resolveSelectedFiles(directory, settings)
  const paths = hasRequestedFiles
    ? requested
    : selectedFiles.length
      ? selectedFiles
    : (await readdir(directory, { withFileTypes: true }))
      .filter(entry => entry.isFile() && entry.name.toLowerCase().endsWith('.blk'))
      .map(entry => join(directory, entry.name))

  const mergedCodes = new Set()
  const files = []
  let issueCount = 0
  let duplicateCount = 0

  for (const path of paths.sort((left, right) => basename(left).localeCompare(basename(right), 'zh-CN'))) {
    const { result, file } = await parseBlockFile(path)
    files.push({
      ...file,
      selected: selectedFiles.some(selected => resolve(selected).toLowerCase() === resolve(path).toLowerCase()),
    })
    issueCount += result.issues.length
    duplicateCount += result.issues.filter(issue => issue.reason === DUPLICATE_REASON).length
    result.codes.forEach((item) => {
      if (mergedCodes.has(item.code)) {
        duplicateCount++
      }
      mergedCodes.add(item.code)
    })
  }

  return {
    directory,
    files: hasRequestedFiles ? applySelectedFileState(files, paths) : files,
    selectedFiles: hasRequestedFiles ? paths : selectedFiles,
    codes: Array.from(mergedCodes).sort(),
    issueCount,
    duplicateCount,
  }
}

export async function saveTdxBlockSelection(options = {}) {
  const { settingsPath, settings } = await readDesktopSettingsWithPath(options.readConfig)
  if (!settingsPath) {
    const error = new Error('TDX block settings path is unavailable')
    error.code = 'TDX_BLOCK_SETTINGS_PATH_MISSING'
    throw error
  }

  const directory = resolveBlockDirectory(options.readConfig, settings)
  const selectedFiles = splitRequestedFiles(options.files)
    .map(item => resolveRequestedPath(directory, item))
    .filter(Boolean)
  const nextSettings = {
    ...settings,
    BlockDirectory: directory,
    SelectedBlockFiles: selectedFiles,
  }

  await mkdir(dirname(settingsPath), { recursive: true })
  await writeFile(settingsPath, `${JSON.stringify(nextSettings, null, 2)}\n`, 'utf8')
  return {
    directory,
    selectedFiles,
  }
}
