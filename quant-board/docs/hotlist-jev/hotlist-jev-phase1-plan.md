# Jev 热榜情绪轨道 — 阶段 1 回放验证实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用近 30 个交易日的 half_hour 锚定帧重建 jev state 回放（~300 次调用，<$0.05），对比 jev 档位/概率 vs 规则档位 vs 次日实际溢价，产出信息增量判定报告。

**Architecture:** 三个新模块：`analysis/hotlist/jev_state.py`（state 构建器，纯函数）、`services/jev/jev_client.py`（统一 /ai/run 调用+响应解析）、`data/repositories/hotlist_jev_repo.py`（落库 upsert）；编排脚本 `operations/jev_replay.py`（CLI dry-run/全量）与 `operations/jev_replay_report.py`（对比报告）。数据事实（已实地验证）：帧 type=half_hour 111 天含 limitSummary{thsPools,zhaban,continuousBoards}+indices{sh,hs300,zz500,zz1000}；行 type=half_hour ~110 天×10 槽×~220 只（无行级 stage，经 snapshot_analysis.analysis.displayStatus.stage 按 code+snapshotId 关联）；情绪桶 snapshotType=half_hour 103 天 slots≥8，含 stage(中文五档)/confidence/metrics.layers.{top20,top50,top100,all}.stageCounts。数据库 `dragon_board_quant`（settings.py 默认名 DragonBoardData 与实际不符，回放脚本显式用实际库名并注释）。

**Tech Stack:** pymongo、Python urllib（无新依赖）、pytest（QuantBoard 现有测试结构）。

**窗口:** 2026-08-11 → 2026-09-24（30 个交易日，排除当日 09-28 半日）；slots=盘中 10 槽；~300 次调用顺序执行（每次间隔 ≥0.3s）。

**数据红线:** fail-visible——缺字段进 quality.degraded、状态照常构建与调用；无行/无情绪桶的槽位跳过并记录 no_data 文档；不伪造 0 值；令牌经环境变量传入（读 Pi models.json 的方式仅限本机 shell，不入仓库）。

---

### Task 1: jev_state 构建器（TDD）

**Files:**
- Create: `quant-board/backend/analysis/hotlist/jev_state.py`
- Test: `quant-board/backend/tests/analysis/hotlist/test_jev_state.py`（按现有 pytest 目录结构，若无此目录则 `quant-board/backend/tests/` 下就近建）

- [ ] **Step 1: 写失败测试**（关键断言）

```python
"""jev_state 构建器测试：shape、fail-visible、不伪造。"""
from backend.analysis.hotlist.jev_state import build_replay_state

def _frame(limit=None, indices=None):
    return {"tradingDate": "2026-09-01", "slotTime": "10:30", "datasetId": "dragonboard_live",
            "type": "half_hour", "timestamp": "2026-09-01T10:31:00",
            "limitSummary": limit if limit is not None else {"thsPools": {}, "zhaban": {}},
            "indices": indices if indices is not None else {"sh": {"change": -12.2}}}

def _sentiment(counts):
    return {"stage": "退潮", "confidence": 70,
            "metrics": {"layers": {"top50": {"stageCounts": counts}}}}

def test_state_shape_and_budget():
    st = build_replay_state(
        frame=_frame(indices={"sh": {"change": -12.2}, "zz500": {"change": -23.4}}),
        rows=[{"code": "000592", "name": "平潭发展", "rank": 1, "heat": 95, "pctChange": 9.98,
               "speed": 3.2, "limitUpPrice": 9.66, "price": 9.66, "mainTheme": "算力",
               "snapshotId": "s1", "platforms": ["ths", "xq"]}],
        analysis_by_code={"000592": "ignition"},
        sentiment_doc=_sentiment({"ignition": 1, "expansion": 0, "crowded": 0, "reversal": 0, "cooling": 0, "unknown": 0}),
        prev_counts={"ignition": 0, "expansion": 0, "crowded": 0, "reversal": 0, "cooling": 0, "unknown": 0},
        prev_codes=set())
    assert st["market"]["zt"] == 1 and st["lifecycle"]["counts"]["ignition"] == 1
    assert st["stocks"][0]["s"] == "ignition" and st["stocks"][0]["zt"] is True
    assert st["hotlist"]["newEntries"] == 1
    assert isinstance(__import__("json").dumps(st, ensure_ascii=False), str)
    assert len(__import__("json").dumps(st, ensure_ascii=False)) < 20000  # ≈5K token 预算

def test_missing_fields_degrade_not_fabricate():
    st = build_replay_state(frame=_frame(limit=None), rows=[], analysis_by_code={},
                            sentiment_doc=None, prev_counts=None, prev_codes=set())
    assert st["quality"]["degraded"], "缺情绪桶/缺行必须记录 degraded"
    assert st["stocks"] == []            # 真实缺失保持空，不伪造
    assert st["lifecycle"]["counts"] is None  # 缺源保持 None，不伪造全零

def test_no_row_stage_marked_unknown():
    st = build_replay_state(frame=_frame(), rows=[{"code": "X", "name": "X", "rank": 1, "heat": 1,
                                                   "pctChange": 1.0, "snapshotId": "s1"}],
                            analysis_by_code={}, sentiment_doc=_sentiment(
                                {"ignition": 0, "expansion": 0, "crowded": 0, "reversal": 0, "cooling": 0, "unknown": 1}),
                            prev_counts=None, prev_codes=set())
    assert st["stocks"][0]["s"] is None and "stock_stage_missing" in st["quality"]["degraded"][0]
```

- [ ] **Step 2: 跑测试确认失败**：`./.venv/Scripts/python.exe -m pytest backend/tests/analysis/hotlist/test_jev_state.py -x -q` → FAIL (ModuleNotFoundError)

- [ ] **Step 3: 最小实现**

```python
"""jev state 构建器：把锚定帧/行/情绪桶压缩为 jev 评估 state（纯函数，无 IO）。

fail-visible：缺源记 quality.degraded，保持 None/空，不伪造零值。见
quant-board/docs/hotlist-jev/hotlist-jev-sentiment-design.md §5/§8。
"""
from __future__ import annotations

STAGE_KEYS = ("ignition", "expansion", "crowded", "reversal", "cooling", "unknown")
_STOCK_LIMIT = 15
_ZT_EPS = 0.999


def _degraded(items: list, code: str, detail: str) -> None:
    items.append({"code": code, "detail": detail[:120]})


def _market(frame: dict, deg: list) -> dict:
    ls = frame.get("limitSummary") or {}
    idx = frame.get("indices") or {}
    m: dict = {}
    if "sh" in idx: m["sh"] = round(idx["sh"]["change"], 2)
    if "zz500" in idx: m["zz500"] = round(idx["zz500"]["change"], 2)
    zt = ls.get("ztCount"); dt = ls.get("dtCount"); zb = ls.get("zhabanRate")
    if zt is None and isinstance(ls.get("thsPools"), dict):
        zt = ls["thsPools"].get("ztCount")
    for k, v in (("zt", zt), ("dt", dt), ("zhabanRate", zb)):
        if v is not None: m[k] = v
        else: _degraded(deg, "market", f"limitSummary.{k} 缺失")
    return m


def _lifecycle(sentiment_doc: dict | None, prev_counts: dict | None, deg: list) -> dict | None:
    if not sentiment_doc:
        _degraded(deg, "lifecycle", "情绪桶文档缺失")
        return None
    layers = (sentiment_doc.get("metrics") or {}).get("layers") or {}
    layer = layers.get("top50") or layers.get("all") or {}
    counts = layer.get("stageCounts")
    if counts is None:
        _degraded(deg, "lifecycle", "metrics.layers.top50.stageCounts 缺失")
        return None
    out = {"counts": {k: int(counts.get(k) or 0) for k in STAGE_KEYS}}
    if prev_counts:
        out["migration"] = {k: int(counts.get(k) or 0) - int(prev_counts.get(k) or 0) for k in STAGE_KEYS}
    return out


def _stocks(rows: list, analysis_by_code: dict, deg: list) -> list:
    def sort_key(r):
        return (-(r.get("heat") or 0), r.get("rank") or 9999)
    out = []
    for r in sorted(rows, key=sort_key)[:_STOCK_LIMIT]:
        price, lup = r.get("price"), r.get("limitUpPrice")
        zt = bool(price and lup and price >= lup * _ZT_EPS)
        stage = analysis_by_code.get(r.get("code"))
        if stage is None:
            _degraded(deg, "stock_stage_missing", f"{r.get('code')} 无 displayStatus.stage")
        out.append({"n": r.get("name"), "s": stage, "pct": round(r.get("pctChange") or 0, 2),
                    "spd": round(r["speed"], 2) if r.get("speed") is not None else None,
                    "zt": zt, "heat": r.get("heat"), "th": r.get("mainTheme")})
    return out


def build_replay_state(frame: dict, rows: list, analysis_by_code: dict,
                       sentiment_doc: dict | None, prev_counts: dict | None,
                       prev_codes: set) -> dict:
    deg: list = []
    codes = {r.get("code") for r in rows if r.get("code")}
    return {
        "asOf": f"{frame.get('tradingDate')} {frame.get('slotTime')}",
        "slot": (frame.get("slotTime") or "").replace(":", "") + "+0",
        "market": _market(frame, deg),
        "lifecycle": _lifecycle(sentiment_doc, prev_counts, deg),
        "stocks": _stocks(rows, analysis_by_code, deg),
        "hotlist": {"platforms": len({p for r in rows for p in (r.get("platforms") or [])}),
                    "entries": len(rows),
                    "newEntries": len(codes - set(prev_codes or set()))},
        "quality": {"degraded": deg},
    }
```

- [ ] **Step 4: 跑测试通过**（同 Step 2 命令 → PASS）
- [ ] **Step 5: Commit** `git add` 三文件 → `feat(hotlist-jev): jev_state 构建器（阶段1 TDD）`

### Task 2: jev 客户端（TDD，mock HTTP）

**Files:**
- Create: `quant-board/backend/services/jev/__init__.py`、`quant-board/backend/services/jev/jev_client.py`
- Test: `quant-board/backend/tests/services/jev/test_jev_client.py`

- [ ] **Step 1: 失败测试**

```python
from backend.services.jev.jev_client import parse_jev_response

ENVELOPE = {"result": {"state": "Completed", "result": {
    "model": "jev-1.13.0",
    "answers": {"stage": {"type": "choice", "choice": "retreat", "probabilities": {"retreat": 0.82}, "confidence": 0.78},
                "temperature": {"type": "score", "score": 7.02, "legend": {"9": "100"}}},
    "usage": {"input_tokens": 1121, "output_tokens": 124}}}, "success": True}

def test_parse_completed():
    p = parse_jev_response(ENVELOPE, latency_ms=1110)
    assert p["ok"] and p["model"] == "jev-1.13.0" and p["answers"]["stage"]["choice"] == "retreat"
    assert p["usage"]["input_tokens"] == 1121 and p["latencyMs"] == 1110

def test_parse_incomplete_is_degraded():
    p = parse_jev_response({"result": {"state": "Errored"}}, latency_ms=10)
    assert not p["ok"] and p["errorCode"] == "not_completed"

def test_score_rescale_10anchors():
    p = parse_jev_response(ENVELOPE, latency_ms=1)
    assert p["scores"]["temperature"] == round(7.02 / 9 * 100, 1)
```

- [ ] **Step 2: 确认失败 → Step 3: 实现**

```python
"""jev 统一端点客户端：POST /accounts/{acc}/ai/run，input 包裹，envelope 解析。

fail-visible：非 Completed/缺 answers 一律 degraded，不伪造默认档位。§8。
"""
from __future__ import annotations
import json, time, urllib.request

SCORE_ANCHORS = [str(i) for i in range(0, 101, 11)][:10]  # 0..100 共 10 档


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
        try: detail = e.read().decode()[:300]
        except Exception: detail = f"HTTP {e.code}"
        return {"success": False, "errors": [{"message": detail}]}, int((time.time() - t0) * 1000)


def parse_jev_response(envelope: dict, latency_ms: int) -> dict:
    inner = ((envelope.get("result") or {}).get("result")) or {}
    if (envelope.get("result") or {}).get("state") != "Completed" or not inner.get("answers"):
        errs = envelope.get("errors") or []
        return {"ok": False, "errorCode": "not_completed" if not errs else "http_error",
                "errorDetail": str(errs)[:300], "latencyMs": latency_ms}
    answers = inner["answers"]
    scores = {k: round(a["score"] / (len(a.get("legend", {})) - 1 or 1) * 100, 1)
              for k, a in answers.items() if a.get("type") == "score"}
    return {"ok": True, "model": inner.get("model"), "answers": answers, "scores": scores,
            "usage": inner.get("usage") or {}, "latencyMs": latency_ms}
```

- [ ] **Step 4: 测试通过 → Step 5: Commit** `feat(hotlist-jev): jev 客户端+envelope 解析（阶段1 TDD）`

### Task 3: 落库 repo + 回放 runner

**Files:**
- Create: `quant-board/backend/operations/jev_replay.py`（repo upsert 内联，量小不单独拆 service）

- [ ] **Step 1: runner 实现**（核心逻辑，CLI）

```python
"""jev 阶段1 回放 runner：历史锚定帧重建 state → jev → hotlist_jev_sentiment。

用法（Git Bash，令牌不入仓库）：
  export JEV_CF_TOKEN=<token>
  ./.venv/Scripts/python.exe -m backend.operations.jev_replay \
      --start 2026-08-11 --end 2026-09-24 --dry-run   # 先 2 天验证
幂等：upsert _id={datasetId}:{snapshotType}:{tradingDate}:{slotKey}，origin=replay。
"""
import argparse, json, os, time
from pymongo import MongoClient
from backend.analysis.hotlist.jev_state import build_replay_state
from backend.services.jev.jev_client import call_jev, parse_jev_response, SCORE_ANCHORS

QUESTIONS = {
    "stage": {"type": "choice", "instructions": "当前A股短线情绪处于哪一档？",
              "criteria": {"ice": "冰点：赚钱效应殆尽，普遍观望", "start": "启动：修复迹象，试错资金进场",
                           "ferment": "发酵：赚钱效应扩散，连板增多", "climax": "高潮：全面亢奋，涨停潮",
                           "retreat": "退潮：高位集体走弱，炸板增多"}},
    "heating_30m": {"type": "noul", "instructions": "未来30分钟市场短线情绪升温（赚钱效应改善）的概率"},
    "retreat_eod": {"type": "noul", "instructions": "收盘前出现明显退潮（炸板潮/高位批量开板）的概率"},
    "temperature": {"type": "score", "instructions": "短线情绪温度（0=彻底冰点，100=极度亢奋）", "criteria": SCORE_ANCHORS},
    "crowding": {"type": "score", "instructions": "高位拥挤度（0=无人问津，100=极度拥挤危险）", "criteria": SCORE_ANCHORS},
}
SLOTS = ["09:30", "10:00", "10:30", "11:00", "11:30", "13:00", "13:30", "14:00", "14:30", "15:00"]


def run(start: str, end: str, dry_run: bool, token: str, acc: str, limit_days: int | None):
    db = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=5000)["dragon_board_quant"]
    fr, sr, hs, sa = db["snapshot_frames"], db["snapshot_stock_rows"], db["hotlist_sentiment"], db["snapshot_analysis"]
    dates = sorted({d["tradingDate"] for d in hs.find({"snapshotType": "half_hour"}, {"tradingDate": 1})
                    if d.get("tradingDate") and start <= d["tradingDate"] <= end})
    if dry_run: dates = dates[-2:]
    if limit_days: dates = dates[-limit_days:]
    n_ok = n_deg = n_skip = 0
    for di, date in enumerate(dates):
        prev_counts = prev_codes = None
        for slot in SLOTS:
            frame = fr.find_one({"type": "half_hour", "tradingDate": date, "slotTime": slot})
            sent = hs.find_one({"snapshotType": "half_hour", "tradingDate": date, "slotTime": slot})
            rows = list(sr.find({"type": "half_hour", "tradingDate": date, "slotTime": slot}))
            _id = f"{(frame or sent or {}).get('datasetId', 'dragonboard_live')}:half_hour:{date}:{slot}"
            if not frame or not rows or not sent:
                db["hotlist_jev_sentiment"].replace_one(
                    {"_id": _id},
                    {"_id": _id, "origin": "replay", "tradingDate": date, "slotKey": slot,
                     "status": "no_data", "detail": {"frame": bool(frame), "rows": len(rows), "sentiment": bool(sent)}},
                    upsert=True)
                n_skip += 1; continue
            snap_ids = {r.get("snapshotId") for r in rows if r.get("snapshotId")}
            ana = {a["code"]: ((a.get("analysis") or {}).get("displayStatus") or {}).get("stage")
                   for a in sa.find({"snapshotId": {"$in": list(snap_ids)}},
                                    {"code": 1, "analysis.displayStatus.stage": 1}) if a.get("code")}
            state = build_replay_state(frame, rows, ana, sent, prev_counts, prev_codes)
            if dry_run and slot == SLOTS[0]:
                print(f"[dry] {date} {slot} state_bytes={len(json.dumps(state, ensure_ascii=False))}")
            env, ms = call_jev(acc, token, state, QUESTIONS)
            parsed = parse_jev_response(env, ms)
            doc = {"_id": _id, "origin": "replay", "datasetId": "dragonboard_live", "snapshotType": "half_hour",
                   "tradingDate": date, "slotKey": slot, "asOf": state["asOf"],
                   "status": "ok" if parsed["ok"] else "degraded",
                   "ruleStage": sent.get("stage"), "ruleConfidence": sent.get("confidence"),
                   "stateRaw": state, "questionsRaw": QUESTIONS,
                   "responseRaw": env if not parsed["ok"] else None,
                   "answers": parsed.get("answers"), "scores": parsed.get("scores"),
                   "model": parsed.get("model"), "usage": parsed.get("usage"), "latencyMs": ms,
                   "errorCode": parsed.get("errorCode"), "errorDetail": parsed.get("errorDetail"),
                   "computedAt": time.strftime("%Y-%m-%dT%H:%M:%S")}
            if not dry_run:
                db["hotlist_jev_sentiment"].replace_one({"_id": _id}, doc, upsert=True)
            n_ok += parsed["ok"]; n_deg += not parsed["ok"]
            prev_counts = ((sent.get("metrics") or {}).get("layers") or {}).get("top50", {}).get("stageCounts")
            prev_codes = {r.get("code") for r in rows if r.get("code")}
            time.sleep(0.3)
        print(f"[{di+1}/{len(dates)}] {date} done (ok={n_ok} deg={n_deg} skip={n_skip})")
    print("FINAL:", {"ok": n_ok, "degraded": n_deg, "skipped": n_skip})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True); ap.add_argument("--end", required=True)
    ap.add_argument("--dry-run", action="store_true"); ap.add_argument("--limit-days", type=int)
    args = ap.parse_args()
    token = os.environ.get("JEV_CF_TOKEN") or ""
    acc = os.environ.get("JEV_CF_ACCOUNT", "921cf15176f84c90ea49865334af32c6")
    assert token, "需要 JEV_CF_TOKEN 环境变量"
    run(args.start, args.end, args.dry_run, token, acc, args.limit_days)
```

- [ ] **Step 2: dry-run 2 天**（上面的命令）→ 期望：`state_bytes` < 8000、无异常退出、最后打印 FINAL 计数
- [ ] **Step 3: 小额实测 2 天（真调用）**：去掉 --dry-run 加 `--limit-days 2` → 期望 ok 主导、degraded 有 errorDetail
- [ ] **Step 4: 全量 30 天**：`--start 2026-08-11 --end 2026-09-24`（~300 次调用，~5 分钟）
- [ ] **Step 5: Commit** `feat(hotlist-jev): 阶段1 回放 runner + dry-run/全量执行记录`

### Task 4: 对比分析报告

**Files:**
- Create: `quant-board/backend/operations/jev_replay_report.py`
- Output: `quant-board/docs/hotlist-jev/phase1-replay-report.md`

- [ ] **Step 1: 分析脚本**——四组指标（全部从 hotlist_jev_sentiment（origin=replay,status=ok）+ hotlist_sentiment + snapshot_frames 读，纯只读）：
  1. **档位对照**：jev answers.stage.choice（英文）→中文映射（ice→冰点…retreat→退潮）vs doc.ruleStage：一致率 + 混淆矩阵（哪几档 jev 爱误判）。
  2. **日内前瞻**：heating_30m 高低分组（>0.6 vs <0.4）的下一槽 zhabanRate/涨停数变化（帧 limitSummary 对比）；retreat_eod 高分组（>0.6）当日 15:00 槽 rule stage 是否恶化（rule stage ∈ {retreat} 或 15:00 槽 zhabanRate > 当日 10:30 槽 +5pct）。
  3. **次日溢价**：crowding 高分组（>70） vs 低分组（<40）的次日 promotionRate（次日各槽 limitSummary 晋级率，缺则次日 ztCount 环比）与次日 crowded/cooling stageCounts 变化。
  4. **退化率**：degraded/total，全部列 errorDetail 分布。
- [ ] **Step 2: 生成报告**（md，含四组指标表 + 每组一句解读 + 结论：jev 是否提供规则链外信息增量的判定 PASS_CANDIDATE / INSUFFICIENT / REJECT 三选一，判定标准写明）
- [ ] **Step 3: Commit** `docs(hotlist-jev): 阶段1 回放验证报告`
- [ ] **Step 4: 向用户汇报结论**（对照 spec §9：PASS_CANDIDATE 才讨论阶段 2 盘中旁观）

## Self-Review 记录

- Spec 覆盖：§5 state→Task 1；§6 五问→Task 3 QUESTIONS（score 用定案锚点数组）；§7 落库→Task 3（origin=replay 补充字段）；§8 fail-visible→Task 1 测试+runner no_data；§9 阶段 1 验收→Task 4。
- 占位符：无 TBD；Task 4 指标全部给出可计算定义。
- 类型一致性：SCORE_ANCHORS（client）与 QUESTIONS 引用一致；parse 输出 {ok,model,answers,scores,usage,latencyMs,errorCode,errorDetail} 与 runner doc 字段一致；build_replay_state 签名与测试/runner 调用一致。
