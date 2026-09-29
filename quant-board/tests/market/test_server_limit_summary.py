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
