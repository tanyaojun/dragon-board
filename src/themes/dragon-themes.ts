// 龙族主题配置
export const dragonThemes = [
  {
    id: 'qiniu',
    name: '囚牛',
    icon: '🎵',
    element: '木',
    personality: ['优雅', '敏锐', '艺术'],
    colors: {
      primary: '#8E44AD',
      secondary: '#9B59B6',
      accent: '#F1C40F'
    },
    suitable: ['文化传媒', '音乐产业', '艺术品'],
    power: {
      name: '音波探测',
      description: '能听到市场的细微波动',
      effect: '提前感知板块轮动'
    }
  },
  {
    id: 'yazi',
    name: '睚眦',
    icon: '⚔️',
    element: '金',
    personality: ['好战', '果断', '勇猛'],
    colors: {
      primary: '#C0392B',
      secondary: '#E74C3C',
      accent: '#F39C12'
    },
    suitable: ['军工', '机械', '资源'],
    power: {
      name: '必杀一击',
      description: '捕捉最强龙头',
      effect: '精准识别主升浪'
    }
  },
  {
    id: 'chaofeng',
    name: '嘲风',
    icon: '⛰️',
    element: '土',
    personality: ['冒险', '探索', '坚韧'],
    colors: {
      primary: '#2C3E50',
      secondary: '#34495E',
      accent: '#E67E22'
    },
    suitable: ['基建', '资源', '周期'],
    power: {
      name: '险峰望远',
      description: '预判顶部风险',
      effect: '提前识别回调信号'
    }
  },
  {
    id: 'pulao',
    name: '蒲牢',
    icon: '🔔',
    element: '金',
    personality: ['警觉', '洪亮', '预警'],
    colors: {
      primary: '#D4AF37',
      secondary: '#C5A028',
      accent: '#F7DC6F'
    },
    suitable: ['券商', '保险', '银行'],
    power: {
      name: '警钟长鸣',
      description: '预警市场风险',
      effect: '提前发出买卖信号'
    }
  },
  {
    id: 'suanni',
    name: '狻猊',
    icon: '🕯️',
    element: '火',
    personality: ['沉稳', '耐心', '持久'],
    colors: {
      primary: '#A0522D',
      secondary: '#8B4513',
      accent: '#CD853F'
    },
    suitable: ['消费', '医药', '食品'],
    power: {
      name: '香火绵长',
      description: '追踪长线趋势',
      effect: '识别慢牛股'
    }
  },
  {
    id: 'bixi',
    name: '赑屃',
    icon: '🐢',
    element: '水',
    personality: ['稳重', '承载', '坚韧'],
    colors: {
      primary: '#5D6D7E',
      secondary: '#4A5A6A',
      accent: '#B7956D'
    },
    suitable: ['公用事业', '交运', '基建'],
    power: {
      name: '负重致远',
      description: '支撑大资金运作',
      effect: '识别机构重仓'
    }
  },
  {
    id: 'bian',
    name: '狴犴',
    icon: '⚖️',
    element: '金',
    personality: ['公正', '明察', '决断'],
    colors: {
      primary: '#2E86C1',
      secondary: '#1F618D',
      accent: '#F4D03F'
    },
    suitable: ['监管', '法务', '审计'],
    power: {
      name: '明察秋毫',
      description: '识别异常交易',
      effect: '预警庄股操纵'
    }
  },
  {
    id: 'fuxi',
    name: '负屃',
    icon: '📜',
    element: '木',
    personality: ['文雅', '博学', '细致'],
    colors: {
      primary: '#1ABC9C',
      secondary: '#16A085',
      accent: '#F1C40F'
    },
    suitable: ['教育', '出版', '软件'],
    power: {
      name: '文采风流',
      description: '深度研报分析',
      effect: '提取关键信息'
    }
  },
  {
    id: 'chiwen',
    name: '螭吻',
    icon: '🔥',
    element: '火',
    personality: ['热情', '奔放', '激进'],
    colors: {
      primary: '#E67E22',
      secondary: '#D35400',
      accent: '#F7DC6F'
    },
    suitable: ['新能源', '科技', '题材'],
    power: {
      name: '吞火吐焰',
      description: '捕捉热点爆发',
      effect: '识别主升浪启动'
    }
  }
]

// 五行相生相克
export const fiveElements = {
  '木': { birth: '火', kill: '土', friends: ['水', '木'] },
  '火': { birth: '土', kill: '金', friends: ['木', '火'] },
  '土': { birth: '金', kill: '水', friends: ['火', '土'] },
  '金': { birth: '水', kill: '木', friends: ['土', '金'] },
  '水': { birth: '木', kill: '火', friends: ['金', '水'] }
}