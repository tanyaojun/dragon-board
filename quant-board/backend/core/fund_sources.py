"""资金数据源标识常量（统一入口，2026-08-12：消除各处硬编码字符串）。

所有资金行 source / moneyFlowSource 的值一律引用本模块常量，禁止在业务
代码中直接书写字符串字面量。前端对应常量见 src/config/fundSources.ts。
"""

from __future__ import annotations

# 同花顺 mainMonitorDetail L2 主源（权威口径）
FUND_SOURCE_THS_MAIN_MONITOR = "ths_main_monitor"
# akshare 同花顺网页个股资金流（估算口径，stock_fund_flow_individual）
FUND_SOURCE_AKSHARE_THS_INDIVIDUAL = "akshare_ths_individual"
# akshare 东财全市场排行（估算口径，自分页 clist fetch）
FUND_SOURCE_AKSHARE_EASTMONEY_RANK = "akshare_eastmoney_rank"
# 同花顺 L2 主力监控（历史/兼容）
FUND_SOURCE_THS_L2 = "ths_l2"
# QMT L2 实时资金流（历史/兼容）
FUND_SOURCE_QMT_L2 = "qmt_l2"
# 东方财富资金流（历史/兼容）
FUND_SOURCE_EASTMONEY = "eastmoney"
# 前端 TDX 分笔估算兜底
FUND_SOURCE_TDX_ESTIMATE = "tdx_estimate"
# python-bridge L1 分笔自算（仅诊断，不作为资金列来源）
FUND_SOURCE_TDX_TRANSACTION = "tdx_transaction"
# 同花顺网页口径种子（历史方案）
FUND_SOURCE_THS_WEB_SEED = "ths_web_seed"
# 东财网页口径种子（历史方案）
FUND_SOURCE_EASTMONEY_SEED = "eastmoney_seed"

# 资金列（theme-fund 缓存）当前接受的数据源
SUPPORTED_FUND_SOURCES = frozenset(
    {
        FUND_SOURCE_THS_MAIN_MONITOR,
        FUND_SOURCE_AKSHARE_THS_INDIVIDUAL,
    }
)
