# -*- coding: utf-8 -*-
"""jev 统一端点客户端：POST /accounts/{acc}/ai/run，input 包裹，envelope 解析。

通道事实与 fail-visible 约定见
quant-board/docs/hotlist-jev/hotlist-jev-sentiment-design.md §10/§12/§8：
非 Completed/缺 answers 一律 degraded，不伪造默认档位。
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request

# score 锚点：0-100 共 10 档（jev 上限 10 档），返回 score 为下标期望，按 /9*100 还原
SCORE_ANCHORS = ["0", "11", "22", "33", "44", "56", "67", "78", "89", "100"]


def call_jev(account_id: str, api_token: str, state: dict, questions: dict,
             model: str = "typesafe/jev", timeout: int = 60) -> tuple[dict, int]:
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run"
    body = json.dumps({"model": model, "input": {"state": state, "questions": questions}}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_token}")
    req.add_header("Content-Type", "application/json")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), int((time.time() - t0) * 1000)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:300]
        except Exception:
            detail = f"HTTP {e.code}"
        return {"success": False, "errors": [{"message": detail}]}, int((time.time() - t0) * 1000)


def parse_jev_response(envelope: dict, latency_ms: int) -> dict:
    inner = ((envelope.get("result") or {}).get("result")) or {}
    state = (envelope.get("result") or {}).get("state")
    if state != "Completed" or not inner.get("answers"):
        errs = envelope.get("errors") or []
        return {"ok": False, "errorCode": "http_error" if errs else "not_completed",
                "errorDetail": str(errs)[:300] if errs else f"state={state}", "latencyMs": latency_ms}
    answers = inner["answers"]
    scores = {k: round(a["score"] / (len(a.get("legend") or {}) - 1 or 1) * 100, 1)
              for k, a in answers.items() if a.get("type") == "score"}
    return {"ok": True, "model": inner.get("model"), "answers": answers, "scores": scores,
            "usage": inner.get("usage") or {}, "latencyMs": latency_ms,
            "errorCode": None, "errorDetail": None}
