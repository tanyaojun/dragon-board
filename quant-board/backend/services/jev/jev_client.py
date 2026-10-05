# -*- coding: utf-8 -*-
"""jev 统一端点客户端：POST /accounts/{acc}/ai/run，input 包裹，envelope 解析。

通道事实与 fail-visible 约定见
quant-board/docs/hotlist-jev/hotlist-jev-sentiment-design.md §10/§12/§8：
非 Completed/缺 answers/答案缺题 一律 degraded，不伪造默认档位。

2026-10-05 批次A（解析层加固，审查 .tmp/jev-limitup-audit.md C2/I1/I2）：
- call_jev 捕获面补齐 json.JSONDecodeError / http.client.HTTPException
  （此前 HTML 错误页/截断流会带异常炸穿 run，与 fail-visible 注释相反）；
- parse_jev_response 增加可选 expected_keys：Completed 但缺题 → degraded/partial_answers，
  已答部分随 answers 保留（调用方幂等集合不得视为已完成，下轮重跑补齐）；
- score 题缺 legend/缺 score 不再产出负数或 KeyError，分数如实缺席（fail-visible）。
"""
from __future__ import annotations

import http.client
import json
import time
import urllib.error
import urllib.request


# CF 账户 ID 单一来源（2026-10-05 M2：此前字面量散落 4 处；仍可用 JEV_CF_ACCOUNT 覆盖）
DEFAULT_ACCOUNT_ID = "921cf15176f84c90ea49865334af32c6"


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
    except (urllib.error.URLError, TimeoutError, OSError,
            http.client.HTTPException, json.JSONDecodeError) as e:
        # 网络层（读超时/连接重置等）与非法响应体（HTML 错误页/截断流）：degraded 返回，不炸 run（fail-visible）
        return {"success": False,
                "errors": [{"message": f"network: {type(e).__name__}: {str(e)[:200]}"}]}, int((time.time() - t0) * 1000)


def parse_jev_response(envelope: dict, latency_ms: int,
                       expected_keys: set[str] | None = None) -> dict:
    """envelope → 解析结果。expected_keys 给出时做缺题校验（partial_answers=degraded）。"""
    inner = ((envelope.get("result") or {}).get("result")) or {}
    state = (envelope.get("result") or {}).get("state")
    if state != "Completed" or not inner.get("answers"):
        errs = envelope.get("errors") or []
        return {"ok": False, "errorCode": "http_error" if errs else "not_completed",
                "errorDetail": str(errs)[:300] if errs else f"state={state}", "latencyMs": latency_ms}
    answers = inner["answers"]
    scores: dict[str, float] = {}
    for k, a in answers.items():
        if a.get("type") != "score":
            continue
        score, legend = a.get("score"), a.get("legend") or {}
        denom = len(legend) - 1
        # legend 缺失/单档（分母<=0）或 score 非数：分数如实缺席，不产出负数/不崩（fail-visible）
        if not isinstance(score, (int, float)) or isinstance(score, bool) or denom <= 0:
            continue
        scores[k] = round(score / denom * 100, 1)
    base = {"model": inner.get("model"), "answers": answers, "scores": scores,
            "usage": inner.get("usage") or {}, "latencyMs": latency_ms}
    missing = sorted(set(expected_keys or ()) - {str(k) for k in answers})
    if missing:
        return {"ok": False, "errorCode": "partial_answers",
                "errorDetail": f"missing answers: {','.join(missing)}", **base}
    return {"ok": True, **base, "errorCode": None, "errorDetail": None}
