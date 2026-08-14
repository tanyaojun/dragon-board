"""资金数据源标识常量（统一入口，2026-08-14：废弃种子与不可用源，只保留 L2 + akshare）。

所有资金行 source / moneyFlowSource 的值一律引用本模块常量，禁止在业务
代码中直接书写字符串字面量。前端对应常量见 src/config/fundSources.ts。

数据源口径（2026-08-14 用户确认，两条线）：
- ``ths_main_monitor``：同花顺 mainMonitorDetail L2 主源（权威口径），
  专供行情主页八平台热榜股票列表（约 200-230 只）资金列；
- ``akshare_ths_individual``：akshare 同花顺网页个股资金流
  （stock_fund_flow_individual，估算口径），专供 theme_fund 题材股票列表
  （约 4000 只）资金聚合。

已废弃且实测不可用的历史源一律删除、禁止恢复：
``ths_web_seed`` / ``eastmoney_seed``（种子方案从未启动、首屏占位效果不佳，
冷启动改由 Redis dump.rdb 恢复 L2 数据）、``eastmoney``（东财限流不可用）、
``tdx_transaction``（bridge L1 分笔自算，非全日完整分笔、累计不可靠）、
``tdx_estimate``（前端 TDX 分笔估算兜底）、``ths_l2`` / ``qmt_l2``（历史兼容）。
"""

from __future__ import annotations

# 同花顺 mainMonitorDetail L2 主源（权威口径，行情主页热榜资金列）
FUND_SOURCE_THS_MAIN_MONITOR = "ths_main_monitor"
# akshare 同花顺网页个股资金流（估算口径，theme_fund 题材资金聚合）
FUND_SOURCE_AKSHARE_THS_INDIVIDUAL = "akshare_ths_individual"

# 资金列（theme-fund 缓存）当前接受的数据源
SUPPORTED_FUND_SOURCES = frozenset(
    {
        FUND_SOURCE_THS_MAIN_MONITOR,
        FUND_SOURCE_AKSHARE_THS_INDIVIDUAL,
    }
)
