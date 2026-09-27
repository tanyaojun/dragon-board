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

from backend.analysis.theme.daily_series import ThemeDailySeries
from backend.analysis.theme.factors_daily import (
    FACTOR_VERSION,
    build_daily_factor_rows,
    build_heat_level_streak_values,
    build_momentum_v2_daily_values,
    merge_heat_level_streak_into_rows,
    merge_momentum_v2_into_rows,
)
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


def _resolve_path(row: dict[str, Any], key: str) -> Any:
    """点路径取值（factors.momentumV2 等），缺失返回 None。"""
    value: Any = row
    for part in key.split("."):
        if isinstance(value, dict) and part in value:
            value = value[part]
        else:
            return None
    return value


def _matches(row: dict[str, Any], query: dict[str, Any]) -> bool:
    for key, expected in query.items():
        actual = _resolve_path(row, key)
        if isinstance(expected, dict):
            if "$exists" in expected and (actual is not None) != bool(expected["$exists"]):
                return False
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
        assert "target_date_no_stock_rows:2026-09-99" in flags

    def test_empty_source_reports_no_data(self) -> None:
        rows, flags = build_daily_factor_rows({}, MEMBERS, target_dates=["2026-09-03"])
        assert rows == []
        assert flags == ["no_stock_rows"]


def make_series(theme_id: str, n_days: int, base_change: float = 1.0) -> ThemeDailySeries:
    """构造 n_days 天的合成日线序列（日期递增、恒定涨幅）。"""
    from datetime import date, timedelta

    dates = [(date(2026, 6, 1) + timedelta(days=i)).isoformat() for i in range(n_days)]
    slots = [
        {"tradingDate": d, "slotTime": "15:30", "change": base_change, "ztCount": 2, "mainNetInflow": 100.0}
        for d in dates
    ]
    return ThemeDailySeries(
        theme_id=theme_id,
        theme_name=f"名称{theme_id}",
        dates=dates,
        changes=[base_change] * n_days,
        zt_counts=[2] * n_days,
        breadths=[60.0] * n_days,
        inflows=[100.0] * n_days,
        amount_ratios=[0.0] * n_days,
        crowding_days=[30.0] * n_days,
        quality_flags=[],
        latest_slots=slots,
        _day_flags=[[] for _ in dates],
    )


class TestBuildMomentumV2DailyValues:
    def test_full_history_produces_score(self) -> None:
        series = make_series("T1", 25)
        values, flags = build_momentum_v2_daily_values(
            {"T1": series}, target_dates=[series.dates[-1]],
        )
        day_values = values[series.dates[-1]]
        v2 = day_values["T1"]
        assert isinstance(v2["score"], float)
        for key in ("direction", "rps", "nearHigh", "windowMomentum", "breadth", "flowVolume", "crowdingPenalty", "qualityFlags"):
            assert key in v2

    def test_truncation_early_dates_per_dim_insufficient(self) -> None:
        """截断语义：早期目标日只用 ≤D 数据——3 天截断下 rps d5/d10/d20 不足为 None，
        其余可用维度照常产分（逐维度 fail-visible，不整票伪造）。"""
        series = make_series("T1", 25)
        early = series.dates[2]
        values, _ = build_momentum_v2_daily_values({"T1": series}, target_dates=[early])
        v2 = values[early]["T1"]
        assert v2["rps"]["d5"] is None
        assert "rps_d5_history_insufficient" in v2["qualityFlags"]
        assert isinstance(v2["score"], float)

    def test_target_date_beyond_series_absent(self) -> None:
        series = make_series("T1", 5)
        values, _ = build_momentum_v2_daily_values({"T1": series}, target_dates=["2027-01-01"])
        assert values == {}

    def test_empty_series_reported(self) -> None:
        values, flags = build_momentum_v2_daily_values({}, target_dates=["2026-09-01"])
        assert values == {}
        assert flags == ["momentum_v2_no_series"]


class TestMergeMomentumV2IntoRows:
    def test_merge_into_existing_and_create_v2_only_row(self) -> None:
        rows, _ = build_daily_factor_rows(
            make_stock_daily(), {"T1": {"A"}}, target_dates=["2026-09-03"], min_periods=3,
        )
        v2_t1 = {"score": 62.0, "direction": "up", "qualityFlags": []}
        v2_t2 = {"score": None, "direction": "neutral", "qualityFlags": ["insufficient_factors"]}
        merged, flags = merge_momentum_v2_into_rows(
            rows, {"2026-09-03": {"T1": v2_t1, "T2": v2_t2}}, theme_names={"T2": "题材二"},
        )
        by_key = {(row["tradingDate"], row["themeId"]): row for row in merged}
        # 既有拥挤行获得 momentumV2 子结构
        t1 = by_key[("2026-09-03", "T1")]
        assert t1["factors"]["momentumV2"]["score"] == 62.0
        assert t1["factors"]["amountShare"] is not None
        # v2-only 题材新建行：拥挤字段 None + 显式标记，不伪造
        t2 = by_key[("2026-09-03", "T2")]
        assert t2["factors"]["amountShare"] is None
        assert t2["factors"]["momentumV2"]["score"] is None
        assert "crowding_unobservable" in t2["qualityFlags"]
        assert "momentum_v2_insufficient" in t2["qualityFlags"]
        assert t2["themeName"] == "题材二"
        assert "momentum_v2_rows_created:1" in flags


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

    def test_momentum_v2_stored_from_daily_sector_rows(self) -> None:
        """v2 从 daily sector rows 构建序列落库；v2-only 题材产行（拥挤字段 None + 标记）。"""
        db = FakeDb()
        _seed_stock_rows(db)
        _seed_mappings(db)
        sector = db.collection("snapshot_sector_rows")
        for day in DAYS:
            for tid in ("T1", "T9"):
                sector.rows.append({
                    "datasetId": "dsx", "type": "daily", "entityType": "hot_theme",
                    "tradingDate": day, "slotTime": "15:30",
                    "themeId": tid, "entityKey": tid, "entityName": f"名称{tid}",
                    "change": 1.5, "ztCount": 3, "breadthScore": 55.0,
                    "mainNetInflow": 200.0, "crowdingRisk": 20.0, "metadata": {},
                })
        result = compute_and_store_daily_factors(
            db, dataset_id="dsx", target_dates=["2026-09-03"],
            min_periods=3, write_redis_cache=False, today="2026-09-27",
        )
        assert result["status"] == "ok"
        stored = db.collection("theme_daily_factors").rows
        by_tid = {row["themeId"]: row for row in stored if row["tradingDate"] == "2026-09-03"}
        # 4 天序列不足 d5/d10/d20 → v2 score=None + insufficient 标记（不伪造）
        assert by_tid["T1"]["factors"]["momentumV2"]["score"] is None
        assert "momentum_v2_insufficient" in by_tid["T1"]["qualityFlags"]
        assert by_tid["T1"]["factors"]["amountShare"] is not None
        # v2-only 题材 T9：不在 stock mappings → 拥挤字段 None + 显式标记
        assert by_tid["T9"]["factors"]["amountShare"] is None
        assert by_tid["T9"]["factors"]["momentumV2"]["score"] is None
        assert "crowding_unobservable" in by_tid["T9"]["qualityFlags"]

    def test_heat_level_streak_stored_from_entity_key_sector_rows(self) -> None:
        """生产形态回归（2026-09-27 补算实测）：daily sector rows 无 themeId 字段、
        题材标识走 entityKey（daily_series._theme_key 同口径 themeId or entityKey），
        heatLevel 序列 known-answer 落 factors.heatLevelStreak。"""
        db = FakeDb()
        _seed_stock_rows(db)
        _seed_mappings(db)
        sector = db.collection("snapshot_sector_rows")
        levels = {"2026-09-01": 100.0, "2026-09-02": 80.0, "2026-09-03": 50.0, "2026-09-04": 90.0}
        for day, level in levels.items():
            sector.rows.append({
                "datasetId": "dsx", "type": "daily", "entityType": "hot_theme",
                "tradingDate": day, "slotTime": "15:30",
                "entityKey": "T1", "entityName": "名称T1",  # 无 themeId 键（生产形态）
                "heatLevel": level, "heatScore": 395901, "metadata": {},
            })
        result = compute_and_store_daily_factors(
            db, dataset_id="dsx", target_dates=["2026-09-04"],
            min_periods=3, write_redis_cache=False, today="2026-09-27",
        )
        assert result["status"] == "ok"
        row = next(
            r for r in db.collection("theme_daily_factors").rows
            if r["tradingDate"] == "2026-09-04" and r["themeId"] == "T1"
        )
        # 100→80 连续 2 天，09-03 归 0，09-04 断链后首个达标 = 1
        assert row["factors"]["heatLevelStreak"] == 1

    def test_auto_mode_backfills_missing_v2_for_covered_dates(self) -> None:
        """自愈合同：已有拥挤行但序列覆盖内缺 momentumV2 的日期会被自动重算补齐。"""
        db = FakeDb()
        _seed_stock_rows(db)
        _seed_mappings(db)
        sector = db.collection("snapshot_sector_rows")
        for day in DAYS:
            sector.rows.append({
                "datasetId": "dsx", "type": "daily", "entityType": "hot_theme",
                "tradingDate": day, "slotTime": "15:30",
                "themeId": "T1", "entityKey": "T1", "entityName": "名称T1",
                "change": 1.5, "ztCount": 3, "breadthScore": 55.0,
                "mainNetInflow": 200.0, "crowdingRisk": 20.0, "metadata": {},
            })
        # 模拟 v2 接线前写入的旧行（09-01 只有拥挤面）
        ThemeDailyFactorRepository(db).upsert_day(
            "dsx", "2026-09-01",
            [{"themeId": "T1", "themeName": "题材一", "factors": {"amountShare": 0.2}, "qualityFlags": []}],
        )
        result = compute_and_store_daily_factors(
            db, dataset_id="dsx", min_periods=3, write_redis_cache=False, today="2026-09-27",
        )
        # 09-01 序列覆盖内缺 v2 → 重算；其余 3 天正常补算
        assert "2026-09-01" in result["computedDates"]
        row = next(
            r for r in db.collection("theme_daily_factors").rows
            if r["tradingDate"] == "2026-09-01" and r["themeId"] == "T1"
        )
        assert "momentumV2" in row["factors"]

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




class TestBuildHeatLevelStreakValues:
    def test_known_answer_accrue_reset_and_none_break(self) -> None:
        heat = {
            "T1": {"2026-09-01": 80.0, "2026-09-02": 72.0, "2026-09-03": 90.0, "2026-09-04": 50.0, "2026-09-05": 75.0},
            "T2": {"2026-09-01": 80.0, "2026-09-03": 85.0},
        }
        values, flags = build_heat_level_streak_values(heat, target_dates=sorted(heat["T1"]))
        assert values == {
            "2026-09-01": {"T1": 1, "T2": 1},
            "2026-09-02": {"T1": 2},
            "2026-09-03": {"T1": 3, "T2": 2},
            "2026-09-04": {"T1": 0},
            "2026-09-05": {"T1": 1},
        }
        assert flags == []

    def test_threshold_default_seventy_is_inclusive(self) -> None:
        heat = {"T1": {"2026-09-01": 70.0, "2026-09-02": 69.9}}
        values, _ = build_heat_level_streak_values(heat, target_dates=sorted(heat["T1"]))
        assert values == {"2026-09-01": {"T1": 1}, "2026-09-02": {"T1": 0}}

    def test_none_day_breaks_not_resumes(self) -> None:
        heat = {"T1": {"2026-09-01": 80.0, "2026-09-02": None, "2026-09-03": 85.0}}
        values, _ = build_heat_level_streak_values(heat, target_dates=sorted(heat["T1"]))
        assert values == {"2026-09-01": {"T1": 1}, "2026-09-02": {"T1": None}, "2026-09-03": {"T1": 1}}

    def test_custom_threshold(self) -> None:
        heat = {"T1": {"2026-09-01": 55.0, "2026-09-02": 60.0, "2026-09-03": 40.0}}
        values, _ = build_heat_level_streak_values(heat, target_dates=sorted(heat["T1"]), threshold=50.0)
        assert values == {"2026-09-01": {"T1": 1}, "2026-09-02": {"T1": 2}, "2026-09-03": {"T1": 0}}

    def test_empty_reported(self) -> None:
        values, flags = build_heat_level_streak_values({}, target_dates=["2026-09-01"])
        assert values == {}
        assert flags == []

    def test_target_date_outside_series_skipped(self) -> None:
        heat = {"T1": {"2026-09-01": 80.0}}
        values, _ = build_heat_level_streak_values(heat, target_dates=["2026-09-01", "2026-09-05"])
        assert values == {"2026-09-01": {"T1": 1}}
class TestMergeHeatLevelStreakIntoRows:
    def test_merge_into_existing_and_create_streak_only_row(self) -> None:
        rows, _ = build_daily_factor_rows(
            make_stock_daily(), {"T1": {"A"}}, target_dates=["2026-09-03"], min_periods=3,
        )
        streak = {"2026-09-03": {"T1": 3, "T2": 1}}
        merged, flags = merge_heat_level_streak_into_rows(
            streak, rows, theme_names={"T2": "题材二"},
        )
        by_key = {(row["tradingDate"], row["themeId"]): row for row in merged}
        t1 = by_key[("2026-09-03", "T1")]
        assert t1["factors"]["heatLevelStreak"] == 3
        assert t1["factors"]["amountShare"] is not None
        t2 = by_key[("2026-09-03", "T2")]
        assert t2["factors"]["amountShare"] is None
        assert t2["factors"]["heatLevelStreak"] == 1
        assert "crowding_unobservable" in t2["qualityFlags"]
        assert "heat_level_streak_rows_created:1" in flags
