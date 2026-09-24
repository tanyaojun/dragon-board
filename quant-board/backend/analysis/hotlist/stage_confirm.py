from __future__ import annotations

from collections.abc import Sequence


STAGE_CONFIRM_SLOTS_DEFAULT = 2


def confirm_stage(
    raw_points: Sequence[tuple[str, str]],
    confirm_slots: int = STAGE_CONFIRM_SLOTS_DEFAULT,
) -> tuple[str, dict[str, object]]:
    """按输入顺序重放阶段滞回；调用方负责提供已按槽位升序且因果截断的序列。

    语义约束（纯函数，无 I/O）：
    - 第一条截面直接确认，不参与候选计数；
    - 候选阶段连续 ``confirm_slots`` 个槽位复现才切换确认阶段；
    - 候选变回当前确认阶段即清空候选（吸收单槽抖动）；
    - ``confirm_slots`` 阈值下限收敛到 1，1 等价于逐槽原始透传；
    - 空序列防御性返回空确认阶段与无候选状态。
    """
    slots = max(1, int(confirm_slots))
    state: dict[str, object] = {
        "pending": False,
        "pendingStage": None,
        "pendingSince": None,
        "confirmSlots": slots,
    }
    points = [(str(slot), str(stage).strip()) for slot, stage in raw_points if str(stage).strip()]
    if not points:
        return "", state

    confirmed = points[0][1]
    pending_stage: str | None = None
    pending_since: str | None = None
    pending_count = 0

    for slot_time, raw_stage in points[1:]:
        if raw_stage == confirmed:
            pending_stage = None
            pending_since = None
            pending_count = 0
            continue
        if raw_stage == pending_stage:
            pending_count += 1
        else:
            pending_stage = raw_stage
            pending_since = slot_time
            pending_count = 1
        if pending_count >= slots:
            confirmed = raw_stage
            pending_stage = None
            pending_since = None
            pending_count = 0

    if pending_stage is not None:
        state.update(
            pending=True,
            pendingStage=pending_stage,
            pendingSince=pending_since,
        )
    return confirmed, state
