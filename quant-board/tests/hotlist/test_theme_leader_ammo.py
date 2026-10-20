# -*- coding: utf-8 -*-
"""题材层龙头题集/弹药纯函数测试（零 IO / 零模型）。

锁定口径：
1. **判据冻结**：题集内容哈希是代际戳，改一个字就必须换代（本测试冻结 v1 的 hash）；
2. **分桶唯一来源**：分桶函数被基线脚本与投喂叙事共用，键必须稳定（改键=历史桶率不可比）；
3. **龙一排序**：真连板最高 → 封板时间最早（时间缺失垫底，但不得把缺失当"最早"）；
4. **基准率透明度**：组合桶样本不足时必须明示"样本不足/样本量"，不得隐藏小样本或给假高率；
5. **叙事顺序固定**：便于逐字复现与回归比对；题材证据缺失的 fail-visible 文本不得被吞掉。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import theme_leader_ammo as A


def test_question_set_frozen_hash_and_versions():
    """题集/原料代际戳冻结：任何判据字面改动都必须显式换代（跨代不可比）。

    代际史：v1 = 2026-10-20（hash `ff010c50200e`，见预登记 §4.2；13 条日标签保留为 v1 代）；
    v2 = 2026-10-20 晚（用户裁决「证据缺失改确定性门」→ 题面加规则④ + `apply_evidence_gate`），
    hash 随之换代——**跨代标签不得混评**（评估脚本按版本分组）。
    """
    assert A.QUESTION_SET_VERSION_THEME_LEADER == "v2"
    assert A.AMMO_VERSION_THEME_LEADER == "2026-10-20b"
    assert A.QUESTION_SET_HASH_THEME_LEADER == "985c529fded7"
    assert A.THEME_LEADER_KEYS == ("leader_nextday_continue", "catalyst_stage")
    for key in A.THEME_LEADER_KEYS:
        q = A.QUESTIONS_THEME_LEADER[key]
        assert q["type"] == "choice" and q["instructions"] and q["criteria"]
        assert "insufficient" in q["criteria"], "每题必须留证据不足档，禁止逼模型硬填"


def test_bucket_functions_stable_keys():
    assert A.streak_bucket(None) == "unknown" and A.streak_bucket("bad") == "unknown"
    assert [A.streak_bucket(v) for v in (1, 2, 3, 4, 9)] == ["1", "2", "3", "4+", "4+"]
    assert [A.board_count_bucket(v) for v in (1, 2, 3, 4, 5, 7, 8, 12)] == \
        ["1-2", "1-2", "3-4", "3-4", "5-7", "5-7", ">=8", ">=8"]
    assert [A.seal_time_bucket(t) for t in ("09:25:00", "10:00:59", "11:30", "13:00", "13:16:47")] == \
        ["early<=10:00", "early<=10:00", "mid<=13:00", "mid<=13:00", "late>13:00"]
    assert A.seal_time_bucket(None) == "unknown" and A.seal_time_bucket("noon") == "unknown"
    assert [A.ladder_bucket(v) for v in (0, 2, 5)] == ["0", "2", "3"]
    assert [A.prev_peer_bucket(v) for v in (None, 0, 1, 3)] == \
        ["prev_unknown", "prev0", "prev1-2", "prev3+"]
    assert A.combo_key({"streak": 3, "boardN": 6, "time": "09:30:00"}) == \
        "streak3|n5-7|early<=10:00"


def test_rank_board_stocks_orders_by_streak_then_time():
    stocks = [
        {"code": "b", "streak": 2, "time": "09:30:00"},
        {"code": "a", "streak": 2, "time": "10:30:00"},
        {"code": "c", "streak": 3, "time": "14:00:00"},
        {"code": "d", "streak": None, "time": "09:00:00"},
        {"code": "e", "streak": 2, "time": None},
    ]
    assert [s["code"] for s in A.rank_board_stocks(stocks)] == ["c", "b", "a", "e", "d"]
    assert [s["code"] for s in stocks] == ["b", "a", "c", "d", "e"], "不得原地改输入"


def _rows():
    def mk(streak, boardN, time, cont):
        return {"streak": streak, "boardN": boardN, "time": time, "continued": cont}
    return [
        mk(4, 9, "09:20:00", True), mk(4, 8, "09:40:00", True), mk(4, 9, "13:30:00", False),
        mk(3, 6, "09:10:00", True), mk(3, 6, "10:05:00", False), mk(3, 5, "11:00:00", True),
        mk(2, 3, "09:00:00", False), mk(1, 1, "14:00:00", False), mk(1, 2, "09:50:00", True),
    ]


def test_rates_and_min_sample_gate():
    rows = _rows()
    assert A.group_rates(rows, lambda r: A.streak_bucket(r["streak"]))["4+"] == \
        {"cont": 2, "n": 3, "rate": 0.6667}
    combo = A.combo_rates(rows, min_n=2)
    assert combo["streak4+|n>=8|early<=10:00"] == {"cont": 2, "n": 2, "rate": 1.0}
    assert "streak1|n1-2|late>13:00" not in combo, "样本 <min_n 的组合桶不得出率"
    s = A.summarize_rows(rows, min_combo_n=2)
    assert s["leaders"] == 9 and s["continued"] == 5 and s["rate"] == 0.5556
    assert set(s) >= {"byStreak", "byBoardCount", "bySealTime", "byFollowers", "byPrevPeers", "combo"}


def test_baseline_line_discloses_small_samples_and_falls_back():
    rows = _rows()
    strong = {"streak": 4, "boardN": 9, "time": "09:20:00"}
    line = A.baseline_line(rows, strong, min_combo_n=2)
    assert "同桶[streak4+|n>=8|early<=10:00] 历史次日连板率 100.0%（2 样本）" in line
    assert "按连板高度[4+]" in line and "按板块家数[>=8]" in line and "总体" in line

    weak = {"streak": 1, "boardN": 2, "time": "09:50:00"}
    line2 = A.baseline_line(rows, weak, min_combo_n=5)
    assert "样本不足（<5），不出率" in line2, "小样本必须明说，不给假高率"
    assert "按连板高度[1]" in line2, "组合桶不足时回退到单维桶（标注样本量）"


def test_structure_line_marks_unknown_prev():
    line = A.structure_line(board="机器人", board_n=5,
                            leader={"name": "大业股份", "code": "603278", "streak": 3,
                                    "time": "09:25:00"},
                            followers_ge_ladder=1, prev_board_n=None, prev_peers=None)
    assert "板块「机器人」今日封板 5 家" in line and "3 连板" in line and "首封 09:25:00" in line
    assert "昨日同板块不可考" in line

    line2 = A.structure_line(board="机器人", board_n=5,
                             leader={"name": "X", "code": "1", "streak": None, "time": None},
                             followers_ge_ladder=0, prev_board_n=3, prev_peers=1)
    assert "连板高度不可算" in line2 and "时间不可考" in line2
    assert "昨日该板块封板 3 只，其中 1 只今日仍封板" in line2


def test_narrative_order_is_fixed_and_keeps_fail_visible_text():
    ev = ("【题材证据 · 韭研产业树 + 投资日历】\n板块级催化：未映射（不代表无催化）")
    text = A.build_leader_narrative(
        date="2026-10-19", market_line="涨停 46 家", structure="板块「X」今日封板 2 家",
        baseline="结构基线：总体 32.6%", evidence_block=ev, corpus_line="题材语料：未采集",
        leader_name="东方嘉盛", leader_code="002889")
    lines = text.splitlines()
    assert lines[0].startswith("2026-10-19 交易日 · 涨停 46 家")
    assert lines[1] == "待判龙头：东方嘉盛（002889）"
    assert text.endswith(ev), "证据块必须原样嵌在末尾，不得被 runner 二次改写"
    assert lines[4] == "题材语料：未采集" and lines[5].startswith("【题材证据")
    assert "未映射（不代表无催化）" in text and "未采集" in text


def test_evidence_gate_forces_insufficient_and_keeps_model_answer():
    """v2 确定性门：证据缺失 → 概率题强制 insufficient；原答必须留档（不丢模型真实输出）。"""
    answers = {"leader_nextday_continue": {"type": "choice", "choice": "mid_45_65",
                                          "confidence": 0.3, "probabilities": {"mid_45_65": 0.6}},
               "catalyst_stage": {"type": "choice", "choice": "insufficient"}}
    out, gate = A.apply_evidence_gate(answers, {"evidenceMissing": True,
                                                "evidenceMissingReason": "board_unmapped"})
    assert out["leader_nextday_continue"]["choice"] == "insufficient"
    assert out["leader_nextday_continue"]["probabilities"] == {"insufficient": 1.0}
    assert out["leader_nextday_continue"]["gateReason"] == "board_unmapped"
    assert out["catalyst_stage"] == answers["catalyst_stage"], "只覆盖概率题，不动催化题"
    assert gate["applied"] is True and gate["reason"] == "board_unmapped"
    assert gate["modelChoice"] == "mid_45_65" and gate["modelProbabilities"] == {"mid_45_65": 0.6}
    assert "未映射" in gate["label"]


def test_evidence_gate_passes_through_when_evidence_present():
    """有催化正文（哪怕陈旧）→ 不改写：stale 是证据，不是缺失。"""
    answers = {"leader_nextday_continue": {"type": "choice", "choice": "low_25_45"}}
    for ev in ({"evidenceMissing": False, "evidenceMissingReason": None}, {},
               {"evidenceMissing": True}):   # 最后一条：缺失但无原因 → 仍要门住（reason=unknown）
        out, gate = A.apply_evidence_gate(answers, ev)
        if ev.get("evidenceMissing"):
            assert gate["applied"] is True and out["leader_nextday_continue"]["choice"] == "insufficient"
        else:
            assert gate["applied"] is False and out is answers


def test_gate_holds_when_previously_gated_answer_reruns():
    """幂等/重跑安全：已是 insufficient 的答案再过门不报错、不丢原因。"""
    out, gate = A.apply_evidence_gate(
        {"leader_nextday_continue": {"type": "choice", "choice": "insufficient"}},
        {"evidenceMissing": True, "evidenceMissingReason": "no_content_no_event"})
    assert gate["applied"] is True and gate["modelChoice"] == "insufficient"
    assert out["leader_nextday_continue"]["gateReason"] == "no_content_no_event"
