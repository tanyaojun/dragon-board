from __future__ import annotations

from typing import Any

from backend.services.theme.hotlist_sentiment_compute import compute_and_upsert_for_slot


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = list(rows)

    def sort(self, spec: list[tuple[str, int]]) -> "FakeCursor":
        for key, direction in reversed(spec):
            self.rows.sort(key=lambda row: row.get(key) or 0, reverse=direction < 0)
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeReplaceResult:
    matched_count = 0
    modified_count = 0
    upserted_id = "dragonboard_live:half_hour:2026-06-05"


class FakeCollection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.replace_calls: list[tuple[dict[str, Any], dict[str, Any], bool]] = []

    def find(self, query: dict[str, Any] | None = None, projection: dict[str, Any] | None = None) -> FakeCursor:
        query = query or {}
        rows = [row for row in self.rows if self._matches(row, query)]
        if projection:
            rows = [self._project(row, projection) for row in rows]
        return FakeCursor(rows)

    def find_one(
        self,
        query: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        rows = list(self.find(query or {}))
        if sort:
            rows = list(FakeCursor(rows).sort(sort))
        return rows[0] if rows else None

    def replace_one(
        self,
        query: dict[str, Any],
        doc: dict[str, Any],
        upsert: bool = False,
    ) -> FakeReplaceResult:
        self.replace_calls.append((query, doc, upsert))
        self.rows = [row for row in self.rows if not self._matches(row, query)]
        self.rows.append(doc)
        return FakeReplaceResult()

    @staticmethod
    def _project(row: dict[str, Any], projection: dict[str, Any]) -> dict[str, Any]:
        projected: dict[str, Any] = {}
        for key, enabled in projection.items():
            if not enabled:
                continue
            if "." not in key:
                projected[key] = row.get(key)
                continue
            # 点路径投影按真实 Mongo 语义展开为嵌套结构；行内路径缺失则该字段不出现
            value: Any = row
            found = True
            for part in key.split("."):
                if isinstance(value, dict) and part in value:
                    value = value[part]
                else:
                    found = False
                    break
            if not found:
                continue
            node = projected
            parts = key.split(".")
            for part in parts[:-1]:
                node = node.setdefault(part, {})
            node[parts[-1]] = value
        return projected

    @staticmethod
    def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
        for key, expected in query.items():
            actual = row.get(key)
            if isinstance(expected, dict) and "$in" in expected:
                if actual not in expected["$in"]:
                    return False
            elif isinstance(expected, dict) and "$ne" in expected:
                if actual == expected["$ne"]:
                    return False
            elif actual != expected:
                return False
        return True


class FakeMongoDb:
    def __init__(self) -> None:
        self.collections: dict[str, FakeCollection] = {
            "snapshot_frames": FakeCollection(),
            "snapshot_stock_rows": FakeCollection(),
            "hotlist_sentiment": FakeCollection(),
        }

    def __getitem__(self, name: str) -> FakeCollection:
        if name not in self.collections:
            self.collections[name] = FakeCollection()
        return self.collections[name]


def _seed_slot(fake_db) -> None:
    fake_db["snapshot_frames"].rows.append({
        "datasetId": "d1", "type": "half_hour", "tradingDate": "2026-06-05",
        "snapshotId": "snap-1030", "slotTime": "10:30", "timestamp": 5,
        "limitSummary": {"continuousBoards": {"yiban": 3, "erban": 1}, "zhaban": {}, "yesterdayZt": {}, "thsPools": {}},
    })
    fake_db["snapshot_stock_rows"].rows.append({
        "datasetId": "d1", "snapshotId": "snap-1030", "code": "000001", "name": "甲",
        "compRank": 1, "change": 5.0, "turnover": 8e8, "zlje": 1e8, "zljzb": 12,
        "cddje": 5000e4, "cddjzb": 5, "volumeRatio": 1.4, "turnoverRate": 8, "rank": 1,
    })


def test_compute_and_upsert_for_slot_persists_slot_doc():
    fake_db = FakeMongoDb()
    _seed_slot(fake_db)
    result = compute_and_upsert_for_slot(
        fake_db, dataset_id="d1", snapshot_type="half_hour",
        trading_date="2026-06-05", slot_time="10:30")
    assert result["written"] is True
    docs = fake_db["hotlist_sentiment"].rows
    assert len(docs) == 1
    assert docs[0]["_id"] == "d1:half_hour:2026-06-05:10:30"
    assert docs[0]["slotTime"] == "10:30"
    assert "stage" in docs[0] and "metrics" in docs[0]


def test_compute_and_upsert_for_slot_missing_frame_reports_reason():
    fake_db = FakeMongoDb()
    result = compute_and_upsert_for_slot(
        fake_db, dataset_id="d1", snapshot_type="half_hour",
        trading_date="2026-06-05", slot_time="10:30")
    assert result["written"] is False and result["reason"]


def test_compute_and_upsert_for_slot_idempotent():
    fake_db = FakeMongoDb()
    _seed_slot(fake_db)
    compute_and_upsert_for_slot(fake_db, dataset_id="d1", snapshot_type="half_hour",
                                trading_date="2026-06-05", slot_time="10:30")
    compute_and_upsert_for_slot(fake_db, dataset_id="d1", snapshot_type="half_hour",
                                trading_date="2026-06-05", slot_time="10:30")
    assert len(fake_db["hotlist_sentiment"].rows) == 1  # replace_one 幂等


# ---------------------------------------------------------------------------
# 2026-09-24 阶段多帧确认（spec §5.1/§8.1.5）：因果边界——计算槽位 T 只消费
# slotTime < T 的截面；数据库中已存在的未来槽不得提前确认。期望值写死，
# 不调用被测 confirm_stage 生成（测试独立性）。
# ---------------------------------------------------------------------------


def _sentiment_stage_payload(stage: str) -> dict[str, Any]:
    return {
        "stage": stage, "riskLevel": "中", "confidence": 60, "summary": f"{stage}截面摘要",
        "metrics": {"topN": 0, "layers": {"all": {"total": 0, "topN": 0,
            "upRatio": 0, "downRatio": 0, "hotTrin": None, "stageCounts": {}, "stageShares": {},
            "nearLimitUpCount": 0, "highGainCount": 0, "highTurnoverCount": 0,
            "riskShare": 0, "activeOpportunityShare": 0, "strongMoneyShare": 0, "crowdedShare": 0}},
            "comparison": {"top100RetainRateFromYesterday": None,
                "top100RetainRateFromDayBefore": None},
            "limitEvidence": {"intersection": {"top100LimitUpShare": 0}},
            "transitionCounts": {}},
        "turnover": {"newEntries": [], "eliminated": []},
        "signals": [], "warnings": [], "statusSourceCounts": {"displayStatus": 0, "fallback": 0},
        "missingEvidence": [],
    }


def _patch_emotion_score(monkeypatch, score_by_slot: dict[str, float] | float) -> None:
    """路线 B 后本帧截面档位=评分映射（级联仅 legacyCascadeStage 对照）——因果截断/
    写序无关测试改以固定评分控制截面档位（T2 合同变更）。"""
    def _fake(evidence, slope=None):
        slot = str(evidence.get("slotTime") or "")
        score = score_by_slot.get(slot) if isinstance(score_by_slot, dict) else score_by_slot
        return {"score": score, "dims": {}, "skippedDims": [], "stageCandidate": None}

    monkeypatch.setattr("backend.analysis.hotlist.emotion_score.compute_emotion_score", _fake)


def test_future_slot_does_not_confirm_current_slot(monkeypatch):
    import backend.operations.hotlist_sentiment as ops_mod

    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        {"datasetId": "dragonboard_live", "snapshotId": "f1000", "type": "half_hour",
         "tradingDate": "2026-06-05", "slotTime": "10:00", "timestamp": 2},
    ]
    db["snapshot_stock_rows"].rows = [
        {"datasetId": "dragonboard_live", "snapshotId": "f1000", "code": "000001",
         "rank": 1, "change": 5, "zlje": 0, "volumeRatio": 1.5},
    ]
    # 库中已存在：过去槽 09:30=退潮（rawStage），以及未来槽 11:00=高潮
    db["hotlist_sentiment"].rows = [
        {"_id": "dragonboard_live:half_hour:2026-06-05:09:30", "datasetId": "dragonboard_live",
         "snapshotType": "half_hour", "tradingDate": "2026-06-05", "slotTime": "09:30",
         "rawStage": "退潮", "stage": "退潮"},
        {"_id": "dragonboard_live:half_hour:2026-06-05:11:00", "datasetId": "dragonboard_live",
         "snapshotType": "half_hour", "tradingDate": "2026-06-05", "slotTime": "11:00",
         "rawStage": "高潮", "stage": "高潮"},
    ]
    monkeypatch.setattr(ops_mod, "compute_hotlist_sentiment",
                        lambda *args, **kwargs: _sentiment_stage_payload("高潮"))
    _patch_emotion_score(monkeypatch, 80.0)  # map_stage(80) = 高潮

    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live", snapshot_type="half_hour",
                                         trading_date="2026-06-05", slot_time="10:00")
    assert result["written"] is True

    doc = db["hotlist_sentiment"].find_one({"_id": "dragonboard_live:half_hour:2026-06-05:10:00"})
    assert doc is not None
    # 期望值写死：09:30 退潮 + 本次高潮 → 候选未达标（阈值 2）→ 保持退潮 pending；
    # 未来 11:00 的"第二次高潮"不得进入序列，否则会被提前确认
    assert doc["rawStage"] == "高潮"
    assert doc["stage"] == "退潮"
    assert doc["stageConfirmState"]["pending"] is True
    assert doc["stageConfirmState"]["pendingSince"] == "10:00"


def test_slot_write_roundtrip_preserves_emotion_score_and_legacy_fields(monkeypatch):
    """T3 写口往返：compute_and_upsert_for_slot 产出的 emotionScore/legacyCascadeStage
    必须随文档落库且读回保留（评分可分解审计与对照面合同）。"""
    import backend.operations.hotlist_sentiment as ops_mod

    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        {"datasetId": "dragonboard_live", "snapshotId": "f1000", "type": "half_hour",
         "tradingDate": "2026-06-05", "slotTime": "10:00", "timestamp": 2},
    ]
    db["snapshot_stock_rows"].rows = [
        {"datasetId": "dragonboard_live", "snapshotId": "f1000", "code": "000001",
         "rank": 1, "change": 5, "zlje": 0, "volumeRatio": 1.5},
    ]
    monkeypatch.setattr(ops_mod, "compute_hotlist_sentiment",
                        lambda *args, **kwargs: _sentiment_stage_payload("高潮"))

    dims = {"upRatio": {"raw": 0.9, "sub": 96.0}}
    skipped = ["amountVsSame"]

    def _fake_emotion(evidence, slope=None):
        return {"score": 80.0, "dims": dims, "skippedDims": skipped, "stageCandidate": None}

    monkeypatch.setattr("backend.analysis.hotlist.emotion_score.compute_emotion_score", _fake_emotion)

    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live", snapshot_type="half_hour",
                                         trading_date="2026-06-05", slot_time="10:00")
    assert result["written"] is True

    doc = db["hotlist_sentiment"].find_one({"_id": "dragonboard_live:half_hour:2026-06-05:10:00"})
    assert doc is not None
    emotion = doc["emotionScore"]
    assert emotion["score"] == 80.0 and emotion["dims"] == dims and emotion["skippedDims"] == skipped
    assert emotion["stageCandidate"] == doc["rawStage"] == "高潮"  # S10 同值
    assert emotion["slope"] is None and emotion["version"] == "score-v1"
    assert doc["legacyCascadeStage"] == "高潮"  # 级联截面对照面随文档落库


def test_slot_wiring_feeds_real_evidence_into_score(monkeypatch):
    """T3 接线断言（review T3-S3）：analysis_by_code 与昨日同期总额真实进入评分链——
    真评分下 amountVsSame/riskRowsPct/yhPositive 可算（不再 skip），证明 evidence parts
    不是摆设；spy 捕获 collect_slot_evidence 的入参核对传递值。"""
    import backend.analysis.hotlist.jev_state as jev_state
    import backend.operations.hotlist_sentiment as ops_mod

    db = FakeMongoDb()
    db["snapshot_frames"].rows = [
        # 昨日 10:00 帧：两市总额（同期量能基线）+ 昨日涨停行（承接证据）
        {"datasetId": "dragonboard_live", "snapshotId": "f0900", "type": "half_hour",
         "tradingDate": "2026-06-04", "slotTime": "10:00", "timestamp": 1,
         "indices": {"totalAmount": {"amount": 1.0e12}}},
        # 当日 10:00 帧：两市总额
        {"datasetId": "dragonboard_live", "snapshotId": "f1000", "type": "half_hour",
         "tradingDate": "2026-06-05", "slotTime": "10:00", "timestamp": 2,
         "indices": {"totalAmount": {"amount": 1.2e12}}},
    ]
    db["snapshot_stock_rows"].rows = [
        {"datasetId": "dragonboard_live", "snapshotId": "f0900", "code": "000001",
         "rank": 1, "change": 10.0, "price": 9.0, "limitUpPrice": 9.0},
        {"datasetId": "dragonboard_live", "snapshotId": "f1000", "code": "000001",
         "rank": 1, "change": 5, "zlje": 0, "volumeRatio": 1.5},
    ]
    db["snapshot_analysis"].rows = [
        {"datasetId": "dragonboard_live", "snapshotId": "f1000", "code": "000001",
         "analysis": {"displayStatus": {"stage": "ignition"}, "cycle": {"stage": "ignition"}}},
    ]
    monkeypatch.setattr(ops_mod, "compute_hotlist_sentiment",
                        lambda *args, **kwargs: _sentiment_stage_payload("高潮"))

    captured: dict[str, Any] = {}
    real_collect = jev_state.collect_slot_evidence

    def _spy_collect(**kwargs):
        captured.update(kwargs)
        return real_collect(**kwargs)

    monkeypatch.setattr(jev_state, "collect_slot_evidence", _spy_collect)

    result = compute_and_upsert_for_slot(db, dataset_id="dragonboard_live", snapshot_type="half_hour",
                                         trading_date="2026-06-05", slot_time="10:00")
    assert result["written"] is True
    # spy：analysis_by_code 与昨日同期总额真实传入（接线断言核心）
    # spy：analysis_by_code 与昨日同期总额真实传入（接线断言核心；参数=昨日同期基线，
    # 当日累计在 frame.indices.totalAmount 内由 collect_slot_evidence 自读）
    assert "000001" in (captured.get("analysis_by_code") or {})
    assert captured.get("yesterday_same_slot_total_amount") == 1.0e12
    assert captured.get("yesterday_rows")
    # 真评分：三维不再 skip（若接线断开，amountVsSame/lifecycle/riskRowsPct 会全部缺失降级）
    doc = db["hotlist_sentiment"].find_one({"_id": "dragonboard_live:half_hour:2026-06-05:10:00"})
    assert doc is not None
    skipped = doc["emotionScore"]["skippedDims"]
    assert "amountVsSame" not in skipped
    assert "riskRowsPct" not in skipped
    assert doc["emotionScore"]["dims"]["amountVsSame"]["raw"] == 20.0  # (1.2e12/1.0e12-1)*100


def test_write_order_does_not_change_per_slot_results(monkeypatch):
    """顺序写入与乱序回填：逐槽 (slotTime, stage, rawStage) 必须完全一致（spec §8.1.5）。"""
    import backend.operations.hotlist_sentiment as ops_mod

    def build_db() -> tuple[FakeMongoDb, list[dict[str, Any]]]:
        db = FakeMongoDb()
        db["snapshot_frames"].rows = [
            {"datasetId": "dragonboard_live", "snapshotId": f"f{slot.replace(':', '')}", "type": "half_hour",
             "tradingDate": "2026-06-05", "slotTime": slot, "timestamp": index + 1}
            for index, slot in enumerate(["09:30", "10:00", "10:30"])
        ]
        db["snapshot_stock_rows"].rows = [
            {"datasetId": "dragonboard_live", "snapshotId": f"f{slot.replace(':', '')}", "code": "000001",
             "rank": 1, "change": 5, "zlje": 0, "volumeRatio": 1.5}
            for slot in ["09:30", "10:00", "10:30"]
        ]
        return db

    stages_by_slot = {"09:30": "退潮", "10:00": "高潮", "10:30": "高潮"}
    # 评分域档位序列：25 分（首槽无斜率 → 冰点）/ 80 分（slope>0 → 高潮）/ 80 分（高潮）
    _patch_emotion_score(monkeypatch, {"09:30": 25.0, "10:00": 80.0, "10:30": 80.0})

    # 顺序写入：逐槽 mock 对应截面
    ordered_db = build_db()
    for slot in ["09:30", "10:00", "10:30"]:
        monkeypatch.setattr(ops_mod, "compute_hotlist_sentiment",
                            lambda *args, _s=stages_by_slot[slot], **kwargs: _sentiment_stage_payload(_s))
        result = compute_and_upsert_for_slot(ordered_db, dataset_id="dragonboard_live", snapshot_type="half_hour",
                                             trading_date="2026-06-05", slot_time=slot)
        assert result["written"] is True
    ordered_docs = [ordered_db["hotlist_sentiment"].find_one({"_id": f"dragonboard_live:half_hour:2026-06-05:{slot}"})
                    for slot in ["09:30", "10:00", "10:30"]]

    # 乱序回填：库中先只有 10:30 文档，再按槽升序重算三槽（因果截断保证未来槽不参与）
    out_of_order_db = build_db()
    out_of_order_db["hotlist_sentiment"].rows = [
        {"_id": "dragonboard_live:half_hour:2026-06-05:10:30", "datasetId": "dragonboard_live",
         "snapshotType": "half_hour", "tradingDate": "2026-06-05", "slotTime": "10:30",
         "rawStage": "高潮", "stage": "高潮"},
    ]
    for slot in ["09:30", "10:00", "10:30"]:
        monkeypatch.setattr(ops_mod, "compute_hotlist_sentiment",
                            lambda *args, _s=stages_by_slot[slot], **kwargs: _sentiment_stage_payload(_s))
        result = compute_and_upsert_for_slot(out_of_order_db, dataset_id="dragonboard_live",
                                             snapshot_type="half_hour", trading_date="2026-06-05", slot_time=slot)
        assert result["written"] is True
    out_of_order_docs = [out_of_order_db["hotlist_sentiment"].find_one({"_id": f"dragonboard_live:half_hour:2026-06-05:{slot}"})
                         for slot in ["09:30", "10:00", "10:30"]]

    assert [(d["slotTime"], d["stage"], d["rawStage"]) for d in ordered_docs if d] == [
        (d["slotTime"], d["stage"], d["rawStage"]) for d in out_of_order_docs if d
    ]
    # 期望值写死（评分域：25 分首槽无斜率=冰点）→ 确认冰点 → pending 高潮（候选第一槽）→ 确认高潮
    assert [(d["slotTime"], d["stage"], d["rawStage"]) for d in ordered_docs if d] == [
        ("09:30", "冰点", "冰点"), ("10:00", "冰点", "高潮"), ("10:30", "高潮", "高潮"),
    ]
