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
