// src/constants/themes.ts

import type { ThemeConfig, ThemeType } from '@/types/theme'

export const THEMES: Record<ThemeType, ThemeConfig> = {
  dark: {
    name: '暗黑',
    icon: '🌙',
    colors: {
      '--bg-primary': '#1a1a1a',
      '--bg-secondary': '#2d2d2d',
      '--bg-header': '#333333',
      '--bg-hover': '#404040',
      '--border-color': '#4a4a4a',
      '--text-primary': '#e0e0e0',
      '--text-secondary': '#a0a0a0',
      '--text-title': '#ffffff',
      '--color-up': '#ff6b81',
      '--color-down': '#7bed9f',
      '--color-highlight': '#ffb142',
      '--color-link': '#5dade2',
      '--color-leader-total': '#ffd700',
      '--color-leader-sector': '#5dade2',
      '--color-leader-continuous': '#e74c3c',
      '--color-leader-middle': '#9b59b6',
      '--color-leader-emotion': '#f39c12'
    }
  },
  light: {
    name: '明亮',
    icon: '☀️',
    colors: {
      '--bg-primary': '#f5f5f7',
      '--bg-secondary': '#e8e8ed',
      '--bg-header': '#e0e0e6',
      '--bg-hover': '#d8d8e0',
      '--border-color': '#d0d0d7',
      '--text-primary': '#2c3e50',
      '--text-secondary': '#5a6a7a',
      '--text-title': '#1e2b3a',
      '--color-up': '#ff4757',
      '--color-down': '#2ed573',
      '--color-highlight': '#ffa502',
      '--color-link': '#3498db',
      '--color-leader-total': '#b8860b',
      '--color-leader-sector': '#3a6ea5',
      '--color-leader-continuous': '#b84a4a',
      '--color-leader-middle': '#8a5f9e',
      '--color-leader-emotion': '#c97c3b'
    }
  },
  matrix: {
    name: '矩阵',
    icon: '💚',
    colors: {
      '--bg-primary': '#0c0c0c',
      '--bg-secondary': '#1a1a1a',
      '--bg-header': '#2a2a2a',
      '--bg-hover': '#3a3a3a',
      '--border-color': '#3a3a3a',
      '--text-primary': '#00ff00',
      '--text-secondary': '#00cc00',
      '--text-title': '#00ff00',
      '--color-up': '#00ff00',
      '--color-down': '#ff0000',
      '--color-highlight': '#ffff00',
      '--color-link': '#00ffff',
      '--color-leader-total': '#ffff00',
      '--color-leader-sector': '#00ffff',
      '--color-leader-continuous': '#ff00ff',
      '--color-leader-middle': '#00ff00',
      '--color-leader-emotion': '#ffaa00'
    }
  },
  cream: {
    name: '淡黄',
    icon: '🟨',
    colors: {
      '--bg-primary': '#fef7e9',
      '--bg-secondary': '#fdf0d8',
      '--bg-header': '#fae8c8',
      '--bg-hover': '#f5deb3',
      '--border-color': '#dac292',
      '--text-primary': '#5d3a1a',
      '--text-secondary': '#8b5a2b',
      '--text-title': '#4a2c0d',
      '--color-up': '#c44b4b',
      '--color-down': '#2e8b57',
      '--color-highlight': '#d68b2c',
      '--color-link': '#c97c3b',
      '--color-leader-total': '#b8860b',
      '--color-leader-sector': '#3a6ea5',
      '--color-leader-continuous': '#b84a4a',
      '--color-leader-middle': '#8a5f9e',
      '--color-leader-emotion': '#c97c3b'
    }
  }
} as const  // 添加 as const 确保类型推断