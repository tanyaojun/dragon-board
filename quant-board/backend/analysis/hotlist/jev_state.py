# -*- coding: utf-8 -*-
"""jev state 构建器（N15 扩窗复验保留件）。

历史：阶段 1（情绪回放 REJECT）与阶段 2（五维打标 REJECT）的构建器已随证伪清理
（2026-09-28，数据可再生，判定留档 hotlist-jev/*.md）；仅保留阶段 3 驱动打标所需。
fail-visible 约定见 quant-board/docs/hotlist-jev/hotlist-jev-sentiment-design.md §8。
"""


def _tag_names(tags) -> list:
    """tags 兼容两种形态：[{Name:...}] 对象数组或字符串数组。"""
    out = []
    for t in tags or []:
        if isinstance(t, dict) and t.get("Name"):
            out.append(str(t["Name"]))
        elif isinstance(t, str) and t:
            out.append(t)
    return out


def build_driver_label_narrative(ths_reason: str, row: dict, mappings: list) -> str:
    """涨停驱动打标叙事：THS 涨停原因 + 行业/题材上下文 + 业务底座映射（≤4 条）。

    映射缺失时如实输出"无题材映射记录"（该缺失本身是判别信号）。
    """
    name = row.get("name") or row.get("code") or "未知"
    head = f"{name}（{row.get('mainTheme') or '行业未标注'}，热榜第{row.get('rank')}名）：今日涨停原因：{ths_reason}。"
    segs = []
    for m in (mappings or [])[:4]:
        theme = m.get("themeName") or m.get("themeId") or "未知题材"
        tags = "/".join(_tag_names(m.get("tags")))
        reason = str(m.get("reason") or "")[:60]
        segs.append(f"【{theme}】{('标签:' + tags + '；') if tags else ''}{reason}")
    base = "；".join(segs) if segs else "无题材映射记录"
    return f"{head}公司业务底座（题材映射）：{base}。"[:1200]
