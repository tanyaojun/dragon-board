import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'

import { describe, expect, test } from 'vitest'

const srcRoot = join(process.cwd(), 'src')

function collectSourceFiles(dir: string): string[] {
  const files: string[] = []
  for (const entry of readdirSync(dir)) {
    const fullPath = join(dir, entry)
    const stat = statSync(fullPath)
    if (stat.isDirectory()) {
      if (entry === 'devtools') continue
      files.push(...collectSourceFiles(fullPath))
      continue
    }
    if (/\.(ts|vue)$/.test(entry)) files.push(fullPath)
  }
  return files
}

describe('architecture boundaries', () => {
  test('uses the unified AppEvents export instead of src/types/events', () => {
    const legacyEventsImport = /from\s+['"][^'"]*types\/events['"]/
    const offenders = collectSourceFiles(srcRoot)
      .filter((file) => !file.endsWith(join('types', 'events.ts')))
      .filter((file) => !file.includes(`${join('src', 'services', '__tests__')}`))
      .filter((file) => legacyEventsImport.test(readFileSync(file, 'utf8').replace(/\\/g, '/')))
      .map((file) => relative(process.cwd(), file))

    expect(offenders).toEqual([])
  })

  test('keeps DataTable free of direct DataLayer reads', () => {
    const dataTablePath = join(srcRoot, 'components', 'common', 'DataTable.vue')
    const source = readFileSync(dataTablePath, 'utf8')

    expect(source).not.toContain("from '../../services/DataLayer'")
    expect(source).not.toContain('dataLayer.')
    expect(source).toMatch(/const getStockThemes[\s\S]*stock\.tags[\s\S]*removeDuplicateThemes/)
  })

  test('keeps JxbkThemeFeed from dynamically importing ThemeFacade', () => {
    const feedPath = join(srcRoot, 'services', 'theme', 'JxbkThemeFeed.ts')
    const source = readFileSync(feedPath, 'utf8')

    expect(source).not.toContain("import('./ThemeFacade')")
    expect(source).not.toContain('import("./ThemeFacade")')
  })
})
