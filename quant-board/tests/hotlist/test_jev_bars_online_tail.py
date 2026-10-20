# -*- coding: utf-8 -*-
"""日线「线上补尾」测试（零网络：本地/线上取数都被 monkeypatch）。

背景（2026-10-20 用户报障实测）：本地 vipdoc（`D:/APP_SOFT/TDX`）末棒停在 2026-10-19，
因为闭市后没跑通达信盘后下载；旧逻辑「本地文件存在即用」→ 当日情绪叙事里
断板钱效/隔日溢价/个股位置/板序/板型全部写「TDX 日线缺失」不可算，而线上 mootdx
当天已有棒。修复=按需补尾（只补本地没有的日期）。

锁定口径：
1. 只补「比本地末棒更新的日期」——重叠日期一律本地为准（历史数字不被线上改写）；
2. **量纲必须归一**：线上 vol 单位=手、本地=股（实测恒 100），不归一会把「量能」算成 1/100
   （实测 002242 曾被算成「前 3 日均量的 0.01 倍」）；
3. 线上拿不到当日棒 → 如实不补（调用方继续 fail-visible 标注），不编造、不用 T-1 冒充当日；
4. 未声明日期上下文 / `JEV_BARS_ONLINE_TAIL=0` → 完全不碰线上（保持纯本地可复现）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import jev_label_jiuyan as runner  # noqa: E402


def _bar(date: str, close: float, vol: float, high: float | None = None) -> dict:
    return {"date": date, "close": close, "vol": vol, "high": high if high is not None else close}


LOCAL = [_bar("2026-10-16", 17.79, 9.68e7), _bar("2026-10-19", 18.69, 1.5266e8)]
# 线上：重叠日 vol 是「手」（=本地/100），外加上今日那根
ONLINE = [_bar("2026-10-16", 17.79, 968439.6), _bar("2026-10-19", 18.69, 1526622.9),
          _bar("2026-10-20", 20.56, 1180000.0)]


@pytest.fixture
def patched(monkeypatch):
    calls = {"online": 0}

    def _patched(local, online):
        # conftest 的离线护栏把 `_daily_bars` 整体换成空棒（防单测连真实节点），
        # 本文件要测的是 `_daily_bars` 自身行为 → 取回真实实现，只把两层取数打成假数据。
        monkeypatch.setattr(runner, "_daily_bars", runner._REAL_DAILY_BARS)
        monkeypatch.setattr(runner, "_local_daily_bars", lambda code: [dict(b) for b in local])
        def _online(code):
            calls["online"] += 1
            return [dict(b) for b in online]
        monkeypatch.setattr(runner, "_online_daily_bars", _online)
        runner._DAILY_BARS_CACHE.clear()
        runner._LOCAL_MISS.clear()
        runner._TAIL_MERGED.clear()
        runner._TAIL_FAIL_CODES.clear()
        runner._TAIL_FAIL_UNTIL.clear()
        runner._TAIL_VOL_SOURCE.clear()
        return calls

    yield _patched
    runner._DAILY_BARS_CACHE.clear()
    runner._LOCAL_MISS.clear()


def test_tail_merge_adds_today_and_normalizes_volume(patched):
    calls = patched(LOCAL, ONLINE)
    with runner.bars_need_upto("2026-10-20"):
        bars = runner._daily_bars("002242")
    assert [b["date"] for b in bars] == ["2026-10-16", "2026-10-19", "2026-10-20"]
    assert bars[-1]["close"] == 20.56
    # 量纲归一：今日 vol 与本地同尺（股），量能比才可能是 1 倍量级而不是 0.01
    ratio = bars[-1]["vol"] / ((bars[-2]["vol"] + bars[-3]["vol"]) / 2)
    assert 0.5 < ratio < 2.0, f"量能比 {ratio} 异常（量纲未归一？）"
    assert runner.bars_source_provenance()["tailMergedCodes"] == 1
    assert runner.bars_source_provenance()["tailVolCalib"] == {"overlap": 1, "assumed": 0}
    assert runner.bars_source_provenance()["tailMergedUpTo"] == "2026-10-20"
    assert calls["online"] == 1


def test_overlap_dates_keep_local_values(patched):
    bumped = [dict(b) for b in ONLINE]
    bumped[0]["close"] = 99.99          # 线上把重叠日改得面目全非
    bumped[0]["vol"] = 1.0
    patched(LOCAL, bumped)
    with runner.bars_need_upto("2026-10-20"):
        bars = runner._daily_bars("002242")
    by_date = {b["date"]: b for b in bars}
    assert by_date["2026-10-16"]["close"] == 17.79, "重叠日期必须以本地为准（历史不可被线上改写）"


def test_no_hint_or_env_off_never_calls_online(patched):
    calls = patched(LOCAL, ONLINE)
    assert [b["date"] for b in runner._daily_bars("002242")][-1] == "2026-10-19"
    assert calls["online"] == 0, "未声明日期上下文 → 不得外呼"
    monkeypatch_env = pytest.MonkeyPatch()
    monkeypatch_env.setenv("JEV_BARS_ONLINE_TAIL", "0")
    try:
        with runner.bars_need_upto("2026-10-20"):
            assert runner._daily_bars("002242")[-1]["date"] == "2026-10-19"
        assert calls["online"] == 0, "开关关闭 → 不得外呼（纯本地可复现）"
    finally:
        monkeypatch_env.undo()

def test_online_without_today_keeps_local_and_marks_miss(patched):
    patched(LOCAL, ONLINE[:2])           # 线上也没有今日棒（未收盘/上游缺当日）
    with runner.bars_need_upto("2026-10-20"):
        bars = runner._daily_bars("002242")
    assert bars[-1]["date"] == "2026-10-19", "拿不到就如实不补，不用 T-1 冒充当日"
    prov = runner.bars_source_provenance()
    assert prov["tailMissCodes"] == 1 and prov["tailMergedCodes"] == 0


def test_local_missing_falls_back_to_online_as_before(patched):
    calls = patched([], ONLINE)          # 本地无此股文件 → 旧行为：整段走线上
    with runner.bars_need_upto("2026-10-20"):
        bars = runner._daily_bars("002242")
    assert [b["date"] for b in bars][-1] == "2026-10-20"
    assert calls["online"] == 1
    assert "002242" in runner._LOCAL_MISS, "本地无文件 → 记 miss 交给线上（不铸造空棒）"


def test_merged_bars_are_cached_per_code(patched):
    calls = patched(LOCAL, ONLINE)
    with runner.bars_need_upto("2026-10-20"):
        runner._daily_bars("002242")
        runner._daily_bars("002242")
    assert calls["online"] == 1, "同一 code 同一日期上下文内只补一次"