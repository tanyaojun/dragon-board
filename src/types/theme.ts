export type ThemeType = 'dark' | 'light' | 'matrix' | 'cream'

export interface ThemeConfig {
  name: string
  icon: string
  colors: Record<string, string>
}
