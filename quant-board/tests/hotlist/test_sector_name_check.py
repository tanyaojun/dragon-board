# -*- coding: utf-8 -*-
"""sector_name_check：韭研↔KPL 板块名录每日匹配诊断（2026-11-01）。

数据口径（用户裁决 2026-11-01：不用 mock，用真实数据）：
- 韭研侧 = 真实 MongoDB（dragon_board_quant）hotlist_jev_action 存量档，只读；
- KPL 侧 = 真实排行归档回放（data/backups/kpl-sector-ranking-20261101/
  kpl_real_ranking.json，2026-11-01 由生产 get_sector_ranking 实拉落档）。
  红线保持：测试零真实 KPL 上呼（先例 test_kpl_ranking_service），零写库。

断言钉住 2026-10-30 韭研 final × KPL 241 板块的真实对照结论；库/归档缺失
时 skip（不伪造通过）。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.operations import sector_name_check as snc

ARCHIVE = Path(__file__).resolve().parents[2] / "data" / "backups" / "kpl-sector-ranking-20261101" / "kpl_real_ranking.json"
CHECK_DATE = "2026-10-30"


@pytest.fixture(scope="module")
def db():
    """真实档测试库：dragon_board_test 由生产库 mongodump→mongorestore 全量复制
    （2026-11-01 用户指令，源库快照归档 data/backups/mongo-quant-snapshot-20261101/）。
    经 repository_factory（pytest 护栏指向 test 库），只读不写。"""
    try:
        from backend.data.repositories import repository_factory
        real = repository_factory.get_runtime_mongodb_database()
        if "jiuyan_action" not in real.list_collection_names():
            pytest.skip("test db lacks jiuyan_action（重跑 restore）")
        return real
    except Exception as exc:   # 库不可用：如实跳过，不伪造通过
        pytest.skip(f"mongodb unavailable: {exc}")


@pytest.fixture(scope="module")
def ranking():
    if not ARCHIVE.exists():
        pytest.skip(f"kpl ranking archive missing: {ARCHIVE}")
    return json.loads(ARCHIVE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def out(db, ranking):
    return snc.check_sector_names(db, CHECK_DATE, kpl_ranking=ranking)


def test_real_check_ok(out, ranking):
    assert out["ok"] is True and out["date"] == CHECK_DATE
    assert out["jiuyanTotal"] >= 5
    assert out["kplTotal"] == len(ranking["items"])   # 名录口径=排行全量
    # 统计自洽：六类计数之和 = 题材板块行数（行政桶除外；semantic=语义桥 2026-11-01 加）
    s = out["stats"]
    assert s["same"] + s["alias"] + s["suffix"] + s["contains"] + s["semantic"] \
        + s["unmatched"] == len(out["rows"])


def test_real_known_conclusions(out):
    """钉 2026-10-30 真实结论（ALIASES/归一/双向包含单一事实源的行为锚）。"""
    by = {r["board"]: r for r in out["rows"]}
    assert by["机器人"]["way"] == "same" and by["机器人"]["kplNames"] == ["机器人概念"]
    assert by["商业航天"]["way"] == "same"
    assert by["AI硬件"]["way"] == "same" and by["AI硬件"]["kplNames"] == ["AI硬件"], \
        "KPL 完整名录含 AI硬件（用户指认白名单），同名直配"
    assert by["医疗医药"]["way"] == "contains" and "医药" in by["医疗医药"]["kplNames"]


def test_real_admin_buckets_excluded(out):
    """行政桶（其他/ST板块）单列不进未匹配统计；公告有语义桥参与匹配，不再单列
    （2026-11-01 用户拍板：公告↔KPL 季报增长高度趋同，模糊匹配非全词）。"""
    excl = {e["board"] for e in out["excludedBuckets"]}
    assert {"其他", "ST板块"} <= excl
    assert "公告" not in excl and "公告" not in out["unmatchedJiuyan"]
    assert all(r["board"] not in excl for r in out["rows"])


def test_real_semantic_bridges(out):
    """语义桥真实结论（2026-11-01 用户拍板第 2 轮，钉档为回归锚）：
    - 公告（event 事件桥，模糊匹配非全词）：KPL 名含「增长/业绩/预增/扭亏」即命中，
      2026-10-30 实命中 5 个业绩板块；
    - 大消费（pan 泛指桥，成员清单=web 申万归类+韭研档成分实证）：
      KPL 归一名与成员词互含即命中，2026-10-30 实命中 10 个细分。
    两桥落地后未匹配清零；未匹配清单继续作为 ALIASES/桥表维护候选。"""
    by = {r["board"]: r for r in out["rows"]}
    pub = by["公告"]
    assert pub["way"] == "semantic" and pub["matched"] is True
    assert "三季报增长" in pub["kplNames"] and "业绩增长" in pub["kplNames"]
    assert pub["bridgeNote"]
    pan = by["大消费"]
    assert pan["way"] == "semantic" and pan["matched"] is True
    assert {"食品饮料", "零售", "旅游"} <= set(pan["kplNames"])
    assert "消费电子" not in pan["kplNames"]   # 科技属性不在成员清单，不误命中
    assert out["unmatchedJiuyan"] == []


def test_history_coverage_aliases(db):
    """历史覆盖增补 alias 生效（2026-11-01 用户拍板：历史 108 交易日 90%+ 目标）。

    增补清单逐条经 KPL 名录全集实证（见 docs v4f §九）；用 check_sector_names
    的 kpl_names 注入口验证：韭研板块名经新增 alias 命中 KPL 对应名（way=alias）。
    """
    from backend.analysis.hotlist import theme_event_digest as dg
    from backend.operations.sector_name_check import check_sector_names
    universe = ["元器件", "农业", "算力", "黄金", "核电", "有色金属",
                "芯片", "消费电子"]
    for board, kpl in (("被动元件", "元器件"), ("农林牧渔", "农业"),
                       ("液冷散热", "算力"), ("贵金属", "黄金"),
                       ("可控核聚变", "核电"), ("金属有色", "有色金属"),
                       ("国产半导体", "芯片"), ("AIPC", "消费电子")):
        aliases = dg.ALIASES.get(dg.normalize_name(board))
        assert aliases and kpl in aliases, f"{board} 缺 {kpl} 别名"
        row = {r["board"]: r for r in check_sector_names(
            db, None, kpl_names=[kpl]).get("rows", [])}.get(board)
        if row is not None:   # 当日档存在该板块时验证实际命中
            assert row["matched"] and kpl in row["kplNames"], (board, row)


def test_real_reverse_coverage_reported(out):
    """KPL 反向未覆盖如实计数（241 细分名对韭研粗桶天然大量未覆盖，不静默省略）。"""
    assert out["uncoveredKplN"] > 0
    assert len(out["uncoveredKpl"]) == out["uncoveredKplN"]


def test_ai_video_whitelist_matches_ai_yingshi_alias(db):
    """2026-11-02 报障回归：韭研「AI影视/传媒」名录对照显示未匹配——KPL「AI视频」
    是层2 板块、不在 Type=1 活跃排行名录，别名桥写了也查无此名。并入
    KPL_EXTRA_BOARDS 白名单后应经 alias 桥命中（用户裁决：语料桥用层2 粒度，
    强度行仍走一级 AI应用，两桥互不影响）。"""
    out = snc.check_sector_names(db, CHECK_DATE, kpl_names=["AI应用", "文化传媒"])
    assert out["ok"] is True
    row = {r["board"]: r for r in out.get("rows", [])}.get("AI影视/传媒")
    if row is None:
        pytest.skip("2026-10-30 韭研档无 AI影视/传媒 板块行")
    assert row["matched"] is True and row["way"] == "alias"
    assert "AI视频" in (row.get("kplNames") or [])
