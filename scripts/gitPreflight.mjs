import { execFileSync } from 'node:child_process'
import { readFileSync } from 'node:fs'

const ZERO_SHA = /^0+$/
const MAX_FILE_BYTES = 50 * 1024 * 1024
const WARN_FILE_BYTES = 10 * 1024 * 1024
const FORBIDDEN_PATHS = [
  '.tmp/',
  'node_modules/',
  'dist/',
  'dist-ssr/',
  'coverage/',
  'playwright-report/',
  'test-results/',
]
const FORBIDDEN_EXTENSIONS = ['.exe', '.pdb']
const ALLOWED_VSCODE_FILES = new Set(['.vscode/extensions.json'])

function git(args, options = {}) {
  return execFileSync('git', args, {
    encoding: 'utf8',
    stdio: ['pipe', 'pipe', options.ignoreError ? 'ignore' : 'pipe'],
    ...options,
  }).trim()
}

function gitMaybe(args) {
  try {
    return git(args, { ignoreError: true })
  } catch {
    return ''
  }
}

function fail(message) {
  console.error(`\n[git-preflight] ${message}`)
  process.exitCode = 1
}

function warn(message) {
  console.warn(`[git-preflight] warning: ${message}`)
}

function normalizePath(path) {
  return path.replace(/\\/g, '/')
}

function isForbiddenPath(path) {
  const normalized = normalizePath(path)
  if (normalized.startsWith('.vscode/')) {
    return !ALLOWED_VSCODE_FILES.has(normalized)
  }
  return FORBIDDEN_PATHS.some((prefix) => normalized === prefix.slice(0, -1) || normalized.startsWith(prefix))
}

function hasForbiddenExtension(path) {
  const normalized = normalizePath(path).toLowerCase()
  return FORBIDDEN_EXTENSIONS.some((extension) => normalized.endsWith(extension))
}

function formatSize(bytes) {
  return `${(bytes / 1024 / 1024).toFixed(2)}MB`
}

function parseLsFiles(output) {
  if (!output) return []
  return output.split(/\r?\n/).filter(Boolean).map(normalizePath)
}

function parseRevListObjects(output) {
  if (!output) return []
  return output
    .split(/\r?\n/)
    .filter(Boolean)
    .map((line) => {
      const [sha, ...pathParts] = line.split(' ')
      return { sha, path: normalizePath(pathParts.join(' ')) }
    })
    .filter((entry) => entry.path)
}

function blobSize(sha) {
  const size = gitMaybe(['cat-file', '-s', sha])
  return /^\d+$/.test(size) ? Number(size) : 0
}

function checkTrackedFiles() {
  const tracked = parseLsFiles(gitMaybe(['ls-files']))
  const forbidden = tracked.filter(isForbiddenPath)
  if (forbidden.length) {
    fail(`当前索引仍跟踪了不应入库的路径:\n${forbidden.slice(0, 30).join('\n')}`)
  }

  const forbiddenBinary = tracked.filter(hasForbiddenExtension)
  if (forbiddenBinary.length) {
    fail(`当前索引仍跟踪了本地二进制/调试产物:\n${forbiddenBinary.slice(0, 30).join('\n')}`)
  }

  for (const path of tracked) {
    const object = gitMaybe(['ls-files', '-s', '--', path]).split(/\s+/)[1]
    if (!object) continue
    const size = blobSize(object)
    if (size > MAX_FILE_BYTES) {
      fail(`已跟踪文件超过 ${formatSize(MAX_FILE_BYTES)}: ${path} (${formatSize(size)})`)
    } else if (size > WARN_FILE_BYTES) {
      warn(`已跟踪文件较大: ${path} (${formatSize(size)})`)
    }
  }
}

function checkStagedFiles() {
  const staged = parseLsFiles(gitMaybe(['diff', '--cached', '--name-only']))
  const forbidden = staged.filter((path) => isForbiddenPath(path) || hasForbiddenExtension(path))
  if (forbidden.length) {
    fail(`暂存区包含不应提交的文件:\n${forbidden.join('\n')}`)
  }
}

function readPrePushRanges() {
  if (process.stdin.isTTY) return []

  const input = readFileSync(0, 'utf8').trim()
  if (!input) return []

  return input
    .split(/\r?\n/)
    .map((line) => line.trim().split(/\s+/))
    .filter((parts) => parts.length >= 4)
    .map(([localRef, localSha, remoteRef, remoteSha]) => ({ localRef, localSha, remoteRef, remoteSha }))
}

function getManualRanges() {
  const upstream = gitMaybe(['rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'])
  if (!upstream) return []
  const head = gitMaybe(['rev-parse', 'HEAD'])
  return [{ localRef: 'HEAD', localSha: head, remoteRef: upstream, remoteSha: upstream }]
}

function rangeSpec(range) {
  if (!range.localSha || ZERO_SHA.test(range.localSha)) return ''
  if (!range.remoteSha || ZERO_SHA.test(range.remoteSha)) return range.localSha
  if (/^[0-9a-f]{40}$/i.test(range.remoteSha)) return `${range.remoteSha}..${range.localSha}`
  return `${range.remoteSha}..${range.localSha}`
}

function checkPushRange(range) {
  const spec = rangeSpec(range)
  if (!spec) return

  const objects = parseRevListObjects(gitMaybe(['rev-list', '--objects', spec]))
  const forbiddenPaths = objects.filter((entry) => isForbiddenPath(entry.path) || hasForbiddenExtension(entry.path))
  if (forbiddenPaths.length) {
    fail(
      `待推送历史包含不应入库的路径 (${range.localRef} -> ${range.remoteRef}):\n` +
        forbiddenPaths
          .slice(0, 40)
          .map((entry) => entry.path)
          .join('\n'),
    )
  }

  for (const entry of objects) {
    const size = blobSize(entry.sha)
    if (size > MAX_FILE_BYTES) {
      fail(`待推送历史包含超过 ${formatSize(MAX_FILE_BYTES)} 的文件: ${entry.path} (${formatSize(size)})`)
    } else if (size > WARN_FILE_BYTES) {
      warn(`待推送历史包含较大文件: ${entry.path} (${formatSize(size)})`)
    }
  }
}

function main() {
  console.log('[git-preflight] checking workspace and push history...')

  checkTrackedFiles()
  checkStagedFiles()

  const ranges = readPrePushRanges()
  const rangesToCheck = ranges.length ? ranges : getManualRanges()
  for (const range of rangesToCheck) {
    checkPushRange(range)
  }

  if (process.exitCode) {
    console.error('\n[git-preflight] failed. Stop syncing and ask Codex to inspect the repository.')
    process.exit(process.exitCode)
  }

  console.log('[git-preflight] ok')
}

main()
