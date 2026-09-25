// src/data/kpl_theme_data.d.ts
// kpl_theme_data.js 的类型声明（数据文件保持 .js，来源为开盘啦题材列表静态快照）

export interface KplThemeItem {
  ID: string
  Name: string
  ZSCode?: string
  LimitUpCount?: number
  ChangePercent?: number
}

export const KPL_THEME_DATA: KplThemeItem[]
