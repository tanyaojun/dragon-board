# -*- coding: utf-8 -*-
"""主题材判定（跟强不跟弱）+ 题材治理层 + KPL↔jiuyan 对照层测试。

核心案例基准（治理 P2 立项根因）：大业股份 603278 themes 含
['轮胎','商业航天','电力','人形机器人']，2026-10-23 强度=轮胎 zt=1/rank=79、
人形机器人 zt=16/rank=2 → 必须判「人形机器人」（旧 themes[0] 口径判「轮胎」）。
"""
from __future__ import annotations

import pytest

from backend.services.theme.dict_governance import (
    GOVERNANCE_BASELINE,
    GovernanceSpec,
    apply_governance,
    load_governance,
    normalize_name,
)
from backend.services.theme.industry_alias import effective_mapping_of, suggest_for
from backend.snapshot_derivation.active_theme import (
    resolve_active_theme,
    theme_names_of,
)


class FakeCol:
    def __init__(self, docs):
        self._docs = docs

    def find_one(self, q, *a, **k):
        for d in self._docs:
            if all(d.get(k_) == v for k_, v in q.items()):
                return d
        return None

    def replace_one(self, q, doc, upsert=False):
        self._docs = [d for d in self._docs if not all(d.get(k_) == v for k_, v in q.items())]
        self._docs.append(doc)

    def insert_many(self, docs, ordered=False):
        self._docs.extend(docs)

    def delete_many(self, q):
        self._docs = [d for d in self._docs if not all(d.get(k_) == v for k_, v in q.items())]


class FakeDb:
    def __init__(self):
        self.collections: dict[str, FakeCol] = {}

    def __getitem__(self, name):
        if name not in self.collections:
            self.collections[name] = FakeCol([])
        return self.collections[name]


# ── active_theme 纯函数 ─────────────────────────────────────────────

DAYE_THEMES = ["轮胎", "商业航天", "电力", "人形机器人"]
DAYE_STRENGTH = {
    "轮胎": {"ztCount": 1, "heatScore": 44367, "rank": 79},
    "人形机器人": {"ztCount": 16, "heatScore": 272276, "rank": 2},
}


def test_daye_case_resolves_humanoid_robot():
    """大业基准：zt=16 的人形机器人必须压过 zt=1 的轮胎（旧口径判轮胎的根因）。"""
    res = resolve_active_theme(DAYE_THEMES, DAYE_STRENGTH)
    assert res["mainTheme"] == "人形机器人"
    assert res["degraded"] is False
    assert "ztCount=16" in res["basis"]


def test_zt_count_dominates_heat_score():
    strength = {
        "A": {"ztCount": 2, "heatScore": 100.0, "rank": 50},
        "B": {"ztCount": 1, "heatScore": 99999.0, "rank": 1},
    }
    res = resolve_active_theme(["A", "B"], strength)
    assert res["mainTheme"] == "A"


def test_tie_breaks_by_heat_then_rank():
    res = resolve_active_theme(
        ["A", "B"],
        {"A": {"ztCount": 1, "heatScore": 10.0, "rank": 9},
         "B": {"ztCount": 1, "heatScore": 99.0, "rank": 1}},
    )
    assert res["mainTheme"] == "B"
    res2 = resolve_active_theme(
        ["A", "B"],
        {"A": {"ztCount": 1, "heatScore": 50.0, "rank": 3},
         "B": {"ztCount": 1, "heatScore": 50.0, "rank": 8}},
    )
    assert res2["mainTheme"] == "A"


def test_all_missing_strength_returns_none_not_first():
    """fail-visible：强度全缺 → None（绝不回退 themes[0] 字典序伪装）。"""
    res = resolve_active_theme(DAYE_THEMES, {})
    assert res["mainTheme"] is None
    assert res["degraded"] is True
    assert res["basis"] == "sector_strength_missing"


def test_partial_strength_judges_among_known():
    """部分候选无强度行：只在有强度的候选里判，无强度的不删除（透明候选）。"""
    res = resolve_active_theme(["冷门题材", "人形机器人"],
                               {"人形机器人": {"ztCount": 3, "heatScore": 1.0, "rank": 5}})
    assert res["mainTheme"] == "人形机器人"
    assert {c["name"] for c in res["candidates"]} == {"冷门题材", "人形机器人"}


def test_excluded_theme_not_candidate():
    res = resolve_active_theme(
        ["中证A50成分股", "银行"],
        {"中证A50成分股": {"ztCount": 9, "heatScore": 999.0, "rank": 1},
         "银行": {"ztCount": 1, "heatScore": 10.0, "rank": 30}},
        excluded_names=["中证A50成分股"],
    )
    assert res["mainTheme"] == "银行"


def test_family_link_extends_parent():
    """宇树概念股：父题材（人形机器人）入候选并可胜出（官方背书挂靠）。"""
    res = resolve_active_theme(
        ["宇树机器人"],
        {"宇树机器人": {"ztCount": 2, "heatScore": 30062.0, "rank": 121},
         "人形机器人": {"ztCount": 16, "heatScore": 272276.0, "rank": 2}},
        family_links={"宇树机器人": "人形机器人"},
    )
    assert res["mainTheme"] == "人形机器人"
    top = res["candidates"][0]
    assert top["origin"] == "family_link"
    assert "家族挂靠" in res["basis"]


def test_legacy_dict_theme_format_supported():
    """4-6 月旧格式 list[dict]（带 name/heatScore）统一取名单。"""
    res = resolve_active_theme(
        [{"name": "人形机器人", "heatScore": 99}, {"name": "轮胎"}],
        DAYE_STRENGTH,
    )
    assert res["mainTheme"] == "人形机器人"


def test_empty_and_non_list_themes():
    assert resolve_active_theme([], DAYE_STRENGTH)["basis"] == "no_themes"
    assert resolve_active_theme(None, DAYE_STRENGTH)["basis"] == "no_themes"
    assert resolve_active_theme("轮胎", DAYE_STRENGTH)["basis"] == "no_themes"


def test_all_excluded_returns_none():
    res = resolve_active_theme(["中证A50成分股"], {}, excluded_names=["中证A50成分股"])
    assert res["mainTheme"] is None
    assert res["basis"] == "all_themes_excluded"


def test_theme_names_of_dedup_and_dict():
    assert theme_names_of(["A", "A", {"name": "B"}, {"name": "A"}]) == ["A", "B"]
    assert theme_names_of([{"id": "84"}]) == ["84"]


# ── 治理层（dict_governance） ──────────────────────────────────────

def test_normalize_name_strips_suffixes():
    assert normalize_name("煤炭概念") == "煤炭"
    assert normalize_name("固态电池概念板块") == "固态电池"
    assert normalize_name("人形机器人") == "人形机器人"


def test_baseline_contents():
    assert "中证A50成分股" in GOVERNANCE_BASELINE["excludeThemeNames"]
    links = {l["child"]: l["parent"] for l in GOVERNANCE_BASELINE["familyLinks"]}
    # T3 正式挂靠 gov-v2：2 官方背书 + 16 重叠率实证晋升
    assert links["宇树机器人"] == "人形机器人"
    assert links["优必选机器人"] == "人形机器人"
    assert links["卫星互联网"] == "商业航天"
    assert links["液冷服务器"] == "AI硬件"
    assert links["固态电池概念"] == "锂电池材料"  # 候选方向修正：细分挂大类
    assert links["光伏辅材"] == "光伏"
    assert len(links) == 18
    # 横切/兄弟/事件关联拒绝名单（重叠率 <0.30 或方向反转）
    assert "军工" not in links.values() or all(  # 军工是大类不作 child 之外的父挂靠检查
        l["parent"] != "可控核聚变" for l in GOVERNANCE_BASELINE["familyLinks"])
    assert "涨价概念" in GOVERNANCE_BASELINE["crossCutBoards"]


def test_apply_and_load_governance_idempotent():
    db = FakeDb()
    s1 = apply_governance(db)
    assert s1["version"] == "gov-v2"
    apply_governance(db)  # 幂等整写
    gov = load_governance(db)
    assert gov.found
    assert gov.family_links["宇树机器人"] == "人形机器人"
    assert normalize_name("大基金持股") in gov.exclude_names


def test_load_missing_doc_returns_empty_spec():
    gov = load_governance(FakeDb())
    assert not gov.found
    assert gov.family_links == {}


def test_governance_spec_direct_construction():
    spec = GovernanceSpec({"familyLinks": [{"parent": "P", "child": "C"}],
                           "excludeThemeNames": ["中证A50成分股"]})
    assert spec.family_links == {"C": "P"}


# ── KPL↔jiuyan 对照层（industry_alias） ────────────────────────────

def test_suggest_for_exact_contains_multi():
    assert suggest_for("储能概念", ["储能", "军工"]) == {"matchType": "exact", "names": ["储能"]}
    assert suggest_for("军工信息化", ["军工", "空军"]) == {"matchType": "contains", "names": ["军工"]}
    multi = suggest_for("机器人零部件", ["机器人零部件", "特斯拉机器人"])
    assert multi is None or multi["matchType"] in ("exact", "contains")


def test_suggest_for_excluded_words():
    assert suggest_for("公告", ["公告产业"]) is None


def test_effective_mapping_family_inherit():
    db = FakeDb()
    db["theme_industry_mapping"].replace_one(
        {"_id": "人形机器人"},
        {"_id": "人形机器人", "theme": "人形机器人",
         "industryNames": ["国产机器人", "特斯拉机器人", "机器人零部件"],
         "matchType": "manual"},
        upsert=True)
    db["theme_dict_governance"].replace_one(
        {"_id": "THEME_GOV"}, {"_id": "THEME_GOV", **GOVERNANCE_BASELINE}, upsert=True)
    direct = effective_mapping_of(db, "人形机器人")
    assert direct["matchType"] == "manual"
    inherit = effective_mapping_of(db, "宇树机器人")
    assert inherit["matchType"] == "family_inherit<人形机器人>"
    assert "国产机器人" in inherit["names"]
    assert effective_mapping_of(db, "轮胎") is None


@pytest.mark.parametrize("name", ["人形机器人", "煤炭概念", "AI硬件"])
def test_normalize_symmetry_with_active_theme(name):
    """active_theme 与治理层归一同式（判定键与治理键一致）。"""
    from backend.snapshot_derivation.active_theme import _norm
    assert _norm(name) == normalize_name(name)
