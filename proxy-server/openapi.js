const jsonResponse = {
  description: 'OK',
  content: {
    'application/json': {
      schema: {
        type: 'object',
        additionalProperties: true,
      },
    },
  },
}

const errorResponse = {
  description: 'Proxy error envelope',
  content: {
    'application/json': {
      schema: { $ref: '#/components/schemas/ErrorEnvelope' },
    },
  },
}

function operation({ method, tag, summary, description, parameters, requestBody }) {
  return {
    [method]: {
      tags: [tag],
      summary,
      description,
      parameters,
      requestBody,
      responses: {
        200: jsonResponse,
        400: errorResponse,
        502: errorResponse,
      },
    },
  }
}

const codesQuery = [
  {
    name: 'codes',
    in: 'query',
    required: true,
    schema: {
      type: 'string',
      example: '000001,600519',
    },
    description: '逗号分隔的 6 位股票代码',
  },
]

const passthroughBody = {
  required: false,
  content: {
    'application/json': {
      schema: {
        type: 'object',
        additionalProperties: true,
      },
    },
  },
}

export function buildOpenApiDocument({ port = 3000 } = {}) {
  return {
    openapi: '3.1.0',
    info: {
      title: 'Dragon Board Proxy API',
      version: '1.0.0',
      description: 'Dragon Board 本地股票数据代理服务 API。',
    },
    servers: [
      {
        url: `http://localhost:${port}`,
        description: 'Local proxy server',
      },
    ],
    tags: [
      { name: 'health', description: '服务健康检查' },
      { name: 'hotlists', description: '八平台热榜代理' },
      { name: 'quotes', description: '行情与主力资金代理' },
      { name: 'market', description: '市场情绪和涨停数据' },
      { name: 'tdx', description: '通达信兼容代理' },
      { name: 'deprecated', description: '兼容旧接口' },
    ],
    paths: {
      '/health': operation({
        method: 'get',
        tag: 'health',
        summary: 'Health check',
        description: '返回代理服务运行状态，不访问外部数据源。',
      }),
      '/api/xueqiu/hot': operation({
        method: 'get',
        tag: 'hotlists',
        summary: '雪球热榜',
      }),
      '/api/cls/hot': operation({
        method: 'get',
        tag: 'hotlists',
        summary: '财联社热榜',
      }),
      '/api/eastmoney/hot': operation({
        method: 'post',
        tag: 'hotlists',
        summary: '东方财富热榜',
        description: '启用 Redis read-through TTL 缓存和 stale fallback。',
        requestBody: passthroughBody,
      }),
      '/api/ths/hot': operation({
        method: 'get',
        tag: 'hotlists',
        summary: '同花顺热榜',
      }),
      '/api/kpl/hot': operation({
        method: 'get',
        tag: 'hotlists',
        summary: '开盘啦热榜',
      }),
      '/api/tdx/hot': operation({
        method: 'post',
        tag: 'hotlists',
        summary: '通达信热榜',
        requestBody: passthroughBody,
      }),
      '/api/tgb/hot': operation({
        method: 'get',
        tag: 'hotlists',
        summary: '淘股吧热榜',
      }),
      '/api/dzh/hot': operation({
        method: 'get',
        tag: 'hotlists',
        summary: '大智慧热榜',
      }),
      '/api/quotes/tencent': operation({
        method: 'get',
        tag: 'quotes',
        summary: '腾讯行情',
        parameters: codesQuery,
      }),
      '/api/quotes/eastmoney': operation({
        method: 'get',
        tag: 'quotes',
        summary: '东方财富行情与主力资金',
        description: '启用 Redis read-through TTL 缓存和 stale fallback。',
        parameters: codesQuery,
      }),
      '/api/quotes/sina': operation({
        method: 'get',
        tag: 'quotes',
        summary: '新浪行情',
        parameters: codesQuery,
      }),
      '/api/quotes/tencent/spk': operation({
        method: 'get',
        tag: 'deprecated',
        summary: '腾讯 SPK 兼容行情',
        parameters: codesQuery,
      }),
      '/api/tdx/{entry}': {
        post: {
          tags: ['tdx'],
          summary: '通达信入口代理',
          parameters: [
            {
              name: 'entry',
              in: 'path',
              required: true,
              schema: { type: 'string', example: 'hq' },
            },
          ],
          requestBody: passthroughBody,
          responses: {
            200: jsonResponse,
            400: errorResponse,
            502: errorResponse,
          },
        },
      },
      '/api/limitup/10jqka': operation({
        method: 'get',
        tag: 'market',
        summary: '同花顺涨停列表',
      }),
      '/api/limitup/detail': operation({
        method: 'get',
        tag: 'deprecated',
        summary: '涨停详情兼容接口',
      }),
      '/api/surge-stock/performance': operation({
        method: 'get',
        tag: 'market',
        summary: '异动股表现',
      }),
      '/api/market/overview': operation({
        method: 'get',
        tag: 'market',
        summary: '市场概览',
      }),
      '/api/sentiment/composite': operation({
        method: 'get',
        tag: 'market',
        summary: '综合情绪',
      }),
      '/api/big-order/main-monitor': operation({
        method: 'get',
        tag: 'market',
        summary: '大单主力监控',
      }),
      '/api/big-order/all-day': operation({
        method: 'get',
        tag: 'market',
        summary: '全天大单',
      }),
      '/api/theme/{id}': {
        get: {
          tags: ['deprecated'],
          summary: '题材详情兼容接口',
          parameters: [
            {
              name: 'id',
              in: 'path',
              required: true,
              schema: { type: 'string' },
            },
          ],
          responses: {
            200: jsonResponse,
            400: errorResponse,
            502: errorResponse,
          },
        },
      },
      '/api/themes/batch': operation({
        method: 'post',
        tag: 'deprecated',
        summary: '批量题材兼容接口',
        requestBody: passthroughBody,
      }),
    },
    components: {
      schemas: {
        ErrorEnvelope: {
          type: 'object',
          required: ['ok', 'errorCode', 'message'],
          properties: {
            ok: { type: 'boolean', const: false },
            degraded: { type: 'boolean' },
            source: { type: 'string' },
            errorCode: { type: 'string' },
            message: { type: 'string' },
          },
        },
      },
    },
  }
}

