export interface DataSourceConfig {
  name: string;
  enabled: boolean;
  baseURL: string;
  params: Record<string, any>;
  transform: (code: string) => string;
  parseResponse: (data: any, iconv?: any) => any[];
  responseType?: 'json' | 'arraybuffer' | 'text';
  timeout: number;
  priority: number;
  weight: number;
  responsePath: string[];
  fieldMapping: Record<string, string>;
}

export interface StrategyConfig {
  mode: 'sequential' | 'parallel' | 'weighted';
  failThreshold: number;
  healthCheckInterval: number;
}

export interface DataSourcesConfig {
  activeSource: string;
  sources: Record<string, DataSourceConfig>;
  strategy: StrategyConfig;
}

export const dataSourceConfig: DataSourcesConfig = {
  activeSource: 'tencent',
  sources: {
    tencent: {
      name: '腾讯财经',
      enabled: true,
      baseURL: 'http://qt.gtimg.cn/q',
      params: {},
      transform: (code: string) => code.startsWith('6') ? `sh${code}` : `sz${code}`,
      parseResponse: (data: any) => [],
      responseType: 'arraybuffer',
      timeout: 5000,
      priority: 1,
      weight: 1,
      responsePath: ['data', 'data', 'diff'],
      fieldMapping: {}
    }
  },
  strategy: {
    mode: 'sequential',
    failThreshold: 3,
    healthCheckInterval: 60000
  }
};