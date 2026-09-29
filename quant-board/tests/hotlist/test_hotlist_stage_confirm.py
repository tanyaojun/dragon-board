from backend.analysis.hotlist.stage_confirm import confirm_stage


def test_first_frame_confirms_immediately() -> None:
    confirmed, state = confirm_stage([("09:30", "退潮")], 2)
    assert confirmed == "退潮"
    assert state == {
        "pending": False,
        "pendingStage": None,
        "pendingSince": None,
        "confirmSlots": 2,
    }


def test_single_candidate_is_pending_with_start_slot() -> None:
    confirmed, state = confirm_stage(
        [("09:30", "退潮"), ("10:00", "退潮"), ("10:30", "高潮")], 2
    )
    assert confirmed == "退潮"
    assert state["pending"] is True
    assert state["pendingStage"] == "高潮"
    assert state["pendingSince"] == "10:30"


def test_two_consecutive_candidates_switch() -> None:
    confirmed, state = confirm_stage(
        [("09:30", "退潮"), ("10:00", "高潮"), ("10:30", "高潮")], 2
    )
    assert confirmed == "高潮"
    assert state["pending"] is False
    assert state["pendingSince"] is None


def test_candidate_change_restarts_count() -> None:
    confirmed, state = confirm_stage(
        [("09:30", "退潮"), ("10:00", "高潮"), ("10:30", "发酵")], 2
    )
    assert confirmed == "退潮"
    assert state["pending"] is True
    assert state["pendingStage"] == "发酵"
    assert state["pendingSince"] == "10:30"
    confirmed, state = confirm_stage(
        [("09:30", "退潮"), ("10:00", "高潮"), ("10:30", "发酵"), ("11:00", "发酵")], 2
    )
    assert confirmed == "发酵"
    assert state["pending"] is False


def test_revert_to_confirmed_clears_candidate() -> None:
    confirmed, state = confirm_stage(
        [("09:30", "退潮"), ("10:00", "高潮"), ("10:30", "退潮")], 2
    )
    assert confirmed == "退潮"
    assert state["pending"] is False


def test_slots_one_is_raw_passthrough() -> None:
    points = [("09:30", "退潮"), ("10:00", "高潮"), ("10:30", "发酵")]
    confirmed, state = confirm_stage(points, 1)
    assert confirmed == "发酵"
    assert state["pending"] is False


def test_empty_sequence_is_defensive_empty_result() -> None:
    confirmed, state = confirm_stage([], 2)
    assert confirmed == ""
    assert state["pending"] is False


def test_confirm_slots_below_one_clamps_to_one() -> None:
    confirmed, state = confirm_stage([("09:30", "退潮"), ("10:00", "高潮")], 0)
    assert confirmed == "高潮"
    assert state["confirmSlots"] == 1


def test_stage_whitespace_is_stripped_before_compare() -> None:
    confirmed, state = confirm_stage([("09:30", " 退潮 "), ("10:00", "高潮")], 2)
    assert confirmed == "退潮"
