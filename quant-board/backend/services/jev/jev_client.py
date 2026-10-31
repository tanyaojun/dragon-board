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
import os
import time
import urllib.error
import urllib.request


# CF 账户 ID 单一来源（2026-10-05 M2：此前字面量散落 4 处；仍可用 JEV_CF_ACCOUNT 覆盖）
DEFAULT_ACCOUNT_ID = "921cf15176f84c90ea49865334af32c6"

# 瞬时失败重试退避（秒）：2026-10-09 实测上游间歇性执行故障（500/2002）存在亚分钟级
# 抖动（同载荷 9 秒内 ✅→❌→✅），秒级重试可接住翻转窗口；重试仅消耗失败请求（0 token，零计费）。
# 2026-10-19 加长尾（2s/5s/15s/30s，共 5 次尝试）：连板情绪 10-19 日判定因网络层
# TLS 重置（`[SSL: UNEXPECTED_EOF_WHILE_READING]`，usage={} 即 0 token）在旧的 3 次尝试
# （2s/5s 间距过近，落在同一抖动窗内）未恢复而 degraded；实测对 api.typesafe.ai 连续
# 连接约 2-5 成失败、间隔 15s 后失败率明显回落，故退避尾部拉长到 30s。
# 全部失败仍返回最后一次 failure envelope（fail-visible，绝不伪造成功）。
# 尝试次数 = len(JEV_RETRY_DELAYS) + 1（首试 + 4 段退避，共 5 次）。
JEV_RETRY_DELAYS: tuple[float, ...] = (2.0, 5.0, 15.0, 30.0)


def _envelope_completed(envelope: dict) -> bool:
    """envelope 是否已拿到 Completed 结果（决定是否继续重试）。"""
    return bool(envelope.get("success")) and (
        (envelope.get("result") or {}).get("state") == "Completed"
    )


def _call_primary(account_id: str, api_token: str, state: dict, questions: dict,
                  model: str = "typesafe/jev", timeout: int = 60) -> tuple[dict, int]:
    """单次 CF ai/run 调用；网络层/非法响应体不拋异常，返回 failure envelope（fail-visible）。"""
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


def _with_retry(attempt) -> tuple[dict, int]:
    """共享重试：未拿到 Completed 时按 JEV_RETRY_DELAYS 退避重试（默认首试+2 次）。"""
    envelope, latency_ms = attempt()
    for delay in JEV_RETRY_DELAYS:
        if _envelope_completed(envelope):
            return envelope, latency_ms
        time.sleep(delay)
        envelope, latency_ms = attempt()
    return envelope, latency_ms


def call_jev(account_id: str, api_token: str, state: dict, questions: dict,
             model: str = "typesafe/jev", timeout: int = 60) -> tuple[dict, int]:
    """CF 网关通道 ai/run；未拿到 Completed 时按 JEV_RETRY_DELAYS 退避重试。"""
    return _with_retry(lambda: _call_primary(account_id, api_token, state, questions, model, timeout))


# ── 官方直连通道（api.typesafe.ai；2026-10-09 CF 上游故障期间接入）──
# 请求体扁平（state/model/questions 顶层），响应亦扁平；统一适配成 CF envelope，
# parse_jev_response 下游零改动。451 地区封锁需经代理（JEV_TYPESAFE_PROXY）。
TYPESAFE_API_URL = "https://api.typesafe.ai/v1/systemone"


def _typesafe_to_envelope(resp: dict) -> dict:
    """官方扁平响应 → CF envelope（result.state=Completed + result.result）。"""
    return {"success": True,
            "result": {"state": "Completed",
                       "result": {"model": resp.get("model"), "answers": resp.get("answers"),
                                  "usage": resp.get("usage")}}}


def _call_typesafe_primary(api_token: str, state, questions: dict,
                           model: str = "jev-latest", timeout: int = 60,
                           proxy: str | None = None) -> tuple[dict, int]:
    """单次官方直连；网络层/HTTP 错误不抛异常，返回 failure envelope（fail-visible）。"""
    body = json.dumps({"state": state, "model": model, "questions": questions}).encode()
    req = urllib.request.Request(TYPESAFE_API_URL, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {api_token}")
    req.add_header("Content-Type", "application/json")
    opener = (urllib.request.build_opener(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
              if proxy else urllib.request.build_opener())
    t0 = time.time()
    try:
        with opener.open(req, timeout=timeout) as r:
            return _typesafe_to_envelope(json.loads(r.read())), int((time.time() - t0) * 1000)
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode()[:300]
        except Exception:
            detail = f"HTTP {e.code}"
        return {"success": False,
                "errors": [{"message": detail, "code": e.code}]}, int((time.time() - t0) * 1000)
    except (urllib.error.URLError, TimeoutError, OSError,
            http.client.HTTPException, json.JSONDecodeError) as e:
        return {"success": False,
                "errors": [{"message": f"network: {type(e).__name__}: {str(e)[:200]}"}]}, int((time.time() - t0) * 1000)


def call_jev_typesafe(api_token: str, state, questions: dict,
                      model: str = "jev-latest", timeout: int = 60,
                      proxy: str | None = None) -> tuple[dict, int]:
    """官方直连通道；同套退避重试。"""
    return _with_retry(lambda: _call_typesafe_primary(api_token, state, questions, model, timeout, proxy))


def dispatch_jev_call(state: dict, questions: dict, *, cf_account: str | None = None,
                      cf_token: str | None = None, timeout: int = 60) -> tuple[dict, int]:
    """通道选择单一事实源（2026-10-31）：

    JEV_TYPESAFE_KEY 存在 → 官方直连（api.typesafe.ai；451 地区封锁需经
    JEV_TYPESAFE_PROXY 代理，默认 model=jev-latest）；
    否则 → CF 网关（api.cloudflare.com ai/run，model=typesafe/jev）。

    两条通道返回同形状 envelope，parse_jev_response 下游零改动。
    cf_account/cf_token 缺省时从环境读取（调用方需已确保 .env.local 入 environ；
    实测 2026-10-31：CF 网关上游对部分区域返回 "Model unavailable in this
    region"，生产必须优先走 typesafe 直连，勿再直写 call_jev）。
    sentiment_compute._dispatch_jev 为历史等价实现（含 enabled 门），暂保留。
    """
    ts_key = os.environ.get("JEV_TYPESAFE_KEY", "").strip()
    if ts_key:
        proxy = os.environ.get("JEV_TYPESAFE_PROXY", "").strip() or None
        return call_jev_typesafe(ts_key, state=state, questions=questions,
                                 model="jev-latest", timeout=timeout, proxy=proxy)
    account = (cf_account or os.environ.get("JEV_CF_ACCOUNT") or "").strip() or DEFAULT_ACCOUNT_ID
    token = (cf_token or os.environ.get("JEV_CF_TOKEN") or "").strip()
    return call_jev(account, token, state=state, questions=questions,
                    model="typesafe/jev", timeout=timeout)


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
