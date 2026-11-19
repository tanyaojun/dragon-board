# -*- coding: utf-8 -*-
"""主题材判定（跟强不跟弱）——个股当日炒作主题材的确定性口径。

立项：KPL 题材数据治理 P2（2026-10-25 用户批准 P1-P4 执行）。
背景：旧 mainTheme = themes[0]，顺序由 theme_stock_mappings 查询的 themeId
字符串升序决定（大业股份 603278：轮胎"223" < 人形机器人"84"），与当日
炒作无关——大业 9-10 月被锁死判「轮胎」的根因。

口径（治理方案冻结）：
- 个股 themes 名单 ∪ 治理层官方背书家族父题材（family 扩展）
  × 当日题材强度（hot_theme sector 行）取最强 = 当日炒作主题材；
- 强度排序键：ztCount 降序 → heatScore 降序 → rank 升序 → 名字稳定序
  （涨停数是题材当日炒作最硬的证据，热度次之，榜单名次再次）；
- 非题材集合（治理层 excludeThemeNames，如「中证A50成分股」）不参与；
- fail-visible：候选全部无当日强度行 → mainTheme=None（basis 说明），
  绝不回退 themes[0] 旧口径（那是字典序伪装）。

纯函数零 IO：strength 表由调用方注入（生产=market_context.sectors，
历史回放=帧内嵌 sectorRows 当日帧，2026-11-19 起独立集合已 drop），单一事实源不复制。
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping


def _norm(value: Any) -> str:
    """题材名归一（与 projection._normalize_theme_label 同式：去概念板块/概念/板块后缀）。"""
    name = str(value or "").strip()
    for suffix in ("概念板块", "概念", "板块"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    return name.strip()


def theme_names_of(row_themes: Any) -> list[str]:
    """themes 字段两代格式统一取名单：list[dict]（4-6 月旧格式）→ 取 name；list[str] → 原样。"""
    if not isinstance(row_themes, list):
        return []
    out: list[str] = []
    for t in row_themes:
        if isinstance(t, dict):
            name = str(t.get("name") or t.get("id") or "").strip()
        else:
            name = str(t or "").strip()
        if name and name not in out:
            out.append(name)
    return out


def _sort_key(cand: dict[str, Any]) -> tuple:
    """强度排序键：有强度行 (-zt, -heat, rank) 前置；无强度行垫底；名字稳定兜底。"""
    if cand.get("hasStrength"):
        zt = cand.get("ztCount")
        heat = cand.get("heatScore")
        return (
            0,
            -(zt if isinstance(zt, (int, float)) else -1.0),
            -(heat if isinstance(heat, (int, float)) else -1.0),
            cand.get("rank") if isinstance(cand.get("rank"), (int, float)) else 10**9,
            str(cand.get("name") or ""),
        )
    return (1, 0.0, 0.0, 0, str(cand.get("name") or ""))


def resolve_active_theme(
    row_themes: Any,
    sectors_by_name: Mapping[str, Mapping[str, Any]],
    *,
    family_links: Mapping[str, str] | None = None,
    excluded_names: Iterable[str] | None = None,
) -> dict[str, Any]:
    """个股当日主题材判定（纯函数）。

    参数：
      row_themes: 股票行 themes 字段（list[str] 或 list[dict] 两代格式）
      sectors_by_name: {归一题材名: sector 行}（须含 ztCount/heatScore/rank，
        缺字段按无值处理不伪造）
      family_links: {子题材名: 父题材名}（治理层官方背书挂靠，原名或归一名均可）
      excluded_names: 非题材名单（治理层 excludeThemeNames，不参与判定）

    返回 {mainTheme, basis, candidates[], degraded}：
      mainTheme: 最强题材原名（family 扩展来源时即父题材登记名）或 None
      basis: 判定依据句（"ztCount=16 rank=2 最强" / "sector_strength_missing" 等）
      candidates: 全部候选及强度明细（透明可审计）
      degraded: True = 无任何强度行（判定不可考，不伪装）
    """
    names = theme_names_of(row_themes)
    if not names:
        return {"mainTheme": None, "basis": "no_themes", "candidates": [], "degraded": False}

    excluded = {_norm(x) for x in (excluded_names or ()) if str(x or "").strip()}
    family = {_norm(k): v for k, v in (family_links or {}).items()}

    # 候选构建：个股 themes + family 父题材扩展；非题材剔除
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(name: str, origin: str) -> None:
        norm = _norm(name)
        if not norm or norm in excluded or norm in seen:
            return
        seen.add(norm)
        sector = sectors_by_name.get(norm)
        # strength 行字段缺失不伪造：zt/heat None 如实透出
        candidates.append({
            "name": name,
            "norm": norm,
            "origin": origin,
            "hasStrength": sector is not None,
            "ztCount": (sector or {}).get("ztCount"),
            "heatScore": (sector or {}).get("heatScore"),
            "rank": (sector or {}).get("rank"),
        })

    for name in names:
        _add(name, "stock_themes")
        parent = family.get(_norm(name))
        if parent:
            _add(parent, "family_link")

    if not candidates:  # 全部被剔除
        return {"mainTheme": None, "basis": "all_themes_excluded",
                "candidates": [], "degraded": False}

    candidates.sort(key=_sort_key)
    top = candidates[0]
    if not any(c["hasStrength"] for c in candidates):
        return {"mainTheme": None, "basis": "sector_strength_missing",
                "candidates": candidates, "degraded": True}
    basis = (f"ztCount={top['ztCount']} heatScore={top['heatScore']} "
             f"rank={top['rank']} 最强" + ("（家族挂靠）" if top["origin"] == "family_link" else ""))
    return {"mainTheme": top["name"], "basis": basis,
            "candidates": candidates, "degraded": False}
