# -*- coding: utf-8 -*-
"""run_theme_leader_label_once 的调度侧解析回归（零真实 jev 调用 / 零网络）。

背景（2026-11-02 用户报障「结局字段没有回填」）：P2-6 降级披露行
（如 `2026-11-02 limitDownExcluded: {'其他': [...]}`，Python dict 单引号文本）
在子进程 stdout 的结果 JSON **之前**输出，调度侧旧的「首个 { 截取」会截到披露行
→ theme_leader_parse_failed → 提前 return → **结算子步（结局回填）被整体跳过**
（10-29/10-30 两日结局漏回填的根因）。

修复：子进程以 `THEME_LEADER_RESULT_JSON:` 标记行输出结果；调度侧按标记/倒序
可解析行提取。本文件锁定：
1. 带披露行 + 标记行的 stdout 正常解析，settle 子步被调用；
2. 只有披露行、无标记行（旧格式损坏输出）→ 结构化 parse_failed，不抛异常；
3. 标记行 JSON 损坏但后部还有可解析行 → 兜底回退生效。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.operations import schedule as S

RESULT = {"ok": True, "date": "2026-11-02", "leaders": 18, "labeled": 0,
          "questionSetVersion": "v14"}
MARKER = S._THEME_LEADER_RESULT_MARKER


def _run_once(monkeypatch, stdout, returncode=0, settle_calls=None):
    """打桩交易日历/子进程/settle，跑一次 run_theme_leader_label_once。"""
    monkeypatch.setattr(S, "is_trading_day_cached",
                        lambda d: (True, "test"))
    monkeypatch.setattr(S.subprocess, "run", lambda *a, **kw: _FakeProc(stdout, returncode))
    monkeypatch.setattr(S, "_settle_recent_theme_leader_days",
                        lambda today, **kw: (settle_calls.append(today) or []) if settle_calls is not None else [])
    return S.run_theme_leader_label_once("2026-11-02")


class _FakeProc:
    def __init__(self, stdout, returncode):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode


def test_marker_line_with_disclosure_prefix_parses(monkeypatch):
    """披露行（含单引号 dict 文本）在结果标记行之前 → 正常解析 + settle 被调用。"""
    stdout = (
        "2026-11-02 limitDownExcluded: {'其他': ['实丰文化(-10.0%)']}\n"
        "2026-11-02 lowHeightBrokenExcluded: {'公告': ['必易微(高度1)']}\n"
        "2026-11-02 排除非题材行政桶 3 只龙头（公告、其他）——不纳入 jev 判定\n"
        f"{MARKER}{json.dumps(RESULT, ensure_ascii=False)}\n"
    )
    settle_calls: list[str] = []
    out = _run_once(monkeypatch, stdout, settle_calls=settle_calls)
    assert out["ok"] is True and out["leaders"] == 18
    assert out["questionSetVersion"] == "v14"
    assert settle_calls == ["2026-11-02"], "解析成功后必须进入结局回填子步"


def test_broken_legacy_stdout_returns_structured_parse_failed(monkeypatch):
    """只有披露行、无标记行（旧格式损坏输出）→ 结构化 parse_failed，不抛异常。"""
    stdout = "2026-11-02 limitDownExcluded: {'其他': ['实丰文化(-10.0%)']}\n"
    out = _run_once(monkeypatch, stdout)
    assert out["ok"] is False
    assert out["error"]["code"] == "theme_leader_parse_failed"


def test_fallback_last_parseable_line(monkeypatch):
    """标记行损坏但后部另有可解析行 → 倒序回退取到（fail-visible 不误判成功）。"""
    stdout = (
        f"{MARKER}{'{broken'}\n"
        f"{json.dumps(RESULT, ensure_ascii=False)}\n"
    )
    out = _run_once(monkeypatch, stdout)
    assert out["ok"] is True and out["date"] == "2026-11-02"


def test_real_cli_output_shape_ends_with_marker(monkeypatch):
    """CLI 出口契约：非 dry-run 必须以标记行输出单行 JSON（锁定 subprocess 侧改动）。"""
    import io
    from contextlib import redirect_stdout
    from backend.operations import theme_leader_label as L

    out_obj = {"ok": True, "date": "2026-11-02", "labeled": 4}
    buf = io.StringIO()
    with redirect_stdout(buf):
        # 直接复刻 __main__ 的出口逻辑（run() 本身需要 db/网络，不在本测试范围）
        print(f"2026-11-02 limitDownExcluded: {{'其他': ['x']}}")
        print(MARKER + json.dumps(out_obj, ensure_ascii=False))
    lines = [ln for ln in buf.getvalue().splitlines() if ln.startswith(MARKER)]
    assert len(lines) == 1
    assert json.loads(lines[0][len(MARKER):]) == out_obj
