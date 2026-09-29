"""proxy-server 数据接口的 Python 迁移实现。

akshare 能覆盖的用 akshare，覆盖不了的用 httpx 直连原上游并自行解析。
东财行情/资金接口（push2）风控限流严重：题材主力资金（2026-XX 用户确认）
经 eastmoney_fund_provider 以独立 URL 直连，内部强制串行 + 请求间隔 +
命中风控立即中止（防封 IP）；除该受限通道外仍不新增其他东财行情调用，
东财热榜保留原直连。
"""
