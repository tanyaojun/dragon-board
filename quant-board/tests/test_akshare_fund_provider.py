from __future__ import annotations

from types import SimpleNamespace

import pandas as pd
import pytest

from backend.akshare_fund_provider import (
    AkshareFundProvider,
    AkshareFundProviderError,
    normalize_code,
    parse_amount,
)


class FakeAkshare:
    def __init__(self, frame=None, error=None, tqdm_module=None) -> None:
        self.frame = frame
        self.error = error
        self.tqdm_module = tqdm_module
        self.calls: list[str] = []
        self.saw_silenced_tqdm: bool | None = None

    def stock_fund_flow_individual(self, symbol: str = "即时"):
        self.calls.append(symbol)
        if self.tqdm_module is not None:
            self.saw_silenced_tqdm = (
                self.tqdm_module.get_tqdm is not self.tqdm_module.original
            )
        if self.error is not None:
            raise self.error
        return self.frame


class FakeTqdmModule:
    def __init__(self) -> None:
        self.original = lambda *args, **kwargs: "original"
        self.get_tqdm = self.original


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


def test_parse_amount_handles_wan_yi_and_invalid() -> None:
    assert parse_amount("-8306.28万") == -83062800.0
    assert parse_amount("3.38亿") == 338000000.0
    assert parse_amount("1,234.5万") == 12345000.0
    assert parse_amount("0") == 0.0
    assert parse_amount("1.26亿") == 126000000.0
    assert parse_amount(None) is None
    assert parse_amount("-") is None
    assert parse_amount("N/A") is None


def test_normalize_code_pads_and_rejects() -> None:
    assert normalize_code(509) == "000509"
    assert normalize_code(300720) == "300720"
    assert normalize_code("000001") == "000001"
    assert normalize_code(688426) == "688426"
    assert normalize_code("SZ000001") == ""
    assert normalize_code(None) == ""
    assert normalize_code("") == ""


def test_fetch_all_parses_full_market_rows() -> None:
    now_ms = 1234567
    ak = FakeAkshare(
        frame=_frame(
            [
                {
                    "序号": 1,
                    "股票代码": 300720,
                    "股票简称": "海川智能",
                    "最新价": 50.8,
                    "涨跌幅": "20.01%",
                    "换手率": "3.72%",
                    "流入资金": "1.26亿",
                    "流出资金": "2.09亿",
                    "净额": "-8306.28万",
                    "成交额": "3.35亿",
                },
                {
                    "序号": 2,
                    "股票代码": 509,
                    "股票简称": "华塑控股",
                    "最新价": 2.92,
                    "涨跌幅": "2.01%",
                    "换手率": "1.00%",
                    "流入资金": "2.28亿",
                    "流出资金": "1.67亿",
                    "净额": "6070.40万",
                    "成交额": "3.95亿",
                },
            ]
        )
    )
    provider = AkshareFundProvider(akshare_module=ak, now_ms=lambda: now_ms)
    batch = provider._fetch_all_sync(session_date="2026-07-30")

    assert ak.calls == ["即时"]
    assert batch.session_date == "2026-07-30"
    assert batch.source == "akshare_ths_individual"
    assert len(batch.rows) == 2
    assert len(batch.failures) == 0

    first = batch.rows[0]
    assert first["code"] == "300720"
    assert first["zlje"] == -83062800.0
    assert first["inflow"] == 126000000.0
    assert first["outflow"] == 209000000.0
    assert first["turnover"] == 335000000.0
    assert first["source"] == "ths_main_monitor"
    assert first["moneyFlowSource"] == "ths_main_monitor"
    assert first["sessionDate"] == "2026-07-30"
    assert first["tradingDate"] == "2026-07-30"
    assert first["sourceTs"] == now_ms

    second = batch.rows[1]
    assert second["code"] == "000509"
    assert second["zlje"] == 60704000.0


def test_fetch_all_records_parse_failures_but_keeps_valid_rows() -> None:
    ak = FakeAkshare(
        frame=_frame(
            [
                {
                    "序号": 1,
                    "股票代码": 300720,
                    "股票简称": "海川智能",
                    "最新价": 50.8,
                    "涨跌幅": "20.01%",
                    "换手率": "3.72%",
                    "流入资金": "1.26亿",
                    "流出资金": "2.09亿",
                    "净额": "-8306.28万",
                    "成交额": "3.35亿",
                },
                {
                    "序号": 2,
                    "股票代码": 300999,
                    "股票简称": "坏数据",
                    "最新价": 10.0,
                    "涨跌幅": "1.00%",
                    "换手率": "1.00%",
                    "流入资金": "-",
                    "流出资金": "-",
                    "净额": "-",
                    "成交额": "-",
                },
                {
                    "序号": 3,
                    "股票代码": None,
                    "股票简称": "无代码",
                    "最新价": 1.0,
                    "涨跌幅": "0.00%",
                    "换手率": "0.00%",
                    "流入资金": "1万",
                    "流出资金": "1万",
                    "净额": "0",
                    "成交额": "2万",
                },
            ]
        )
    )
    provider = AkshareFundProvider(akshare_module=ak, now_ms=lambda: 1)
    batch = provider._fetch_all_sync(session_date="2026-07-30")

    assert len(batch.rows) == 1
    assert batch.rows[0]["code"] == "300720"
    assert len(batch.failures) == 2
    assert all(failure["reason"] == "invalid_stock_code_or_zlje" for failure in batch.failures)
    codes = {failure["code"] for failure in batch.failures}
    assert codes == {"300999", ""}


def test_fetch_all_maps_upstream_errors() -> None:
    import requests

    cases = [
        (requests.exceptions.ConnectTimeout("boom"), "ths_timeout"),
        (
            requests.exceptions.HTTPError("429", response=SimpleNamespace(status_code=429)),
            "ths_rate_limited",
        ),
        (
            requests.exceptions.HTTPError("500", response=SimpleNamespace(status_code=500)),
            "ths_upstream_unavailable",
        ),
        (AttributeError("page_info"), "ths_captcha_required"),
        (ValueError("bad payload"), "ths_invalid_payload"),
        (RuntimeError("boom"), "ths_upstream_unavailable"),
    ]
    for error, expected_code in cases:
        provider = AkshareFundProvider(akshare_module=FakeAkshare(error=error))
        with pytest.raises(AkshareFundProviderError) as exc_info:
            provider._fetch_all_sync(session_date="2026-07-30")
        assert exc_info.value.code == expected_code


def test_fetch_all_rejects_empty_frame() -> None:
    provider = AkshareFundProvider(akshare_module=FakeAkshare(frame=None))
    with pytest.raises(AkshareFundProviderError) as exc_info:
        provider._fetch_all_sync(session_date="2026-07-30")
    assert exc_info.value.code == "ths_invalid_payload"


def test_tqdm_module_silenced_and_restored() -> None:
    tqdm_module = FakeTqdmModule()
    ak = FakeAkshare(
        frame=_frame(
            [
                {
                    "序号": 1,
                    "股票代码": 300720,
                    "股票简称": "海川智能",
                    "最新价": 50.8,
                    "涨跌幅": "20.01%",
                    "换手率": "3.72%",
                    "流入资金": "1.26亿",
                    "流出资金": "2.09亿",
                    "净额": "-8306.28万",
                    "成交额": "3.35亿",
                }
            ]
        ),
        tqdm_module=tqdm_module,
    )
    provider = AkshareFundProvider(akshare_module=ak, tqdm_module=tqdm_module, now_ms=lambda: 1)

    provider._fetch_all_sync(session_date="2026-07-30")

    assert ak.saw_silenced_tqdm is True
    assert tqdm_module.get_tqdm is tqdm_module.original


@pytest.mark.asyncio
async def test_fetch_all_async_wrapper() -> None:
    ak = FakeAkshare(
        frame=_frame(
            [
                {
                    "序号": 1,
                    "股票代码": 300720,
                    "股票简称": "海川智能",
                    "最新价": 50.8,
                    "涨跌幅": "20.01%",
                    "换手率": "3.72%",
                    "流入资金": "1.26亿",
                    "流出资金": "2.09亿",
                    "净额": "-8306.28万",
                    "成交额": "3.35亿",
                }
            ]
        )
    )
    provider = AkshareFundProvider(akshare_module=ak, now_ms=lambda: 1)
    batch = await provider.fetch_all(session_date="2026-07-30")
    assert len(batch.rows) == 1
    assert batch.rows[0]["zlje"] == -83062800.0
