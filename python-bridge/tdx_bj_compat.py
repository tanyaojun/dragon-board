"""北交所（920 号段）行情兼容层：运行时 patch mootdx/tdxpy 的能力缺口。

背景（2026-08-06）：
- 通达信协议本身支持北交所行情（实测：市场 2 + 920299 返回完整真实行情，含五档/量额），
  但 Python 库未实现/未识别：
  * mootdx.get_stock_market 不识别 920 号段 → 920 被映射到沪市(1) → 服务器返回错误条目
    （如 600839）→ bridge 产生 missing=920299 缺股警告；
  * tdxpy.get_security_type 无市场 2 分支、SECURITY_COEFFICIENT 无北交所类型 →
    对 920 抛 NotImplementedError（tdxpy ERROR）；
  * tdxpy.get_security_quotes 对 MARKET_BJ 显式拒绝（「此接口暂时不支持北证A股」）。
- 本项目不 fork 依赖、不提交上游 PR：仅在 python-bridge 启动时运行时替换（monkeypatch），
  集中管理、可回退（uninstall_bj_compat() 或删除本模块并移除 main.py 的调用），
  pip 重装/升级不影响。
- 范围：只支持 920 新号段（83/87/43 老号段实测服务器端已失效/已转码，不处理）。

用法：main.py 模块顶部（import mootdx/tdxpy 之后）调用 install_bj_compat()。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_installed = False
_ORIGINALS: dict[str, Any] = {}

_BJ_CODE_PREFIX = "92"


def install_bj_compat() -> bool:
    """安装北交所 920 号段兼容 patch；幂等，重复调用返回已安装状态。"""
    global _installed
    if _installed:
        return True
    try:
        _patch_mootdx_market()
        _patch_tdxpy_security_type()
        _patch_tdxpy_coefficient()
        _patch_tdxpy_quotes()
        _installed = True
        logger.info("installed BJ(920) compat patch for mootdx/tdxpy")
        return True
    except Exception as error:  # 兼容层失败不影响行情主链路
        logger.warning("failed to install BJ(920) compat patch: %s", error)
        return False


def uninstall_bj_compat() -> None:
    """还原被替换的函数与常量（测试隔离用）；幂等。"""
    global _installed
    if not _installed:
        return
    try:
        import mootdx.quotes
        import mootdx.utils
        import tdxpy.constants
        import tdxpy.helper
        import tdxpy.hq

        for key, module, attr in (
            ("mootdx.utils.get_stock_market", mootdx.utils, "get_stock_market"),
            ("mootdx.quotes.get_stock_market", mootdx.quotes, "get_stock_market"),
            ("tdxpy.helper.get_security_type", tdxpy.helper, "get_security_type"),
            ("tdxpy.hq.get_security_quotes", tdxpy.hq.TdxHq_API, "get_security_quotes"),
        ):
            if key in _ORIGINALS:
                setattr(module, attr, _ORIGINALS[key])
        if _ORIGINALS.get("coefficient_has_bj"):
            tdxpy.constants.SECURITY_COEFFICIENT.pop("BJ_A_STOCK", None)
    finally:
        _ORIGINALS.clear()
        _installed = False


def _patch_mootdx_market() -> None:
    """mootdx: 92 开头代码识别为北交所（市场 2），不再误映射到沪市。"""
    import mootdx.quotes
    import mootdx.utils
    from mootdx.consts import MARKET_BJ

    orig = mootdx.utils.get_stock_market
    _ORIGINALS["mootdx.utils.get_stock_market"] = orig

    def bj_market(symbol="", string=False):
        if isinstance(symbol, str) and symbol.startswith(_BJ_CODE_PREFIX):
            return "bj" if string else MARKET_BJ
        return orig(symbol, string)

    mootdx.utils.get_stock_market = bj_market
    # mootdx.quotes 为绑定导入（from mootdx.utils import get_stock_market），
    # bars() 直接走 quotes 命名空间的引用，需同步替换。
    if getattr(mootdx.quotes, "get_stock_market", None) is orig:
        _ORIGINALS["mootdx.quotes.get_stock_market"] = orig
        mootdx.quotes.get_stock_market = bj_market


def _patch_tdxpy_security_type() -> None:
    """tdxpy: 市场 2 + 92 开头返回北交所 A 股类型，不再抛 NotImplementedError。"""
    import tdxpy.helper as helper

    orig = helper.get_security_type
    _ORIGINALS["tdxpy.helper.get_security_type"] = orig

    def bj_type(market, code):
        code = str(code)
        if market in ["BJ", "bj", 2] and code[:2] in (_BJ_CODE_PREFIX,):
            return "BJ_A_STOCK"
        return orig(market, code)

    helper.get_security_type = bj_type


def _patch_tdxpy_coefficient() -> None:
    """tdxpy: 北交所 A 股价格系数（0.01 元，与沪深 A 股一致）。

    dict 就地修改：helper 绑定的是同一 SECURITY_COEFFICIENT 对象，无需替换引用。
    """
    import tdxpy.constants as constants

    if "BJ_A_STOCK" not in constants.SECURITY_COEFFICIENT:
        constants.SECURITY_COEFFICIENT["BJ_A_STOCK"] = [0.01, 0.01]
        _ORIGINALS["coefficient_has_bj"] = True


def _patch_tdxpy_quotes() -> None:
    """tdxpy: 放开行情快照对北交所（MARKET_BJ）的拒绝，走底层同路径请求。"""
    import tdxpy.hq as hq
    from tdxpy.constants import TDXParams

    orig = hq.TdxHq_API.get_security_quotes
    _ORIGINALS["tdxpy.hq.get_security_quotes"] = orig

    @hq.last_ack_time  # 与原函数一致：刷新心跳 last_ack_time、异常自动重试
    def bj_quotes(self, all_stock=None, code=None):
        bj_list = None
        if isinstance(all_stock, list) and any(
            isinstance(item, (list, tuple)) and item and item[0] == TDXParams.MARKET_BJ
            for item in all_stock
        ):
            bj_list = all_stock
        elif all_stock == TDXParams.MARKET_BJ and code is not None:
            # 单值形式 get_security_quotes(2, code)——原函数同样拒绝，这里转成 list 走北交所路径
            bj_list = [(all_stock, code)]
        if bj_list is not None:
            # 与原函数内部同一路径（GetSecurityQuotesCmd），仅跳过 MARKET_BJ 拒绝；
            # 动态 import 便于测试注入，也避免在模块顶层强依赖该内部模块
            from tdxpy.parser.std.get_security_quotes import GetSecurityQuotesCmd

            cmd = GetSecurityQuotesCmd(self.client, lock=self.lock)
            cmd.setParams(bj_list)
            return cmd.call_api()
        return orig(self, all_stock, code)

    hq.TdxHq_API.get_security_quotes = bj_quotes
