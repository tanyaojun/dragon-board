# -*- coding: utf-8 -*-
"""_confirm_jump（Jump 价格/量确认）单元测试。

2026-08-17 审计（G4）：_confirm_jump 无测试用例，且 half_hour 数据上 Jump 事件为 0，
路径从未被真实执行验证。规则：up 需 change ≥ jumpConfirmChangeMin 且 volumeRatio ≥
jumpConfirmVolumeRatioMin；down 需 change ≤ -jumpConfirmChangeMin 且 volumeRatio ≥
jumpConfirmVolumeRatioMin（放量配合）；不满足 → direction 降级 hold + unconfirmedReasons。
"""
import pytest

from backend.analysis.ranktrend.engine import RankTrendConfig, _confirm_jump


def cfg(**patch) -> RankTrendConfig:
    base = dict(RankTrendConfig().__dict__)
    base.update(patch)
    return RankTrendConfig(**base)


def jump(direction="up") -> dict:
    return {"direction": direction, "event": direction, "events": [{"direction": direction, "magnitude": 30}]}


def stock(change=3.0, volume_ratio=1.2) -> dict:
    return {"code": "000001", "change": change, "volumeRatio": volume_ratio}


# ---------- up 确认 ----------

def test_up_confirmed_with_price_and_volume() -> None:
    r = _confirm_jump(jump("up"), stock(change=3.0, volume_ratio=1.0), cfg())
    assert r["direction"] == "up"
    assert r["confirmed"] is True


def test_up_unconfirmed_without_price() -> None:
    r = _confirm_jump(jump("up"), stock(change=2.0, volume_ratio=1.5), cfg())
    assert r["direction"] == "hold"
    assert r["confirmed"] is False
    assert any("缺价格/量确认" in x for x in r["unconfirmedReasons"])


def test_up_unconfirmed_without_volume() -> None:
    r = _confirm_jump(jump("up"), stock(change=5.0, volume_ratio=0.8), cfg())
    assert r["direction"] == "hold"
    assert r["confirmed"] is False


def test_up_unconfirmed_when_missing_fields() -> None:
    r = _confirm_jump(jump("up"), {"code": "000001"}, cfg())
    assert r["direction"] == "hold"
    assert r["confirmed"] is False


# ---------- down 确认 ----------

def test_down_confirmed_with_price_and_volume() -> None:
    r = _confirm_jump(jump("down"), stock(change=-4.0, volume_ratio=1.3), cfg())
    assert r["direction"] == "down"
    assert r["confirmed"] is True


def test_down_unconfirmed_without_price() -> None:
    r = _confirm_jump(jump("down"), stock(change=-2.0, volume_ratio=1.2), cfg())
    assert r["direction"] == "hold"
    assert r["confirmed"] is False


def test_down_unconfirmed_without_volume() -> None:
    r = _confirm_jump(jump("down"), stock(change=-5.0, volume_ratio=0.5), cfg())
    assert r["direction"] == "hold"
    assert r["confirmed"] is False


# ---------- hold / 无方向 ----------

def test_hold_passthrough() -> None:
    r = _confirm_jump(jump("hold"), stock(change=5.0, volume_ratio=2.0), cfg())
    assert r["direction"] == "hold"
    assert r["confirmed"] is True  # hold 视为无确认需求


def test_none_direction_passthrough() -> None:
    r = _confirm_jump({"direction": None, "events": []}, stock(change=5.0), cfg())
    assert r["direction"] is None


# ---------- config 生效 ----------

def test_config_thresholds_effective() -> None:
    # 门槛提高：change=3.0 不再满足 5.0
    c = cfg(jumpConfirmChangeMin=5.0)
    r = _confirm_jump(jump("up"), stock(change=3.0, volume_ratio=2.0), c)
    assert r["direction"] == "hold"
    # 量门槛关闭：volumeRatio 不参与
    c2 = cfg(jumpConfirmVolumeRatioMin=0.0)
    r2 = _confirm_jump(jump("up"), stock(change=3.0, volume_ratio=0.1), c2)
    assert r2["direction"] == "up"
