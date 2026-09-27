"""ThemeTrend v12 升级 Task1：theme_daily_factors 落库链路测试。

覆盖：
  - factors_daily.build_daily_factor_rows 纯函数已知答案（手算分位数）；
  - ThemeDailyFactorRepository upsert/查询；
  - compute_and_store_daily_factors 服务编排（收盘槽取数、自动补算、
    fail-visible：全源无数据不写、缺历史不伪造分位）。
口径来源：设计 §5.1 D1（60 日分位数起步）+ Phase 2 runner 固化语义
（零覆盖题材当日不入序列、一股多题材重复计入白名单口径）。
"""

from __future__ import annotations

from typing import Any

import pytest

from backend.analysis.theme.factors_daily import FACTOR_VERSION, build_daily_factor_rows
from backend.data.repositories.theme_daily_factor_repository import ThemeDailyFactorRepository
from backend.services.theme.daily_factors_service import compute_and_store_daily_factors


class FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = list(rows)

    def sort(self, spec: list[tuple[str, int]]) -> "FakeCursor":
        for key, direction in reversed(spec):
            self.rows.sort(key=lambda row: (row.get(key) is None, row.get(key)), reverse=direction < 0)
        return self

    def __iter__(self):
        return iter(self.rows)


def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = row.get(key)
        if isinstance(expected, dict):
            if "$gte" in expected and not (actual is not None and actual >= expected["$gte"]):
                return False
            if "$lte" in expected and not (actual is not None and actual <= expected["$lte"]):
                return False
            if "$in" in expected and actual not in expected["$in"]:
                return False
        elif actual != expected:
            return False
    return True


class FakeCollection:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.index_specs: list[Any] = []

    def create_index(self, spec: Any, **kwargs: Any) -> None:
        self.index_specs.append(spec)

    def find(self, query: dict[str, Any] | None = None, projection: dict[str, Any] | None = None) -> FakeCursor:
        return FakeCursor([row for row in self.rows if _matches(row, query or {})])

    def find_one(self, query: dict[str, Any] | None = None, sort: list[tuple[str, int]] | None = None) -> dict[str, Any] | None:
        cursor = self.find(query or {})
        if sort:
            cursor = cursor.sort(sort)
        return next(iter(cursor), None)

    def replace_one(self, query: dict[str, Any], doc: dict[str, Any], upsert: bool = False) -> None:
        for index, row in enumerate(self.rows):
            if _matches(row, query):
                self.rows[index] = doc
                return
        if upsert:
            self.rows.append(doc)


class FakeDb:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def __getitem__(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection())

    def collection(self, name: str) -> FakeCollection:
        return self._collections.setdefault(name, FakeCollection())


DAYS = ["2026-09-01", "2026-09-02", "2026-09-03", "2026-09-04"]
AMOUNTS_A = [30.0, 10.0, 20.0, 10.0]
AMOUNTS_B = [70.0, 90.0, 80.0, 90.0]
TURNOVERS_B = [None, 6.0, 6.0, 6.0]


def make_stock_daily() -> dict[str, dict[str, dict[str, float | None]]]:
    out: dict[str, dict[str, dict[str, float | None]]] = {}
    for index, day in enumerate(DAYS):
        out[day] = {
            "amount": {"A": AMOUNTS_A[index], "B": AMOUNTS_B[index]},
            "turnover": {"A": 5.0, "B": TURNOVERS_B[index]},
        }
    return out


MEMBERS = {"T1": {"A"}, "T2": {"B"}, "T3": {"Z"}}


class TestBuildDailyFactorRows:
    def test_known_answer_percentile_and_combine(self) -> None:
        rows, flags = build_daily_factor_rows(
            make_stock_daily(),
            MEMBERS,
            target_dates=["2026-09-03", "2026-09-04"],
            theme_names={"T1": "题材一", "T2": "题材二"},
            window=60,  # 设计 §5.1：60 日分位数起步（Phase 0 裁决）
            min_periods=3,
        )
        # 零覆盖题材 T3 不产出行（当日不可观测不入序列），按 target 日计数
        assert len(rows) == 4
        assert "zero_coverage_theme_days:2" in flags
        by_key = {(row["tradingDate"], row["themeId"]): row for row in rows}

        t1_d3 = by_key[("2026-09-03", "T1")]
        assert t1_d3["themeName"] == "题材一"
        assert t1_d3["factorVersion"] == FACTOR_VERSION
        factors = t1_d3["factors"]
        # 手算：T1 amountShare 序列 [0.3, 0.1, 0.2, 0.1]，d3 cur=0.2 le=2/3
        assert round(factors["amountShare"], 6) == 0.2
        assert round(factors["amountSharePct"], 4) == round(2 / 3 * 100, 4)
        # T1 turnoverMean 恒 5.0，d3 分位 = 100（全并列 <= 口径）
        assert factors["turnoverMean"] == 5.0
        assert factors["turnoverMeanPct"] == 100.0
        # BC 等权合成（双侧都有）
        assert round(factors["crowdingPercentile"], 4) == round((2 / 3 * 100 + 100.0) / 2, 4)
        assert t1_d3["qualityFlags"] == []

        t1_d4 = by_key[("2026-09-04", "T1")]
        # d4: hist=[0.3,0.1,0.2,0.1] cur=0.1 → le=2/4=50（0.2/0.3 均大于 cur）
        assert round(t1_d4["factors"]["amountSharePct"], 4) == 50.0
        assert round(t1_d4["factors"]["crowdingPercentile"], 4) == round((50.0 + 100.0) / 2, 4)

        t2_d3 = by_key[("2026-09-03", "T2")]
        # T2 amountShare [0.7, 0.9, 0.8, 0.9]：d3 cur=0.8 le=2/3
        assert round(t2_d3["factors"]["amountSharePct"], 4) == round(2 / 3 * 100, 4)
        # T2 turnover 序列 d2 起才有观测：d3 仅 2 个观测 < min_periods → None；
        # BC 单侧缺失取另一侧 = amountSharePct
        assert t2_d3["factors"]["turnoverMean"] == 6.0
        assert t2_d3["factors"]["turnoverMeanPct"] is None
        assert round(t2_d3["factors"]["crowdingPercentile"], 4) == round(2 / 3 * 100, 4)
        assert t2_d3["qualityFlags"] == []

        t2_d4 = by_key[("2026-09-04", "T2")]
        assert t2_d4["factors"]["amountSharePct"] == 100.0
        assert t2_d4["factors"]["crowdingPercentile"] == 100.0

    def test_min_periods_insufficient_marks_not_fabricates(self) -> None:
        rows, flags = build_daily_factor_rows(
            make_stock_daily(), MEMBERS, target_dates=list(DAYS), min_periods=3,
        )
        by_key = {(row["tradingDate"], row["themeId"]): row for row in rows}
        # d1/d2 观测数 < min_periods → 分位 None + 显式标记，不伪造中性值
        for day in ("2026-09-01", "2026-09-02"):
            for tid in ("T1", "T2"):
                row = by_key[(day, tid)]
                assert row["factors"]["amountSharePct"] is None
                assert row["factors"]["crowdingPercentile"] is None
                assert "insufficient_history" in row["qualityFlags"]
        assert "insufficient_history_rows:4" in flags

    def test_turnover_unobservable_single_side_combine(self) -> None:
        rows, _ = build_daily_factor_rows(
            make_stock_daily(), MEMBERS, target_dates=["2026-09-01"], min_periods=3,
        )
        t2_d1 = next(row for row in rows if row["themeId"] == "T2")
        # B 当日无换手观测：原料 None + 标记；分位双侧缺 → None（不伪造）
        assert t2_d1["factors"]["turnoverMean"] is None
        assert "turnover_unobservable" in t2_d1["qualityFlags"]

    def test_zero_pool_total_day_not_observable(self) -> None:
        """当日 amount 全零（pool_total<=0）：theme_amount_share 返回 {}，
        装配层不得 KeyError，该日 amount 不可观测（真实数据冒烟暴露的边界）。"""
        stock_daily = {
            "2026-09-01": {"amount": {"A": 0.0, "B": 0.0}, "turnover": {"A": 5.0, "B": 6.0}},
            "2026-09-02": {"amount": {"A": 30.0, "B": 70.0}, "turnover": {"A": 5.0, "B": 6.0}},
        }
        rows, flags = build_daily_factor_rows(
            stock_daily, {"T1": {"A"}, "T2": {"B"}}, target_dates=list(stock_daily), min_periods=1,
        )
        # d1 无 amount 份额行（换手仍可观测）；d2 正常产出
        d1 = {(row["themeId"]): row for row in rows if row["tradingDate"] == "2026-09-01"}
        assert "amount_unobservable" in d1["T1"]["qualityFlags"]
        assert d1["T1"]["factors"]["amountShare"] is None
        assert d1["T1"]["factors"]["turnoverMean"] == 5.0
        d2 = {(row["themeId"]): row for row in rows if row["tradingDate"] == "2026-09-02"}
        assert d2["T1"]["factors"]["amountShare"] == 0.3

    def test_zero_coverage_theme_excluded_and_counted(self) -> None:
        rows, flags = build_daily_factor_rows(
            make_stock_daily(), MEMBERS, target_dates=list(DAYS), min_periods=3,
        )
        assert all(row["themeId"] != "T3" for row in rows)
        assert "zero_coverage_theme_days:4" in flags

    def test_missing_target_date_flagged(self) -> None:
        rows, flags = build_daily_factor_rows(
            make_stock_daily(), MEMBERS, target_dates=["2026-09-03", "2026-09-99"], min_periods=3,
        )
        assert {row["tradingDate"] for row in rows} == {"2026-09-03"}
        assert "target_date_missing:2026-09-99" in flags

    def test_empty_source_reports_no_data(self) -> None:
        rows, flags = build_daily_factor_rows({}, MEMBERS, target_dates=["2026-09-03"])
        assert rows == []
        assert flags == ["no_stock_rows"]


class TestThemeDailyFactorRepository:
    def test_upsert_day_replaces_not_duplicates(self) -> None:
        db = FakeDb()
        repo = ThemeDailyFactorRepository(db)
        row = {"themeId": "T1", "themeName": "题材一", "factors": {"amountShare": 0.2}, "qualityFlags": []}
        assert repo.upsert_day("dsx", "2026-09-03", [row]) == 1
        stored = db.collection("theme_daily_factors").rows
        assert len(stored) == 1
        assert stored[0]["datasetId"] == "dsx"
        assert stored[0]["tradingDate"] == "2026-09-03"
        # 同键重写覆盖（幂等）
        repo.upsert_day("dsx", "2026-09-03", [{**row, "factors": {"amountShare": 0.3}}])
        stored = db.collection("theme_daily_factors").rows
        assert len(stored) == 1
        assert stored[0]["factors"]["amountShare"] == 0.3

    def test_computed_dates_latest_date_and_range(self) -> None:
        db = FakeDb()
        repo = ThemeDailyFactorRepository(db)
        base = {"themeName": "", "factors": {}, "qualityFlags": []}
        repo.upsert_day("dsx", "2026-09-03", [{**base, "themeId": "T1"}])
        repo.upsert_day("dsx", "2026-09-04", [{**base, "themeId": "T1"}])
        repo.upsert_day("other", "2026-09-05", [{**base, "themeId": "T1"}])
        assert repo.computed_dates("dsx", "2026-09-01", "2026-09-30") == ["2026-09-03", "2026-09-04"]
        assert repo.latest_date("dsx") == "2026-09-04"
        rows = repo.list_range("dsx", "2026-09-03", "2026-09-04")
        assert [(row["tradingDate"], row["themeId"]) for row in rows] == [
            ("2026-09-03", "T1"),
            ("2026-09-04", "T1"),
        ]


def _seed_stock_rows(db: FakeDb) -> None:
    coll = db.collection("snapshot_stock_rows")
    for index, day in enumerate(DAYS):
        # 09:30 首槽诱饵行：收盘槽选择后不得进入口径
        coll.rows.append({
            "datasetId": "dsx", "type": "daily", "tradingDate": day, "slotTime": "09:30",
            "code": "A", "amount": 999.0, "turnoverRate": 9.9,
        })
        coll.rows.append({
            "datasetId": "dsx", "type": "daily", "tradingDate": day, "slotTime": "15:30",
            "code": "A", "amount": AMOUNTS_A[index], "turnoverRate": 5.0,
        })
        coll.rows.append({
            "datasetId": "dsx", "type": "daily", "tradingDate": day, "slotTime": "15:30",
            "code": "B", "amount": AMOUNTS_B[index],
            "turnoverRate": TURNOVERS_B[index],
        })


def _seed_mappings(db: FakeDb) -> None:
    db.collection("theme_stock_mappings").rows.extend([
        {"themeId": "T1", "stockCode": "A"},
        {"themeId": "T2", "stockCode": "B"},
        {"themeId": "T3", "stockCode": "Z"},
    ])
    db.collection("themes").rows.extend([
        {"id": "T1", "name": "题材一"},
        {"id": "T2", "name": "题材二"},
    ])


class TestComputeAndStoreDailyFactors:
    def test_explicit_targets_write_docs_with_close_slot_only(self) -> None:
        db = FakeDb()
        _seed_stock_rows(db)
        _seed_mappings(db)
        result = compute_and_store_daily_factors(
            db,
            dataset_id="dsx",
            target_dates=["2026-09-03", "2026-09-04"],
            min_periods=3,
            write_redis_cache=False,
            today="2026-09-27",
        )
        assert result["status"] == "ok"
        assert result["computedDates"] == ["2026-09-03", "2026-09-04"]
        stored = db.collection("theme_daily_factors").rows
        assert len(stored) == 4
        t1_d3 = next(row for row in stored if row["tradingDate"] == "2026-09-03" and row["themeId"] == "T1")
        # 09:30 诱饵（amount=999）未进分母 → share = 20/100
        assert round(t1_d3["factors"]["amountShare"], 6) == 0.2
        assert t1_d3["themeName"] == "题材一"

    def test_auto_mode_catches_up_missing_dates_only(self) -> None:
        db = FakeDb()
        _seed_stock_rows(db)
        _seed_mappings(db)
        ThemeDailyFactorRepository(db).upsert_day(
            "dsx", "2026-09-01",
            [{"themeId": "T1", "themeName": "", "factors": {}, "qualityFlags": []}],
        )
        result = compute_and_store_daily_factors(
            db, dataset_id="dsx", min_periods=3, write_redis_cache=False, today="2026-09-27",
        )
        assert result["status"] == "ok"
        assert result["computedDates"] == ["2026-09-02", "2026-09-03", "2026-09-04"]
        assert result["skippedExistingDates"] == ["2026-09-01"]

    def test_auto_mode_up_to_date_is_noop(self) -> None:
        db = FakeDb()
        _seed_stock_rows(db)
        _seed_mappings(db)
        compute_and_store_daily_factors(db, dataset_id="dsx", min_periods=3, write_redis_cache=False, today="2026-09-27")
        before = len(db.collection("theme_daily_factors").rows)
        result = compute_and_store_daily_factors(db, dataset_id="dsx", min_periods=3, write_redis_cache=False, today="2026-09-27")
        assert result["status"] == "up_to_date"
        assert result["computedDates"] == []
        assert len(db.collection("theme_daily_factors").rows) == before

    def test_no_source_data_writes_nothing(self) -> None:
        db = FakeDb()
        _seed_mappings(db)
        result = compute_and_store_daily_factors(
            db, dataset_id="dsx", target_dates=["2026-09-03"],
            min_periods=3, write_redis_cache=False, today="2026-09-27",
        )
        assert result["status"] == "no_source_data"
        assert result["ok"] is False
        assert db.collection("theme_daily_factors").rows == []

    def test_missing_stock_fields_counted(self) -> None:
        db = FakeDb()
        _seed_stock_rows(db)
        _seed_mappings(db)
        db.collection("snapshot_stock_rows").rows.append({
            "datasetId": "dsx", "type": "daily", "tradingDate": "2026-09-03",
            "slotTime": "15:30", "code": "C", "amount": None, "turnoverRate": None,
        })
        result = compute_and_store_daily_factors(
            db, dataset_id="dsx", target_dates=["2026-09-03"],
            min_periods=3, write_redis_cache=False, today="2026-09-27",
        )
        assert result["stockRowMissing"]["amount"] >= 1
        assert result["stockRowMissing"]["turnoverRate"] >= 1
