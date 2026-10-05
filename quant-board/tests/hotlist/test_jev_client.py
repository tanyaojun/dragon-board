# -*- coding: utf-8 -*-
"""jev 客户端 envelope 解析测试（阶段1 Task 2，不触网）。"""
from backend.services.jev.jev_client import parse_jev_response

ENVELOPE = {"result": {"state": "Completed", "result": {
    "model": "jev-1.13.0",
    "answers": {"stage": {"type": "choice", "choice": "retreat",
                          "probabilities": {"retreat": 0.82, "start": 0.04}, "confidence": 0.78},
                "temperature": {"type": "score", "score": 7.02,
                                "legend": {"0": "0", "1": "11", "2": "22", "3": "33", "4": "44",
                                           "5": "56", "6": "67", "7": "78", "8": "89", "9": "100"}}},
    "usage": {"input_tokens": 1121, "output_tokens": 124}}}, "success": True}


def test_parse_completed():
    p = parse_jev_response(ENVELOPE, latency_ms=1110)
    assert p["ok"] and p["model"] == "jev-1.13.0"
    assert p["answers"]["stage"]["choice"] == "retreat"
    assert p["usage"]["input_tokens"] == 1121 and p["latencyMs"] == 1110


def test_parse_incomplete_is_degraded():
    p = parse_jev_response({"result": {"state": "Errored"}}, latency_ms=10)
    assert not p["ok"] and p["errorCode"] == "not_completed"


def test_http_error_is_degraded():
    p = parse_jev_response({"success": False, "errors": [{"message": "HTTP 402 balance"}]}, latency_ms=5)
    assert not p["ok"] and "402" in p["errorDetail"]


def test_score_rescale_by_legend_size():
    p = parse_jev_response(ENVELOPE, latency_ms=1)
    assert p["scores"]["temperature"] == round(7.02 / 9 * 100, 1)  # 10 档锚点 → /9*100


# ---- 2026-10-05 批次A（C2/I1）：缺题 partial + score 解析层加固 ----

def test_partial_answers_marked_degraded_with_expected_keys():
    """Completed 但缺题 → degraded/partial_answers；已答部分保留，缺失题结构化留档。"""
    p = parse_jev_response(ENVELOPE, latency_ms=7,
                           expected_keys={"stage", "temperature", "crowding"})
    assert p["ok"] is False and p["errorCode"] == "partial_answers"
    assert "crowding" in p["errorDetail"]
    assert p["answers"]["stage"]["choice"] == "retreat"  # 已答部分不丢（fail-visible）


def test_all_expected_answers_ok():
    p = parse_jev_response(ENVELOPE, latency_ms=1, expected_keys={"stage", "temperature"})
    assert p["ok"] is True and p["errorCode"] is None


def test_score_missing_legend_not_negative():
    """legend 缺失：分数如实缺席，不再产出负数（旧实现 5/(-1)=-500）。"""
    env = {"result": {"state": "Completed",
                      "result": {"answers": {"t": {"type": "score", "score": 5}}}}}
    p = parse_jev_response(env, latency_ms=1)
    assert p["ok"] is True and p["scores"] == {}  # 缺失 ≠ 伪值


def test_score_missing_score_key_no_crash():
    env = {"result": {"state": "Completed",
                      "result": {"answers": {"t": {"type": "score", "legend": {"a": 1, "b": 2}}}}}}
    p = parse_jev_response(env, latency_ms=1)  # 旧实现 KeyError 穿透
    assert p["ok"] is True and p["scores"] == {}


def test_score_bool_score_rejected():
    env = {"result": {"state": "Completed",
                      "result": {"answers": {"t": {"type": "score", "score": True,
                                                    "legend": {"a": 1, "b": 2}}}}}}
    p = parse_jev_response(env, latency_ms=1)
    assert p["scores"] == {}  # bool 是 int 子类，显式拒绝


def test_call_jev_malformed_body_degraded_not_raise(monkeypatch):
    """I2：HTML 错误页/截断流 → degraded envelope，不炸调用方（旧实现 JSONDecodeError 穿透）。"""
    import json as _json
    from backend.services.jev import jev_client

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b"<html>502 Bad Gateway</html>"

    monkeypatch.setattr(jev_client.urllib.request, "urlopen", lambda req, timeout=None: _Resp())
    envelope, ms = jev_client.call_jev("acc", "tok", "state", {"q": 1})
    assert envelope["success"] is False
    assert "JSONDecodeError" in envelope["errors"][0]["message"]
    assert isinstance(ms, int)
