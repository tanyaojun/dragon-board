from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DEFAULT_STRATEGY_NAME = "rank_trend_candidate"

STRATEGY_DEFINITIONS: list[dict[str, Any]] = [
    {
        "key": DEFAULT_STRATEGY_NAME,
        "label": "RankTrend 候选池",
        "description": "买入 A_MAIN 与连续确认后的 B_IGNITION，是当前正式策略。",
    },
    {
        "key": "hot_top10",
        "label": "热榜 Top10",
        "description": "只用热榜排名前 10 作为朴素对照组，不使用 RankTrend 分层。",
    },
    {
        "key": "a_main_only",
        "label": "A_MAIN only",
        "description": "只买 A_MAIN，衡量主升分层本身的交易贡献。",
    },
    {
        "key": "b_ignition_only",
        "label": "B_IGNITION only",
        "description": "只买连续确认后的 B_IGNITION，衡量点火分层的交易贡献。",
    },
    {
        "key": "a_b_combined",
        "label": "A+B",
        "description": "只买 A_MAIN 与连续确认后的 B_IGNITION，是当前正式策略的核心候选池对照。",
    },
]

SUPPORTED_STRATEGY_NAMES = {definition["key"] for definition in STRATEGY_DEFINITIONS}

CONTROL_STRATEGIES = [
    definition for definition in STRATEGY_DEFINITIONS if definition["key"] != DEFAULT_STRATEGY_NAME
]


def normalize_strategy_name(value: Any = None, default: str = DEFAULT_STRATEGY_NAME) -> str:
    strategy_name = str(value or default).strip()
    if not strategy_name:
        strategy_name = default
    if strategy_name not in SUPPORTED_STRATEGY_NAMES:
        supported = ", ".join(sorted(SUPPORTED_STRATEGY_NAMES))
        raise ValueError(f"unsupported strategyName: {strategy_name}. supported: {supported}")
    return strategy_name


# ═══════════════════════════════════════════
# Phase 3: 四层策略模型
# ═══════════════════════════════════════════

CANDIDATE_TIERS = ("A_MAIN", "B_IGNITION", "C_CROWDED", "D_EXIT_RISK", "N_NEUTRAL")


@dataclass
class StrategyInput:
    """单帧策略评估的输入上下文。"""
    frame: dict[str, Any]
    frame_signals: list[dict[str, Any]]
    previous_frame: dict[str, Any] | None = None
    signal_by_key: dict[str, dict[str, Any]] = field(default_factory=dict)
    positions: dict[str, Any] = field(default_factory=dict)
    strategy_key: str = DEFAULT_STRATEGY_NAME
    config: dict[str, Any] = field(default_factory=dict)
    theme_support_by_code: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def snapshot_id(self) -> str:
        return str(self.frame.get("snapshotId") or "")

    @property
    def timestamp(self) -> int:
        return int(self.frame.get("timestamp") or 0)

    @property
    def trading_date(self) -> str:
        return str(self.frame.get("tradingDate") or "")


@dataclass
class StrategyDecision:
    """单只股票经过四层流水线后的策略决策。"""
    code: str
    name: str
    candidate_tier: str
    signal: str  # "buy" / "sell" / "hold" / "watch"
    confidence: float = 0.0
    rank: int = 999
    stage: str = ""
    regime: str = ""
    reasons: list[str] = field(default_factory=list)
    risk_flags: list[str] = field(default_factory=list)
    quality_flags: list[str] = field(default_factory=list)
    main_theme: str = ""
    theme_heat: float = 0.0
    theme_contribution: float = 0.0
    theme_role: str = ""
    theme_support_score: float = 0.0
    theme_risk_flags: list[str] = field(default_factory=list)
    theme_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "candidateTier": self.candidate_tier,
            "signal": self.signal,
            "confidence": self.confidence,
            "rank": self.rank,
            "stage": self.stage,
            "regime": self.regime,
            "reasons": self.reasons,
            "riskFlags": self.risk_flags,
            "qualityFlags": self.quality_flags,
            "mainTheme": self.main_theme,
            "themeHeat": self.theme_heat,
            "themeContribution": self.theme_contribution,
            "themeRole": self.theme_role,
            "themeSupportScore": self.theme_support_score,
            "themeRiskFlags": self.theme_risk_flags,
            "themeReasons": self.theme_reasons,
        }


@dataclass
class FrameStrategyResult:
    """单帧策略评估的聚合输出。"""
    snapshot_id: str
    timestamp: int
    trading_date: str
    decisions: list[StrategyDecision] = field(default_factory=list)
    buy_candidates: list[StrategyDecision] = field(default_factory=list)
    watch_candidates: list[StrategyDecision] = field(default_factory=list)
    excluded_candidates: list[StrategyDecision] = field(default_factory=list)

    @property
    def strong_buy_count(self) -> int:
        return len(self.buy_candidates)

    @property
    def watch_count(self) -> int:
        return len(self.watch_candidates)

    @property
    def excluded_count(self) -> int:
        return len(self.excluded_candidates)

    def to_dict(self) -> dict[str, Any]:
        return {
            "snapshotId": self.snapshot_id,
            "timestamp": self.timestamp,
            "tradingDate": self.trading_date,
            "decisionCount": len(self.decisions),
            "buyCandidates": [d.to_dict() for d in self.buy_candidates],
            "watchCandidates": [d.to_dict() for d in self.watch_candidates],
            "excludedCandidates": [d.to_dict() for d in self.excluded_candidates],
        }


class BaseStrategy:
    """四层策略流水线基类。

    流水线：
    1. CandidateGeneration — 从信号中筛选候选
    2. CandidateTiering   — 按分层归类 (A_MAIN / B_IGNITION / C_CROWDED / D_EXIT_RISK / N_NEUTRAL)
    3. SignalGeneration    — 生成 buy / hold / sell / watch 信号
    4. RiskFiltering       — 涨跌停、T+1、流动性、市场环境过滤
    """

    key: str = ""
    label: str = ""
    description: str = ""

    def evaluate_frame(self, input: StrategyInput) -> FrameStrategyResult:
        """执行四层流水线，返回单帧策略结果。"""
        decisions = self._generate_candidates(input)
        self._tier_candidates(decisions, input)
        self._generate_signals(decisions, input)
        self._filter_risks(decisions, input)

        buy: list[StrategyDecision] = []
        watch: list[StrategyDecision] = []
        excluded: list[StrategyDecision] = []
        for d in decisions:
            if d.signal == "buy":
                buy.append(d)
            elif d.signal == "watch":
                watch.append(d)
            else:
                excluded.append(d)

        return FrameStrategyResult(
            snapshot_id=input.snapshot_id,
            timestamp=input.timestamp,
            trading_date=input.trading_date,
            decisions=decisions,
            buy_candidates=sorted(buy, key=lambda d: d.confidence, reverse=True),
            watch_candidates=watch,
            excluded_candidates=excluded,
        )

    # Layer 1 ─────────────────────────────────

    def _generate_candidates(self, input: StrategyInput) -> list[StrategyDecision]:
        """Layer 1: 从帧信号生成候选决策列表。"""
        decisions: list[StrategyDecision] = []
        for signal in input.frame_signals:
            code = str(signal.get("code") or "")
            decisions.append(StrategyDecision(
                code=code,
                name=str(signal.get("name") or ""),
                candidate_tier=str(signal.get("candidateTier") or "N_NEUTRAL"),
                signal="hold",
                confidence=float(signal.get("confidence") or 0),
                rank=int(signal.get("rank") or 999),
                stage=str(signal.get("stage") or ""),
                regime=str(signal.get("regime") or ""),
            ))
        return decisions

    # Layer 2 ─────────────────────────────────

    def _tier_candidates(self, decisions: list[StrategyDecision], input: StrategyInput) -> None:
        """Layer 2: 分层标注 (RankTrend 已完成分层，此处记录原因)。"""
        for d in decisions:
            tier = d.candidate_tier
            if tier == "A_MAIN":
                d.reasons.append("A_MAIN: 主升分层，动量与热度均占优")
            elif tier == "B_IGNITION":
                d.reasons.append("B_IGNITION: 点火分层，需连续确认")
            elif tier == "C_CROWDED":
                d.reasons.append("C_CROWDED: 拥挤分层，入场风险较高")
            elif tier == "D_EXIT_RISK":
                d.reasons.append("D_EXIT_RISK: 退出风险分层，应考虑卖出")
            else:
                d.reasons.append(f"N_NEUTRAL: 中性分层 ({tier})")
            self._apply_theme_support(d, input)

    def _apply_theme_support(self, d: StrategyDecision, input: StrategyInput) -> None:
        support = input.theme_support_by_code.get(d.code) or {}
        if not support:
            return
        d.main_theme = str(support.get("mainTheme") or "")
        d.theme_heat = float(support.get("themeHeat") or 0)
        d.theme_contribution = float(support.get("themeContribution") or 0)
        d.theme_role = str(support.get("themeRole") or "")
        d.theme_support_score = float(support.get("themeSupportScore") or 0)
        d.theme_risk_flags = [str(item) for item in support.get("riskFlags") or []]
        d.theme_reasons = [str(item) for item in support.get("reasons") or []]
        d.reasons.extend(item for item in d.theme_reasons if item not in d.reasons)
        d.risk_flags.extend(item for item in d.theme_risk_flags if item not in d.risk_flags)

        if not bool(input.config.get("useThemeFactorForExecution")):
            return
        if d.theme_support_score >= 70 and "题材拥挤风险高" not in d.theme_risk_flags:
            d.confidence = min(100, d.confidence + min(8, (d.theme_support_score - 70) * 0.2))

    # Layer 3 ─────────────────────────────────

    def _generate_signals(self, decisions: list[StrategyDecision], input: StrategyInput) -> None:
        """Layer 3: 信号生成 — 子类重写此方法定义入场规则。"""
        for d in decisions:
            if d.code in input.positions:
                self._exit_signal(d, input)
            else:
                self._entry_signal(d, input)

    def _entry_signal(self, d: StrategyDecision, input: StrategyInput) -> None:
        """默认入场规则：A_MAIN + 连续确认 B_IGNITION。"""
        if d.regime == "retreat":
            d.signal = "hold"
            d.reasons.append("市场退潮期，暂停入场")
            return
        if d.candidate_tier == "A_MAIN" and d.regime != "weak":
            d.signal = "buy"
            d.reasons.append("A_MAIN 入场信号，regime 非 weak")
        elif d.candidate_tier == "B_IGNITION" and self._is_confirmed_b(d, input):
            d.signal = "buy"
            d.reasons.append("B_IGNITION 连续确认入场")
        elif d.candidate_tier == "B_IGNITION":
            d.signal = "watch"
            d.reasons.append("B_IGNITION 待连续确认")
        else:
            d.signal = "hold"

    def _exit_signal(self, d: StrategyDecision, input: StrategyInput) -> None:
        """默认退出规则：D_EXIT_RISK / C_CROWDED 加速转弱 / 排名退出。"""
        if d.candidate_tier == "D_EXIT_RISK":
            d.signal = "sell"
            d.reasons.append("D_EXIT_RISK 退出信号")
        elif d.rank > 50:
            d.signal = "sell"
            d.reasons.append("排名跌出前 50")
        else:
            d.signal = "hold"

    def _is_confirmed_b(self, d: StrategyDecision, input: StrategyInput) -> bool:
        if not input.previous_frame or d.candidate_tier != "B_IGNITION":
            return False
        prev = input.signal_by_key.get(f"{input.previous_frame['snapshotId']}:{d.code}")
        return bool(prev and str(prev.get("candidateTier") or "") == "B_IGNITION")

    # Layer 4 ─────────────────────────────────

    def _filter_risks(self, decisions: list[StrategyDecision], input: StrategyInput) -> None:
        """Layer 4: 风险过滤 — 子类可扩展。"""
        for d in decisions:
            if d.regime == "retreat":
                d.risk_flags.append("市场退潮")
                if d.signal == "buy":
                    d.signal = "hold"
                    d.reasons.append("风险过滤: 市场退潮期禁止入场")
            if d.candidate_tier == "D_EXIT_RISK":
                d.risk_flags.append("退出风险")
            if d.rank > 100:
                d.risk_flags.append("排名过低")
            if d.confidence < 0:
                d.risk_flags.append("信心为负")
            if bool(input.config.get("useThemeFactorForExecution")) and "题材拥挤风险高" in d.theme_risk_flags:
                if d.signal == "buy":
                    d.signal = "watch"
                    d.reasons.append("题材执行过滤: 拥挤风险高，买入降级为观察")


# ═══════════════════════════════════════════
# 具体策略子类
# ═══════════════════════════════════════════

class RankTrendCandidateStrategy(BaseStrategy):
    key = "rank_trend_candidate"
    label = "RankTrend 候选池"
    description = "买入 A_MAIN 与连续确认后的 B_IGNITION，是当前正式策略。"


class HotTop10Strategy(BaseStrategy):
    key = "hot_top10"
    label = "热榜 Top10"
    description = "只用热榜排名前 10 作为朴素对照组，不使用 RankTrend 分层。"

    def _entry_signal(self, d: StrategyDecision, input: StrategyInput) -> None:
        if d.regime == "retreat":
            d.signal = "hold"
            d.reasons.append("市场退潮期，暂停入场")
            return
        if d.rank <= 10:
            d.signal = "buy"
            d.reasons.append(f"热榜排名 {d.rank} ≤ 10")
        else:
            d.signal = "hold"


class AMainOnlyStrategy(BaseStrategy):
    key = "a_main_only"
    label = "A_MAIN only"
    description = "只买 A_MAIN，衡量主升分层本身的交易贡献。"

    def _entry_signal(self, d: StrategyDecision, input: StrategyInput) -> None:
        if d.regime == "retreat":
            d.signal = "hold"
            d.reasons.append("市场退潮期，暂停入场")
            return
        if d.candidate_tier == "A_MAIN" and d.regime != "weak":
            d.signal = "buy"
            d.reasons.append("A_MAIN 入场 (对照组)")
        else:
            d.signal = "hold"


class BIgnitionOnlyStrategy(BaseStrategy):
    key = "b_ignition_only"
    label = "B_IGNITION only"
    description = "只买连续确认后的 B_IGNITION，衡量点火分层的交易贡献。"

    def _entry_signal(self, d: StrategyDecision, input: StrategyInput) -> None:
        if d.regime == "retreat":
            d.signal = "hold"
            d.reasons.append("市场退潮期，暂停入场")
            return
        if d.candidate_tier == "B_IGNITION" and self._is_confirmed_b(d, input):
            d.signal = "buy"
            d.reasons.append("B_IGNITION 连续确认入场 (对照组)")
        elif d.candidate_tier == "B_IGNITION":
            d.signal = "watch"
            d.reasons.append("B_IGNITION 待连续确认")
        else:
            d.signal = "hold"


class ABCombinedStrategy(BaseStrategy):
    key = "a_b_combined"
    label = "A+B"
    description = "只买 A_MAIN 与连续确认后的 B_IGNITION，是当前正式策略的核心候选池对照。"

    def _entry_signal(self, d: StrategyDecision, input: StrategyInput) -> None:
        if d.regime == "retreat":
            d.signal = "hold"
            d.reasons.append("市场退潮期，暂停入场")
            return
        if d.candidate_tier == "A_MAIN" and d.regime != "weak":
            d.signal = "buy"
            d.reasons.append("A_MAIN 入场 (A+B 对照组)")
        elif d.candidate_tier == "B_IGNITION" and self._is_confirmed_b(d, input):
            d.signal = "buy"
            d.reasons.append("B_IGNITION 连续确认入场 (A+B 对照组)")
        elif d.candidate_tier == "B_IGNITION":
            d.signal = "watch"
            d.reasons.append("B_IGNITION 待连续确认")
        else:
            d.signal = "hold"


STRATEGY_REGISTRY: dict[str, type[BaseStrategy]] = {
    "rank_trend_candidate": RankTrendCandidateStrategy,
    "hot_top10": HotTop10Strategy,
    "a_main_only": AMainOnlyStrategy,
    "b_ignition_only": BIgnitionOnlyStrategy,
    "a_b_combined": ABCombinedStrategy,
}


def get_strategy(key: str = DEFAULT_STRATEGY_NAME) -> BaseStrategy:
    key = normalize_strategy_name(key)
    cls = STRATEGY_REGISTRY.get(key)
    if cls is None:
        raise ValueError(f"strategy '{key}' not registered")
    return cls()
