from __future__ import annotations

import json

import httpx
import pytest

from backend.market_proxy.eastmoney_fund_provider import (
    EM_QUOTE_URL,
    EastmoneyFundBatch,
    EastmoneyFundProvider,
    EastmoneyFundProviderError,
    build_secid,
    get_eastmoney_fund_provider,
    parse_em_number,
)


def _em_payload(diff: list[object]) -> dict:
    return {"rc": 0, "rt": 6, "data": {"diff": diff}}


def _client_with_responses(responses: list[httpx.Response]) -> httpx.Client:
    """按请求顺序返回预设响应的 httpx client（MockTransport）。"""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if not queue:
            return httpx.Response(500, text="unexpected extra request")
        response = queue.pop(0)
        response.request = request
        return response

    return httpx.Client(transport=httpx.MockTransport(handler))


def _provider(client: httpx.Client, **kwargs) -> EastmoneyFundProvider:
    kwargs.setdefault("sleep", lambda _seconds: None)
    kwargs.setdefault("request_interval_seconds", 0.0)
    return EastmoneyFundProvider(client=client, **kwargs)


def test_build_secid_routes_shanghai_and_others() -> None:
    assert build_secid("600000") == "1.600000"
    assert build_secid("688981") == "1.688981"
    assert build_secid("110038") == "1.110038"
    assert build_secid("510300") == "1.510300"
    assert build_secid("000001") == "0.000001"
    assert build_secid("300750") == "0.300750"
    assert build_secid("830799") == "0.830799"
    assert build_secid("430047") == "0.430047"


def test_parse_em_number_missing_not_zero() -> None:
    assert parse_em_number("-") is None
    assert parse_em_number(None) is None
    assert parse_em_number("") is None
    assert parse_em_number("abc") is None
    assert parse_em_number(float("nan")) is None
    assert parse_em_number("1,234.5") == 1234.5
    assert parse_em_number(12.5) == 12.5
    assert parse_em_number(-3) == -3.0


def test_fetch_all_parses_rows_with_honest_missing_fields() -> None:
    diff = [
        {
            "f12": "600000",
            "f14": "浦发银行",
            "f2": 7.5,
            "f3": 1.2,
            "f6": 1234567890.0,
            "f62": -9876543.21,
            "f66": -12345678.0,
            "f69": -5.5,
            "f184": -2.34,
        },
        {
            # 停牌：f62 为 "-"，zlje 缺失必须进 failures，不伪装 0
            "f12": "000001",
            "f14": "平安银行",
            "f62": "-",
            "f66": "-",
            "f69": "-",
            "f184": "-",
        },
        {"f12": "bad", "f62": 1.0},
    ]
    client = _client_with_responses([httpx.Response(200, json=_em_payload(diff))])
    provider = _provider(client)

    batch = provider._fetch_all_sync(["600000", "000001", "badcode"], "2026-07-30")

    assert isinstance(batch, EastmoneyFundBatch)
    assert batch.source == "eastmoney_main"
    assert batch.session_date == "2026-07-30"
    assert batch.request_count == 1
    assert batch.truncated_by == ""
    assert len(batch.rows) == 1
    row = batch.rows[0]
    assert row["code"] == "600000"
    assert row["name"] == "浦发银行"
    assert row["zlje"] == -9876543.21
    assert row["cddje"] == -12345678.0
    assert row["cddjzb"] == -5.5
    assert row["zljzb"] == -2.34
    assert row["turnover"] == 1234567890.0
    # 东财 ulist 无流入/流出分项：诚实缺失，不伪装
    assert row["inflow"] is None and row["outflow"] is None
    assert row["source"] == "eastmoney_main"
    assert row["moneyFlowSource"] == "eastmoney_main"
    assert row["sessionDate"] == "2026-07-30"
    reasons = {failure["reason"] for failure in batch.failures}
    assert reasons == {"invalid_stock_code_or_zlje"}
    assert any(f["reason"] == "invalid_stock_code_or_zlje" and f["code"] == "000001" for f in batch.failures)


def test_fetch_all_splits_batches_and_throttles_between_requests() -> None:
    sleeps: list[float] = []
    requests: list[list[str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        secids = request.url.params["secids"]
        requests.append(secids.split(","))
        return httpx.Response(200, json=_em_payload([]))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = EastmoneyFundProvider(
        client=client,
        sleep=sleeps.append,
        batch_size=2,
        request_interval_seconds=1.5,
    )

    batch = provider._fetch_all_sync(["600000", "000001", "300750", "688981"], "2026-07-30")

    assert len(requests) == 2
    assert requests[0] == ["1.600000", "0.000001"]
    assert requests[1] == ["0.300750", "1.688981"]
    # 批间节流生效：等满最小间隔 + 随机抖动（interval*0.15 内，防精确节拍指纹）
    assert len(sleeps) == 1
    assert 1.4 <= sleeps[0] <= 1.75
    assert batch.request_count == 2


def test_rate_limited_aborts_remaining_batches_and_marks_truncated() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return httpx.Response(429, text="too many requests")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = EastmoneyFundProvider(client=client, sleep=lambda _s: None, batch_size=1)

    batch = provider._fetch_all_sync(["600000", "000001", "300750"], "2026-07-30")

    # 命中风控立即中止：3 批只打了 1 个请求，绝不连续打 API
    assert len(requests) == 1
    assert batch.truncated_by == "em_rate_limited"
    assert batch.rows == []
    assert batch.failures and batch.failures[0]["reason"] == "em_rate_limited"


def test_single_batch_timeout_records_failure_and_continues() -> None:
    responses = [
        httpx.Response(200, json=_em_payload([{"f12": "600000", "f14": "浦发银行", "f62": 100.0}])),
        httpx.Response(200, json=_em_payload([{"f12": "000001", "f62": 200.0}])),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if len(responses) == 2:
            responses.pop(0)
            raise httpx.ConnectTimeout("timed out", request=request)
        response = responses.pop(0)
        response.request = request
        return response

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = EastmoneyFundProvider(client=client, sleep=lambda _s: None, batch_size=1)

    batch = provider._fetch_all_sync(["600000", "000001"], "2026-07-30")

    # 单批网络抖动 ≠ 被封：记录 failure 继续下一批，已成功数据保留
    assert batch.truncated_by == ""
    assert [row["code"] for row in batch.rows] == ["000001"]
    assert batch.failures and batch.failures[0]["reason"] == "em_timeout"


def test_three_consecutive_batch_failures_abort_round() -> None:
    # 非系统性失败（em_invalid_payload）连续 3 批：视为上游异常，中止本轮；
    # 系统性失败（5xx/429）首批即中止，由 test_rate_limited_* 覆盖
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>blocked</html>")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = EastmoneyFundProvider(client=client, sleep=lambda _s: None, batch_size=1)

    batch = provider._fetch_all_sync(["600000", "000001", "300750", "688981"], "2026-07-30")

    assert batch.truncated_by == "em_invalid_payload"
    assert batch.request_count == 3


def test_html_body_counts_as_invalid_payload_failure() -> None:
    client = _client_with_responses(
        [httpx.Response(200, text="<html>captcha</html>")]
    )
    provider = _provider(client)

    batch = provider._fetch_all_sync(["600000"], "2026-07-30")

    # HTTP 200 但 body 非行情结构（常见于风控拦截页）：单批记 failure，
    # 未达连续失败阅值不中止本轮，但绝不伪装成空成功
    assert batch.rows == []
    assert batch.truncated_by == ""
    assert batch.failures and batch.failures[0]["reason"] == "em_invalid_payload"


def test_universe_unavailable_raises_structured_error() -> None:
    provider = EastmoneyFundProvider(
        universe_provider=lambda: [],
        sleep=lambda _s: None,
    )

    with pytest.raises(EastmoneyFundProviderError) as exc_info:
        provider._fetch_all_sync(None, "2026-07-30")

    assert exc_info.value.code == "em_universe_unavailable"


def test_universe_provider_used_when_codes_absent() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["secids"] = request.url.params["secids"]
        return httpx.Response(200, json=_em_payload([]))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = EastmoneyFundProvider(
        universe_provider=lambda: ["600000", "000001"],
        client=client,
        sleep=lambda _s: None,
    )

    batch = provider._fetch_all_sync(None, "2026-07-30")

    assert captured["secids"] == "1.600000,0.000001"
    assert batch.rows == []


def test_request_carries_fltt_np_fields_and_referer() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        captured["referer"] = request.headers.get("referer", "")
        captured["url"] = str(request.url).split("?")[0]
        return httpx.Response(200, json=_em_payload([]))

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = EastmoneyFundProvider(client=client, sleep=lambda _s: None)

    provider._fetch_all_sync(["600000"], "2026-07-30")

    assert captured["url"] == EM_QUOTE_URL
    params = captured["params"]
    assert params["fltt"] == "2"
    assert params["np"] == "3"
    assert params["invt"] == "2"
    assert params["fields"].endswith("f184")
    assert "ut" in params
    assert captured["referer"].startswith("https://quote.eastmoney.com")


def test_singleton_uses_settings_and_quotes_universe(monkeypatch) -> None:
    import backend.market_proxy.eastmoney_fund_provider as module

    monkeypatch.setattr(module, "_provider", None)
    created: dict[str, object] = {}

    class FakeProviderInstance:
        def __init__(self, **kwargs: object) -> None:
            created.update(kwargs)

    class FakeQuotesCache:
        def all_codes(self) -> list[str]:
            return ["600000"]

    monkeypatch.setattr(module, "EastmoneyFundProvider", FakeProviderInstance)
    monkeypatch.setattr(
        "backend.market_proxy.quotes.get_market_quotes_cache",
        lambda: FakeQuotesCache(),
    )
    provider = module.get_eastmoney_fund_provider()

    assert isinstance(provider, FakeProviderInstance)
    assert created["batch_size"] == 800
    assert created["request_interval_seconds"] == 60.0
    assert callable(created["universe_provider"])


def test_five_hundred_abort_round_immediately() -> None:
    # 5xx 属系统性上游故障：首批即中止，不连续打 API
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    provider = EastmoneyFundProvider(client=client, sleep=lambda _s: None, batch_size=1)

    batch = provider._fetch_all_sync(["600000", "000001", "300750"], "2026-07-30")

    assert batch.truncated_by == "em_upstream_unavailable"
    assert batch.request_count == 1


def test_get_singleton_reuses_instance(monkeypatch) -> None:
    import backend.market_proxy.eastmoney_fund_provider as module

    monkeypatch.setattr(module, "_provider", None)
    first = module.get_eastmoney_fund_provider()
    second = module.get_eastmoney_fund_provider()
    assert first is second
