"""ServerLimitSummaryProvider 纯函数合同（2026-09-25）。

背景：frame.limitSummary 与 frame.indices 此前取自前端写入 proxy 的 startup-bundle
（TTL 300s），浏览器断供的槽位帧相应字段为空（2026-09-24 的 11:00/11:30/14:00/15:00
四帧），触发情绪文档「全市场证据回退自 14:30 槽位」诊断。根治 = 采集器进程内直连
THS 涨停池接口与 akshare-sina 指数源服务端构建。

fail-visible 验收：部分异常仍保存且带标记；缺失不被伪装成零值；上游失败时不产出
limitSummary（全零结构会被下游误判为有效证据并废掉 EOD 回退）。
"""
import asyncio

from backend.snapshot_collector.providers import (
    ServerMarketEvidenceProvider,
    build_server_indices,
    build_server_limit_summary,
)


def test_build_server_limit_summary_buckets_boards_and_zhaban():
    info = [
        {"code": "301689", "high_days": "首板", "continue_day": None},
        {"code": "600825", "continue_day": 4},
        {"code": "002119", "continue_day": 2},
        {"code": "603230", "continue_day": 3},
        {"code": "no_height"},
    ]
    pools = {"poolCounts": {"failed": 10}}

    summary = build_server_limit_summary(info, pools)

    assert summary["continuousBoards"] == {
        "yiban": 1, "erban": 1, "sanban": 1, "sibanPlus": 1, "maxBoard": 4,
    }
    assert summary["zhaban"]["ztCount"] == 5
    assert summary["zhaban"]["count"] == 10
    assert summary["zhaban"]["fengbanRate"] == round(5 / 15 * 100, 2)
    assert summary["zhaban"]["rate"] == round(10 / 15 * 100, 2)
    assert summary["thsPools"]["poolCounts"]["failed"] == 10
    assert summary["thsPools"]["failedCount"] == 10
    assert summary["source"] == "server-limitup"


def test_build_server_limit_summary_drawdown_block():
    # 大幅回撤池（2026-10-02 弹药扩展）：max_drawdown API 为负数字符串 → 存正幅值；
    # 空池 count=0、幅值 None（不伪造）；池缺失（pools 无该键且无 poolCounts）count=None
    pools = {"pools": {"drawdown": {"ok": True, "items": [
        {"stock_code": "603278", "max_drawdown": "-12.56"},
        {"stock_code": "600001", "max_drawdown": -5.0},
    ]}}}
    summary = build_server_limit_summary([{"code": "x"}], pools)
    assert summary["drawdown"] == {"count": 2, "avgDrawdownPct": 8.78, "deepestDrawdownPct": 12.56}

    empty = build_server_limit_summary([{"code": "x"}], {"pools": {"drawdown": {"ok": True, "items": []}}})
    assert empty["drawdown"] == {"count": 0, "avgDrawdownPct": None, "deepestDrawdownPct": None}

    missing = build_server_limit_summary([{"code": "x"}], {})
    assert missing["drawdown"]["count"] is None  # 上游没给 ≠ 0
    assert missing["drawdown"]["avgDrawdownPct"] is None


def test_pool_counts_missing_derived_from_pool_items_not_faked_zero():
    # 历史日期查询 poolCounts=null：炸板/回封/回撤必须按池内 items 派生，禁止伪装成 0
    pools = {
        "pools": {
            "failed": {"items": [{}, {}, {}]},
            "rushing": {"items": [{}]},
            "drawdown": {"items": [{}, {}]},
        }
    }
    summary = build_server_limit_summary([{"code": "x"}], pools)
    assert summary["zhaban"]["count"] == 3
    assert summary["thsPools"]["failedCount"] == 3
    assert summary["thsPools"]["rushingCount"] == 1
    assert summary["thsPools"]["drawdownCount"] == 2


def test_high_days_value_bit_encoding_decoded():
    # 电科思仪 2026-09-24 实测形态：high_days="首板" + high_days_value=65537（位编码 1）
    info = [{"code": "301689", "high_days": "首板", "high_days_value": 65537}]
    summary = build_server_limit_summary(info, {})
    assert summary["continuousBoards"]["yiban"] == 1
    assert summary["continuousBoards"]["maxBoard"] == 1


def test_missing_zhaban_pool_yields_null_not_hundred_percent():
    # 炸板池缺失（单池上游失败/无数据）：zhaban 数值为 None 而非伪装 0/封板率 100%
    summary = build_server_limit_summary([{"code": "600825", "continue_day": 4}], {})
    assert summary["zhaban"] == {"count": None, "rate": None, "fengbanRate": None, "ztCount": 1}
    assert summary["continuousBoards"]["maxBoard"] == 4


def test_empty_info_returns_empty_summary_for_caller_fallback():
    # 上游无数据：返回空 dict（falsy），由调用方回退浏览器原料/最近有效帧，
    # 绝不产出全零结构（会被 _limit_summary_has_evidence 误判为有效证据）
    assert build_server_limit_summary([], {}) == {}


def test_provider_without_in_process_gateway_returns_no_limit_summary():
    # 非进程内网关 = 采集链路不可用：不携带 limitSummary（杜绝全零结构覆盖浏览器原料），
    # health ok=False 带结构化错误
    provider = ServerMarketEvidenceProvider(trading_date="2026-09-24", gateway=object())
    evidence, health = asyncio.run(provider.acollect(timeout_ms=1000))

    assert "limitSummary" not in evidence
    assert health.ok is False
    assert health.error


def test_build_server_indices_maps_aliases_and_skips_unknown():
    overview = {
        "items": [
            {"code": "sh000001", "change": -1.22},
            {"code": "sh000300", "change": -1.73},
            {"code": "sh000905", "change": -2.15},
            {"code": "sh000852", "change": -2.26},
            {"code": "sz399001", "change": -1.5},  # 未登记别名 → 跳过
            {"code": "sh000002", "change": None},  # 非数值 → 跳过
        ]
    }
    assert build_server_indices(overview) == {
        "sh": {"change": -1.22},
        "hs300": {"change": -1.73},
        "zz500": {"change": -2.15},
        "zz1000": {"change": -2.26},
    }


# ── THS 拉取重试（2026-10-02：9 月 15:00 缺 13/21 帧的根因缓解）───────────────


class _FakeLimitupService:
    """get_limit_up_list 按 payload 队列逐次返回；异常对象则抛出。"""

    def __init__(self, payloads):
        self._payloads = list(payloads)
        self.calls = 0
        self.pool_keys_requested = None

    async def get_limit_up_list(self, date=None):
        self.calls += 1
        payload = self._payloads.pop(0) if len(self._payloads) > 1 else self._payloads[0]
        if isinstance(payload, Exception):
            raise payload
        return payload

    async def get_ths_pools(self, date=None, keys=None):
        self.pool_keys_requested = keys
        return {"pools": {}}


_OK_PAYLOAD = {"data": {"info": [{"code": "600825", "continue_day": 4}]}}


class _FakeOverviewService:
    async def get_overview(self):
        return {"items": [{"code": "sh000001", "change": -1.0}]}


def _run_acollect(monkeypatch, service):
    import asyncio

    from backend.snapshot_collector.gateway import InProcessMarketDataGateway
    from backend.snapshot_collector import providers as providers_module

    async def _no_sleep(_seconds):
        return None

    monkeypatch.setattr("backend.market_proxy.limitup.get_limitup_service", lambda: service)
    monkeypatch.setattr(
        "backend.market_proxy.indices.get_market_overview_service",
        lambda: _FakeOverviewService(),
    )
    monkeypatch.setattr(providers_module.asyncio, "sleep", _no_sleep)
    providers_module._SERVER_EVIDENCE_CACHE.clear()  # 证据级缓存按用例隔离
    provider = ServerMarketEvidenceProvider(
        trading_date="2026-09-24", gateway=InProcessMarketDataGateway())
    return asyncio.run(provider.acollect(timeout_ms=1000))


def test_provider_reuses_evidence_within_ttl(monkeypatch):
    # 证据级 300s 缓存（风控优化）：TTL 内第二次 acollect 复用缓存，不再打 THS
    import asyncio

    from backend.snapshot_collector.gateway import InProcessMarketDataGateway
    from backend.snapshot_collector import providers as providers_module

    async def _no_sleep(_seconds):
        return None

    service = _FakeLimitupService([_OK_PAYLOAD])
    monkeypatch.setattr("backend.market_proxy.limitup.get_limitup_service", lambda: service)
    monkeypatch.setattr(
        "backend.market_proxy.indices.get_market_overview_service",
        lambda: _FakeOverviewService(),
    )
    monkeypatch.setattr(providers_module.asyncio, "sleep", _no_sleep)
    providers_module._SERVER_EVIDENCE_CACHE.clear()
    provider = ServerMarketEvidenceProvider(
        trading_date="2026-09-24", gateway=InProcessMarketDataGateway())
    evidence1, _ = asyncio.run(provider.acollect(timeout_ms=1000))
    evidence2, health2 = asyncio.run(provider.acollect(timeout_ms=1000))  # 缓存未清
    assert service.calls == 1  # 第二次 0 次上游调用
    assert evidence2["limitSummary"]["zhaban"]["ztCount"] == 1
    assert health2.ok is True


def test_provider_passes_collector_pool_subset(monkeypatch):
    # 盘中采集链只取 failed/rushing/drawdown 三池。
    # 7af28e2e 起 EOD（上海 ≥15:00）连板层五池并入采集——本用例冻结盘中时刻，
    # 避免真实时钟导致的昼/夜结果漂移（EOD 八池语义由 pool-key 选择专项用例覆盖）。
    from datetime import datetime
    from backend.snapshot_collector import providers as providers_module

    frozen = datetime(2026, 9, 24, 14, 30)

    class _FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # noqa: N805
            return frozen if tz is None else frozen.replace(tzinfo=tz)

    monkeypatch.setattr(providers_module, "datetime", _FrozenDatetime)
    service = _FakeLimitupService([_OK_PAYLOAD])
    _run_acollect(monkeypatch, service)
    assert service.pool_keys_requested == ("failed", "rushing", "drawdown")


def test_ths_first_attempt_fails_retry_recovers(monkeypatch):
    # 首试空 info（THS 间歇失败），重试成功 → limitSummary 在场、health ok、恰好 2 次调用
    service = _FakeLimitupService([{"data": {"info": []}}, _OK_PAYLOAD])
    evidence, health = _run_acollect(monkeypatch, service)
    assert evidence["limitSummary"]["zhaban"]["ztCount"] == 1
    assert health.ok is True and health.error == ""
    assert service.calls == 2


def test_ths_retry_exhausted_reports_failure_visible(monkeypatch):
    # 两次都空 → 不携带 limitSummary（绝不伪造全零结构）、health ok=False 带结构化错误
    service = _FakeLimitupService([{"data": {"info": []}}])
    evidence, health = _run_acollect(monkeypatch, service)
    assert "limitSummary" not in evidence
    assert health.ok is False and "重试后仍失败" in health.error
    assert service.calls == 2


def test_ths_first_attempt_success_no_extra_call(monkeypatch):
    # 首试即成功 → 只调 1 次，不产生无谓重试
    service = _FakeLimitupService([_OK_PAYLOAD])
    evidence, health = _run_acollect(monkeypatch, service)
    assert evidence["limitSummary"]["zhaban"]["ztCount"] == 1
    assert health.ok is True
    assert service.calls == 1


def test_build_server_limit_summary_seal_quality_block():
    # 封板质量（2026-10-02 裁决采集）：open_num None=一字秒板/1=硬板/≥2=烂板（键缺失≠0）；
    # limit_up_suc_rate 取 [0,1] 均值，越界/缺失过滤
    info = [
        {"code": "a"},                                        # open_num 缺失 → 一字/秒板
        {"code": "b", "open_num": 1, "limit_up_suc_rate": 0.5},
        {"code": "c", "open_num": 3, "limit_up_suc_rate": 0.7},
        {"code": "d", "open_num": 2, "limit_up_suc_rate": 1.4},  # 越界过滤
        {"code": "e", "open_num": 0},                         # 显式 0：按 ≤1 归硬板
    ]
    summary = build_server_limit_summary(info, {})
    sq = summary["sealQuality"]
    assert sq == {"byzCount": 1, "hardCount": 2, "rottenCount": 2, "rottenShare": 0.4,
                  "avgSucRate": 0.6}
