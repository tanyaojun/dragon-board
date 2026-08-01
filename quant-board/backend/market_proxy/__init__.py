"""proxy-server 数据接口的 Python 迁移实现。

akshare 能覆盖的用 akshare，覆盖不了的用 httpx 直连原上游并自行解析。
不使用东财行情/资金接口（限流与风控），东财热榜保留原直连。
"""
