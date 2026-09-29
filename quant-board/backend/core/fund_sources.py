"""资金数据源标识常量（统一入口）。

所有资金行 source / moneyFlowSource 的值一律引用本模块常量，禁止在业务
代码中直接书写字符串字面量。前端对应常量见 src/config/fundSources.ts。

数据源口径（两条线）：
- ``ths_main_monitor``：同花顺 mainMonitorDetail L2 主源（权威口径），
  专供行情主页八平台热榜股票列表（约 200-230 只）资金列；
- ``eastmoney_main``：东财 push2 主力资金（ulist.np 批量，httpx 独立 URL
  直连、不走 akshare——东财接口风控限流严重，必须精确控制请求节奏），
  专供 theme_fund 题材股票列表（约 4000 只）资金聚合（默认源，akshare
  同花顺网页口径数据不准，2026-09-29 用户确认切换）；
- ``akshare_ths_individual``：akshare 同花顺网页个股资金流
  （stock_fund_flow_individual，估算口径），题材资金回退源
  （QUANT_BOARD_THEME_FUND_SOURCE=akshare 时启用）。

已废弃且实测不可用的历史源一律删除、禁止恢复：
``ths_web_seed`` / ``eastmoney_seed``（种子方案从未启动、首屏占位效果不佳，
冷启动改由 Redis dump.rdb 恢复 L2 数据）、``eastmoney``（东财限流不可用）、
``tdx_transaction``（bridge L1 分笔自算，非全日完整分笔、累计不可靠）、
``tdx_estimate``（前端 TDX 分笔估算兜底）、``ths_l2`` / ``qmt_l2``（历史兼容）。
"""

from __future__ import annotations

# 同花顺 mainMonitorDetail L2 主源（权威口径，行情主页热榜资金列）
FUND_SOURCE_THS_MAIN_MONITOR = "ths_main_monitor"
# 东财 push2 主力资金（估算口径，theme_fund 题材资金聚合，默认源）
FUND_SOURCE_EASTMONEY_MAIN = "eastmoney_main"
# akshare 同花顺网页个股资金流（估算口径，theme_fund 题材资金回退源）
FUND_SOURCE_AKSHARE_THS_INDIVIDUAL = "akshare_ths_individual"

# 资金列（theme-fund 缓存）当前接受的数据源
SUPPORTED_FUND_SOURCES = frozenset(
    {
        FUND_SOURCE_THS_MAIN_MONITOR,
        FUND_SOURCE_EASTMONEY_MAIN,
        FUND_SOURCE_AKSHARE_THS_INDIVIDUAL,
    }
)

# theme-fund 缓存 hash 后缀（fund_cache 内部结构名，统一从本模块暴露，
# 避免业务代码散落 "latest"/"akshare" 字符串字面量）。
# FUND_HASH_AKSHARE 自 2026-09-29 起承载「题材估算源」hash（默认 eastmoney_main、
# 回退 akshare_ths_individual 都写入该 hash）；Redis key 名保持 "akshare" 不变，
# 避免迁移导致已预热缓存丢失。
FUND_HASH_LATEST = "latest"
FUND_HASH_AKSHARE = "akshare"

# 数据源 → 缓存 hash 路由表（唯一真相源，2026-08-14 收敛）：
# 每个源只写入/读取其专属 hash；加新源只需在此登记一条映射，
# fund_cache 的 put/put_many/get_* 统一按本表路由，不再散落 == 判断。
FUND_SOURCE_HASH: dict[str, str] = {
    FUND_SOURCE_THS_MAIN_MONITOR: FUND_HASH_LATEST,
    FUND_SOURCE_EASTMONEY_MAIN: FUND_HASH_AKSHARE,
    FUND_SOURCE_AKSHARE_THS_INDIVIDUAL: FUND_HASH_AKSHARE,
}
