"""limitSummary 情绪快照取数（Phase 1 解锁项，设计文档 §5.3/§6.0 取数规则的研究侧实现）。

回退口径（2026-09-26 计划定版，task_plan_phase1.md 接口事实 3/4）：
  daily:15:30 收盘帧优先 → half_hour 尾盘槽倒序（15:00→…→11:00），
  排除 09:30/10:00（Phase 0 实证首槽 THS 池未建满、ztCount 系统性偏低）。
  全部不可得 → status=insufficient（不伪造）。
这是**研究读取口径**：只改变读侧选择，不改采集/写入链；输出携带 source 供
消费方核对取数来源。字段缺失保持 None 不伪造。
"""

from __future__ import annotations

from typing import Any

EXCLUDED_SLOTS = frozenset({"09:30", "10:00"})


def _zhaban_dict(limit_summary: Any) -> dict[str, Any]:
    z = limit_summary.get("zhaban") if isinstance(limit_summary, dict) else None
    return z if isinstance(z, dict) else {}


def _num(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) else None


def _extract_fields(limit_summary: Any) -> dict[str, float | None]:
    """从一帧 limitSummary 提取情绪字段（缺字段保持 None）。"""
    zhaban = _zhaban_dict(limit_summary)
    zt = _num(zhaban.get("ztCount"))
    if zt is None and isinstance(limit_summary, dict):
        zt = _num(limit_summary.get("ztCount"))
    boards = (
        limit_summary.get("continuousBoards")
        if isinstance(limit_summary, dict)
        else None
    )
    max_board = _num(boards.get("maxBoard")) if isinstance(boards, dict) else None
    has_any = zt is not None or max_board is not None or _num(zhaban.get("rate")) is not None
    if not has_any:
        return {}
    return {"zhabanRate": _num(zhaban.get("rate")), "maxBoard": max_board, "ztCount": zt}


def pick_sentiment_snapshot(
    daily_1530: Any,
    half_hour_slots: list[tuple[str, Any]] | None,
) -> dict[str, Any]:
    """单日 limitSummary 情绪快照：按回退口径选帧并提取字段。

    daily_1530：daily 类型 15:30 帧的 limitSummary（或 None）；
    half_hour_slots：该日 half_hour 各槽 [(slotTime, limitSummary)]（顺序无关）。
    """
    fields = _extract_fields(daily_1530)
    if fields:
        return {"status": "ok", "source": "daily:15:30", **fields}

    for slot, limit_summary in sorted(
        (half_hour_slots or []), key=lambda item: item[0], reverse=True
    ):
        if str(slot) in EXCLUDED_SLOTS:
            continue
        fields = _extract_fields(limit_summary)
        if fields:
            return {"status": "ok", "source": f"half_hour:{slot}", **fields}

    return {"status": "insufficient", "source": None, "zhabanRate": None, "maxBoard": None, "ztCount": None}
