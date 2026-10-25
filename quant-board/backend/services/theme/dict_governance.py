# -*- coding: utf-8 -*-
"""KPL 题材名录治理层（人工层，manual 不被上游刷新覆盖）。

立项：KPL 题材数据治理 P1（2026-10-25 用户批准 P1-P4 执行；题材周期方案无限期
延后，待题材数据达标后启动）。前史：题材周期 V1/V2 已全量回退（0f1539a4）。

单一事实源分工：
- `themes` / `theme_stock_mappings` = KPL 上游镜像（mapping_refresh 08:30 每日覆盖，
  层级/治理信息**不落**这两集合，防被刷新冲掉）；
- `theme_dict_governance`（本模块）= 人工治理层，单文档 `_id=THEME_GOV`，
  baseline 定义在代码常量（git 管版本），Mongo 是运行时镜像，apply 幂等整写。

baseline 依据（2026-10-25 全量拉取 251 题材 InfoGet Table，证据
`data/backups/theme-governance-20261025/full_tables.json`）：
- excludeThemeNames：非题材（指数成分/持股归类），不作主题材候选；
- familyLinks：真父子挂靠 18 对（T3 正式挂靠 2026-10-25 用户批准：机器人家族仅
  官方背书对+全清单重叠率实证晋升，智元/小米/AGV/外骨骼不挂——官方 Table 无此
  分支即无背书且成分零重叠）；
- crossCutBoards：横切假父子禁挂登记（父题材=视角归类，分支名指向独立题材；
  判定规则=Table 分支 exact 匹配独立题材 ≥2，人形机器人 exact=0 不在列）；
- aliasPairs：themes 名录内部异名归一——2026-10-25 扫描结论=无真异名对
  （近名 8 组全为细分关系），空清单如实登记；
- candidates：其余分支×题材匹配对 100 条 pending 登记（不消费，逐条批后升
  familyLinks 或弃）。
"""
from __future__ import annotations

from typing import Any

COLLECTION = "theme_dict_governance"
DOC_ID = "THEME_GOV"
GOVERNANCE_VERSION = "gov-v2"

# ── baseline（git 管版本；改动须同步治理文档并升 GOVERNANCE_VERSION） ──

EXCLUDE_THEME_NAMES = [
    "中证A50成分股",  # 指数成分归类，非炒作题材
    "大基金持股",     # 持股归类
    "汇金证金持股",   # 持股归类
]

# 官方背书真父子：child → parent（挂靠语义=子题材成分股的候选扩展并入父题材）。
# T3 正式挂靠（2026-10-25 用户批准）：candidates 100 对 × 成分股重叠率
# （|child∩parent|/|child|，theme_stock_mappings 实测）双峰分布——≥0.40 自动晋升；
# 0.30-0.40 仅产业链/品牌真细分人工裁定；<0.30 全拒（横切视图/兄弟大类/事件关联，
# 挂靠将稀释主题材判定）。familyLinks 语义=child 细分挂 parent 大类
# （固态电池概念/光伏辅材 2 对候选方向已修正）。
FAMILY_LINKS: list[dict[str, str]] = [
    {"parent": "人形机器人", "child": "宇树机器人",
     "evidence": "官方Table L1[宇树相关]: 参股17+合作商27；重叠 42/46=0.913"},
    {"parent": "人形机器人", "child": "优必选机器人",
     "evidence": "官方Table L1[优必选]: 参股4+合作商8+供货商4；重叠 19/27=0.704"},
    {"parent": "商业航天", "child": "卫星互联网", "evidence": "重叠 42/52=0.808"},
    {"parent": "锂电池材料", "child": "锂矿", "evidence": "重叠 20/29=0.690（上游细分）"},
    {"parent": "充电桩", "child": "华为液冷快充", "evidence": "重叠 8/12=0.667（品牌家族）"},
    {"parent": "农业种植", "child": "农机概念", "evidence": "重叠 10/17=0.588（产业链细分）"},
    {"parent": "AI硬件", "child": "液冷服务器", "evidence": "重叠 44/78=0.564（产业链细分）"},
    {"parent": "核电", "child": "可控核聚变", "evidence": "重叠 44/78=0.564（前沿细分；反向不挂）"},
    {"parent": "光伏新技术", "child": "钙钛矿电池", "evidence": "重叠 16/34=0.471（技术细分）"},
    {"parent": "服务消费概念", "child": "旅游", "evidence": "重叠 19/43=0.442（大类细分）"},
    {"parent": "锂电池材料", "child": "固态电池概念",
     "evidence": "重叠 56/138=0.406（候选方向修正：细分挂大类）"},
    {"parent": "外卖概念", "child": "京东概念", "evidence": "重叠 10/24=0.417（事件主体同源）"},
    {"parent": "光伏", "child": "硅", "evidence": "重叠 11/27=0.407（上游材料，KPL官方列光伏链）"},
    {"parent": "国产芯片概念", "child": "摩尔线程概念", "evidence": "重叠 15/37=0.405（品牌家族）"},
    {"parent": "华为昇腾", "child": "超节点概念",
     "evidence": "重叠 10/52=0.37（人工裁定：超节点=昇腾架构真细分）"},
    {"parent": "光伏", "child": "光伏辅材",
     "evidence": "重叠 47/128=0.367（候选方向修正：细分挂大类）"},
    {"parent": "智能驾驶系统", "child": "激光雷达",
     "evidence": "重叠 6/117=0.316（人工裁定：智驾核心零部件真细分）"},
    {"parent": "AI智能体概念", "child": "AI低代码概念",
     "evidence": "重叠 7/23=0.304（人工裁定：智能体应用细分）"},
]

# 横切假父子禁挂（父题材=视角归类视图；分支指向独立题材，挂靠将造成多父/热度吸走）
CROSS_CUT_BOARDS: dict[str, list[str]] = {
    "关税战概念": ["医美", "小金属", "工业母机", "旅游", "港口航运", "自主可控", "跨境支付"],
    "新质生产力": ["光伏", "半导体设备", "大模型概念", "工业母机", "氢能源", "脑机接口"],
    "高股息": ["中药", "地产链", "煤炭概念"],
    "复苏消费概念": ["冰雪旅游概念", "旅游", "预制菜"],
    "国企人工智能": ["大模型概念", "文生视频概念", "算力租赁概念"],
    "中部崛起概念": ["工业母机", "煤炭概念", "电力"],
    "反内卷概念": ["光伏", "煤炭概念", "锂矿"],
    "犒赏经济": ["旅游", "游戏", "谷子经济概念"],
    "出海": ["光伏", "游戏"],
    "半导体存储器": ["HBM存储", "SRAM存储概念"],
    "设备更新": ["半导体设备", "工业母机"],
    "低空经济": ["旅游", "碳纤维"],
    "涨价概念": ["小金属", "碳纤维"],
    "比亚迪产业链": ["充电桩", "汽车芯片"],
    "腾讯AI概念": ["AI医疗", "云计算"],
    "端侧AI概念": ["AI手机", "AI眼镜概念"],
    "新消费": ["旅游", "谷子经济概念"],
    "谷歌概念": ["AI硬件", "AI营销"],
    "欧洲电力基建": ["储能概念", "风电"],
    "词元概念": ["AI智能体概念", "算力租赁概念"],
    "俄乌重建": ["农机概念", "电力"],
}

# themes 名录内部异名归一（2026-10-25 扫描：无真异名对，空清单如实登记）
ALIAS_PAIRS: list[dict[str, str]] = []

GOVERNANCE_BASELINE: dict[str, Any] = {
    "version": GOVERNANCE_VERSION,
    "excludeThemeNames": EXCLUDE_THEME_NAMES,
    "familyLinks": FAMILY_LINKS,
    "crossCutBoards": CROSS_CUT_BOARDS,
    "aliasPairs": ALIAS_PAIRS,
    "notes": (
        "T3 正式挂靠 2026-10-25 用户批准：18 对（2 官方背书 + 16 重叠率实证晋升，"
        "≥0.40 自动 + 0.30-0.40 真细分人工裁定；<0.30 共 78 对拒绝）。"
        "智元/小米/AGV/外骨骼不挂（官方 Table 无分支且成分零重叠）；"
        "横切父题材分支禁挂；非题材 3 条剔除。"
    ),
}


def normalize_name(value: Any) -> str:
    """题材名归一：去「概念板块/概念/板块」后缀（与 projection._normalize_theme_label 同式）。"""
    name = str(value or "").strip()
    for suffix in ("概念板块", "概念", "板块"):
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
    return name.strip()


class GovernanceSpec:
    """治理层运行时视图（纯数据，加载自 Mongo 镜像）。"""

    def __init__(self, doc: dict[str, Any] | None) -> None:
        doc = doc or {}
        self.version = str(doc.get("version") or "")
        self.exclude_names = {normalize_name(x) for x in doc.get("excludeThemeNames") or []}
        self.family_links = {
            normalize_name(link.get("child")): str(link.get("parent") or "")
            for link in doc.get("familyLinks") or []
            if link.get("child") and link.get("parent")
        }
        self.cross_cut_boards = {
            str(parent): [str(b) for b in branches]
            for parent, branches in (doc.get("crossCutBoards") or {}).items()
        }
        self.alias_pairs = list(doc.get("aliasPairs") or [])
        self.found = bool(doc)

    def __bool__(self) -> bool:  # 缺文档 → falsy，调用方 fail-visible 注记
        return self.found


def load_governance(db: Any) -> GovernanceSpec:
    """加载治理层（只读）；集合/文档缺失返回空 spec（found=False）。"""
    try:
        doc = db[COLLECTION].find_one({"_id": DOC_ID})
    except Exception:  # noqa: BLE001 — 采集链内使用，治理层读失败不阻断采集
        return GovernanceSpec(None)
    return GovernanceSpec(doc if isinstance(doc, dict) else None)


def apply_governance(db: Any, baseline: dict[str, Any] | None = None) -> dict[str, Any]:
    """baseline 整写落库（幂等 replace）；默认写代码常量。返回落库文档摘要。"""
    from datetime import datetime

    doc = {"_id": DOC_ID, **(baseline or GOVERNANCE_BASELINE),
           "appliedAt": datetime.now().isoformat(timespec="seconds")}
    db[COLLECTION].replace_one({"_id": DOC_ID}, doc, upsert=True)
    return {"version": doc["version"],
            "excludeThemeNames": len(doc["excludeThemeNames"]),
            "familyLinks": len(doc["familyLinks"]),
            "crossCutBoards": len(doc["crossCutBoards"]),
            "aliasPairs": len(doc["aliasPairs"])}
