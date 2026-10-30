# -*- coding: utf-8 -*-
"""题材层「板块龙头隔日连板」弹药纯函数层（2026-10-20 用户裁决「从 L3 开始做」后续步）。

分层边界（AGENTS §2.2：算法→analysis、服务/取数→operations）：
- 本文件**只放纯函数**：分桶/龙头排序/题集常量/叙事拼装/基准率汇总；无 DB、无网络、无模型。
- 取数与 jev 调用编排在 `backend/operations/theme_leader_label.py`；
- 基线脚本 `scripts/theme_leader_sustain_baseline.py` 也 import 本文件的分桶与排序，
  **分桶口径只有一份**（改这里=改基线=改投喂，不允许第二套）。

为什么先要「结构基准率」：实测 2026-08-01~10-19（50 交易日 / 341 个板块龙头样本）纯结构特征
已把次日连板率从总体 34.3% 拉到 83.3%（4板+|≥8家|早封）。题集里必须把同桶历史基准率摆给模型，
否则无法判断「模型是否只是复述结构特征」——验收门槛也因此定为「同桶 ≥15pp 提升」（§预登记）。
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable

from backend.analysis.hotlist.jev_driver_ammo import _questions_hash

# ── 代际戳 ──
# 题集/口径任何一字变更必须换代（跨代不可比）。v1 = 2026-10-20 定版（龙头隔日连板两题）；
# v2 = 2026-10-20 晚确定性证据门；v3 = 2026-10-22 归因修复（早报段落级匹配 + L2 板内解析
# 纳入证据 + 门条件收窄为「L3 与 L2 均无可用证据」+ 非题材粗分桶不纳入判定范围）；
# v6 = 2026-10-23 四题判据增档；**v7 = 2026-10-24 置信度归因后空间题加历史锚规则**
# （14 只 v6 样本实测空间题 conf 均值 0.435 全场最差且无锚——判据加「锚必须先对」
# 硬规则，criteria 各档门不动；同批语料四补见 AMMO 2026-10-24b）；
# **v8 = 2026-10-24 空间题「越锚」铸词内联定义**（6b008b85 review P3：模型直读可能
# 不解裸铸词，改「要选高于锚的档位（越锚）时」——v7 仅 1 条样本（榕基 10-23 档，
# 页面重跑产生，保留作历史参照），此刻换代弃置成本最小且验收窗保持单代际，
# 推翻 review「并入下一自然换代点」原注；详见预登记 §17）。
# **v9 = 2026-10-26 零区分度处置**（A 检验 0/7 判对但零信息量；用户批准 §21.3 三项，
# AMMO 2026-10-26a 率值锚行配套）：①硬规则②单向改双向——偏离锚（上调或下调）都
# 须引用锚行具体数字+锚未覆盖新证据；②新增默认起判档规则③（按连板高度：1-3 板→peak、
# 4+ 板→space_1，依据=分层杀伤证据非桶众数，随 v9 冻结）；③space_1/peak criteria 绑
# 锚行「再走≥1板率」读数（三成上下/不足三成），非写死绝对阈值。
# **v10 = 2026-10-27 空间龙一规则配套**（用户裁决：龙一=10日涨幅最高，非真连板——
# 10-26 正裕 3 板卡位次日跌停 vs 大业断板反包 +8% 实证）：①续板题加规则⑤——待判龙头
# 当日未封板（断板反包候选）时判「重新上板概率」，封板类判据不适用、改按断板承接/
# 梯队/题材证据，锚缺失如实对待；②推导侧配套见 theme_leader_baseline（候选池扩近 3 日
# 封板池）与结构行未封板显式标注（AMMO 2026-10-27a）。
# **v11 = 2026-10-27 判据遵从收紧**（10-26 双案例：上海九百按判据应判 weak_extend 却判
# ending（三信号只中新闻断流一条）、大业无新鲜催化判 strong_extend 0.89 次日未续；
# 已结算 8 行对账=低档 5/5 全对、中档 1/3 无区分度，归因=锚定不对称+延续性题零引用义务，
# 预登记 §22，2026-10-27 用户批准）：①续板题规则①对称化——最细同桶基线为概率中枢，
# 偏离一档以上（上调或下调）都须点名基线行数字+锚外新证据，同桶样本不足未出率时以
# 「按连板高度」桶为中枢；②延续性题加引用义务——ending 须点名 ≥2 个判据信号对应
# 事实、strong_extend 须点名排队事件或近 2 日新增标题（打标交叉行可作引用源），
# 未封板龙一场景无锚须保守并降低置信。v12（2026-10-28）在 ①② 基础上修延续/深度
# 盲区（贫料≠断流、结构再点火扩源、跨题一致性）并分轨，见题集上方 v12 注。
# **v12 = 2026-10-28 双龙一分轨 + 延续/深度判据修复**（用户四点裁决，预登记
# theme-leader-v12-dual-leader-preregistration-20261028.md）：①龙一分轨——主板
# （60/000-003）与双创（30x/68x）各按**复合排序**独立取龙一（同日三轮裁决定稿）：
# 空间板=10日涨幅最高的高位股，三种情况（真连板/断板反包/断板不反包未跌停）均参与
# ——高度≥2 者组成空间板组整体优先、组内 gain10 最高（涨停时间晚于龙二依然龙一）；
# 全首板（主板/双创涨跌幅限制不同，首板间 gain10 不可比）按当日首封最早；
# 断板不反包且今日跌停剔除（「未跌停」条件）；AI硬件实证：gain10 主键会选出回撤股长缆
# -1.6% 而漏掉早封自身催化的菲林格尔；v10 的 rank_board_stocks_space 随之淘汰删除），
# 每板块 ≤2 行
# （`segment_of`/`space_leaders_by_segment`/`structure_line_dual`；§18.2 唯一性键升级为
# (date, board, segment)）；②深度题「贫料 ≠ 断流」——零痕迹+家数扩张判 igniting 优先，
# 家数萎缩/龙头断板才可 ebbing；③延续题 strong_extend 引用义务扩源（结构再点火信号
# 二选一可点名）+ ending 方向约束（家数扩张不得 ending）；④跨题一致性硬规则
# （igniting/fermenting 时空间不得 peak、延续不得 ending，除非点名锚/基线数字+新证据）；
# ⑤A2 拆题——板块级两题（深度/延续）每板块 1 次（双龙一并列结构行，
# `build_sector_narrative`），个股级两题（续板/空间）每轨龙一各 1 次。
# **v13 = 2026-10-29 未封板 insufficient 禁令**（预登记
# theme-leader-v13-unsealed-insufficient-preregistration-20261029，用户批准换代；
# 题面三处）：①续板题规则⑤补「锚缺失≠可判 insufficient——基线/承接/梯队/题材证据
# 任一在场必须按①给档，锚缺失仅强制降置信 ≤0.6」；②空间题规则③补未封板分支默认档
# =空间锚最细出率桶起判，锚行整体缺席才允许自判；③两题 insufficient criteria 补
# 对称禁令（10-28 首批实证：上海九百双题证据在场仍答 insufficient）。
QUESTION_SET_VERSION_THEME_LEADER = "v13"
# 原料代际：板块结构（触板−炸板二分、真连板）+ 题材语料（韭研产业树 + 开盘啦题材事件/
# 新闻（Kword 标签）/日历 + 题材热度序列 + 板内解析）。
# 2026-10-24a（语料精简+匹配收紧，2026-10-24 用户批准；题集 v6 冻结不动）：
# ① 删叙事重复头行 corpus_line（采集日/节点数/条数与证据块头完全重复）；
# ② 题材新闻与前瞻日历双空时合并为一行无匹配行；③ 事件正文剥确定性电头；
# ④ 共享子串锚加泛词黑名单（「应用」级泛词不再充当锚）。ALIASES 不加：
# kword 词表核验（29 个 distinct 标签，2026-10-24）无字面等价缺口——近义标签
# （算力概念/算力 等）已由包含匹配覆盖，新闻层瓶颈是供给稀疏（全题材 1-5 条/日），不是词表。
# 2026-10-24b（置信度提升批次，2026-10-24 用户批准四项；与题集 v7 同批换代）：
# S1 结构行加近 5 日板块封板家数序列（判据「扩张中/萎缩」从两点变形状）；
# S2 题材热度序列窗 5→10 日（「断流/见顶」需要更长窗）；S3 龙头驱动标签第二匹配通道
# （板块名命中错位宏观节点时补对口催化，只并列披露不替换）；Q1 新增空间锚行
# （历史连板周期自当日高度剩余板数分布，右删失剔除）。
# 2026-10-24c（盘面语料四补，2026-10-24 用户批准；对照韭研个股链 v3.2「判据点名
# 要、语料缺席」盘点；题面 v8 判据零改动）：①基线行补透出封板时间/跟风梯队/昨日承接
# 三组单维桶率（此前已算仅落审计）；②板内梯队形态行（首板/2板/3板+分布+次高连板差，
# climax 判据「首板潮/中军成形/高标分化」直接可读）；③前向交易日轴行（「未来 1-2 个
# 交易日」跨周末可数，日历源三级降级显式标注）；④板内炸板面行（今日/昨日触板未封，
# 板内口径同触板二分）+ 结构行昨日口径修正（prevBoardN 语义=昨日封板且今日仍封，
# 旧文案误写为「昨日封板 N 只」吞掉断板数，本版以 prevTotal−prevBoardN 显式出断板）。
# 2026-10-24d（review 处置，2026-10-24）：断板改同名成员口径——新增 prevStill（昨日同名板块
# 封板股中今日仍封数，prevTotal−prevStill 恒 ≥0）；旧实现用 prevBoardN（今日成员交集，含昨日
# 他板块迁入股），迁移场景减出负数甚至「昨日封 0 仍封 2」自相矛盾。同时修防御分支原始 None
# 泄漏（「今日仍封 None 只」→「今日仍封不可考」）。
# 2026-10-26a（空间锚每档基率化，2026-10-26 用户批准；预登记 §21.2）：Q1 空间锚行每档
# 只给「平均再走 X 板」（实测全 <1 板）与档位语义（space_1≈1 板/peak=顶部）粒度错配，
# 10-23 八龙头全 peak 塌缩归因之一——改为每档「再走≥1板率/≥2板率/中位再走/均值/样本量」，
# 率值口径与档位判定直接对齐；题面 v8 判据零改动，hash 不变。
# 2026-10-27a（空间龙一规则配套，2026-10-27 用户裁决；预登记 §21.6）：①结构行
# leader_sealed_today=False 分情形——「待判龙一 X（code）今日未封板（断板反包候选，
# 10 日涨幅 +Y% 居候选池首位）」替代「连板高度不可算」哑谜，跟风段如实改不可算；
# ②新增 rank_board_stocks_space（10日涨幅→连板高度→首封），历史窗口/基线仍用旧
# rank_board_stocks（口径分代见 §21.6）。题面 v10（续板题规则⑤）同批换代。
# 2026-10-27b（打标交叉原料行，2026-10-27 用户批准并入 v11 批次；预登记 §22）：
# 新增 driver_cross_line——join hotlist_jev_driver_labels（final 优先、midday 兜底、
# 槽位显式标注、双缺 fail-visible 出「无当日个股打标记录」），四轴（驱动类别 top-2/
# 催化深度/新鲜度/买盘逻辑）枚举译名+概率并列，行内自描述口径（个股级机器判定·供交叉
# 参考）。动机=题材语料空窗时给延续性/续板题一个结构化引用锚（10-26 上海九百/大业
# 双病案），并从个股侧补题材关键词匹配漏供给。只并待判龙头个股行，**不并 boardDragons**
# （真连板口径推导，与 v10 空间龙一双口径，单一事实源红线）。题面 v11 同批换代。
# 2026-10-28a（v12 批次，2026-10-28 用户批准；预登记 theme-leader-v12 §4）：
# ①涨停原因行 limitup_reason_line——join 韭研 expound（单一事实源
# `jev_label_jiuyan.expound_reason()`，与打标链读口同源；已落库零外呼），仅待判龙一
# 自身（2026-10-28 用户裁决收窄：板块成员原因不列，板内同伴由既有板内解析行承载）；
# ②板块强度行 plate_strength_line——KPL 层1
# RealRankingInfo（`kpl_ranking_service.get_sector_ranking`，按日查史已通接口）名称桥
# 匹配，未匹配/取数失败 fail-visible；③题材事件行收窄（theme_event_digest 同批，
# 用户裁决）：仅标题+热度+日期、正文不出、仅正文级关联标「弱匹配」降级；
# ④（2026-10-28b，code review P1-4）：个股级叙事头部注入轨别身位〔主板龙一/双创龙一〕
# ——题面规则⑥/空间题⑤的前提「若叙事标注分轨」此前不成立，双轨身位对模型不可见；
# AMMO_VERSION_THEME_LEADER 同批换代。
# 2026-10-30a（龙虎榜事实行，2026-10-30 用户指示；预登记 §23）：新增 lhb_line——join
# 当日 HisBeOnTheLHB 龙虎榜事实（取数单一源=jev_lhb_ammo.collect_lhb_facts，与方向线
# task-6 同源；个股级=待判龙一+板内封板成员、板块级=双龙一+板内封板成员代码过滤），
# 四种结构化状态全 fail-visible（取数失败/榜单未生成/0 只上榜/有上榜逐只列），主力
# 净额口径行内标注（盘中主力大单资金流，非交易所龙虎榜席位额，lhb-scaling-verification
# §13.3 裁决）。题集判据零改动（沿 2026-10-24c 先例：纯语料补行不动题面 hash；把龙虎榜
# 列为判据显式引用源须另走换代预登记）。
# 2026-10-30d（语料精简，2026-10-30 用户确认删除清单后执行）：删重复自我解释与工程注记
# ——「无数据 ≠ 无催化」复述、「fail-visible/不冒充」行话、「跌多涨少（偏弱）」/「（断板 X）」
# 可推导语气、端点名（HisBeOnTheLHB/expound）、「匹配方式 exact」「另一条打标链…供交叉
# 参考」注记、空间锚定义复述；近 1 日家数序列改为 ≥3 日才出行。事实与防误读锚全保留。
# 共享行（盘面事实/池内涨跌比/触板未封在 jev_label_jiuyan，与打标链同源）同步生效。
# 2026-10-30e（用户指示）：①新增 15:00 收盘总结行「盘面总结（KPL 15:00）」作当日盘面
# 全市场介绍（紧跟盘面事实行后，两级叙事共用；取数单一源=直播归档，缺席不出行）；
# ②韭研↔KPL 板块名经济/产业后缀桥（digest.board_keywords 公共函数，冰雪经济↔冰雪
# 产业 10-29 播报漏配实证），直播 plate 命中同步用 keys。
# 2026-10-30g（用户裁决，括号注释全清理）：叙事内括号只留数据——基线/空间锚/龙虎榜/
# 强度行头部口径注、层2 缺口注、最近记录日注、原因行尾部注、降级原因括号全删（工程词
# unmatched/fetch_failed 中文化）；样本数/排名/买卖额等数据括号与「不代表无催化」类
# 语义锚保留。
# 2026-10-30f（用户指示）：①直播只收板块相关时间点语料——空板块名条目命中指数/成交
# 综述词（三大指数/上证指数/创业板指/沪深京三市/全市场等，近 5 日归档实测判别有效）
# 不进板块播报（大盘综述已由盘面事实行与盘面总结行承载）；②来源注记删（纯数据源头
# 说明，不影响读数语义）：跌停行「全市场·东财跌停池」、连板梯队「韭研」/「THS交叉」→
# 「交叉」、板块强度「KPL 801xxx 指数·按日查史」、板块序列「KPL·801xxx 稳定 ID 锚」、
# 直播头「实时流·仅标注时点可得」、打标交叉行「打标链+题集版本」、证据块头部与
# 催化/事件/新闻/日历/板内解析行的「韭研产业树/开盘啦/韭研异动」字样；口径与降级
# 披露（真连板口径、采集池回退、右删失、龙虎榜主力净额口径）全保留。
AMMO_VERSION_THEME_LEADER = "2026-10-30g"


# ── 分桶（唯一口径：基线脚本与投喂叙事共用） ──
def streak_bucket(s: Any) -> str:
    """真连板高度分桶（None=不可算）。"""
    if s is None:
        return "unknown"
    try:
        n = int(s)
    except (TypeError, ValueError):
        return "unknown"
    if n <= 1:
        return "1"
    if n == 2:
        return "2"
    if n == 3:
        return "3"
    return "4+"


def board_count_bucket(n: Any) -> str:
    """板块当日封板家数分桶。"""
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "unknown"
    if v >= 8:
        return ">=8"
    if v >= 5:
        return "5-7"
    if v >= 3:
        return "3-4"
    return "1-2"


def seal_time_bucket(t: Any) -> str:
    """封板时间分桶（无时间=unknown）。"""
    s = str(t or "")[:5]
    if len(s) != 5 or s[2] != ":":
        return "unknown"
    if s <= "10:00":
        return "early<=10:00"
    if s <= "13:00":
        return "mid<=13:00"
    return "late>13:00"


def ladder_bucket(n: Any) -> str:
    """板块内跟风（真连板 >= 龙头-1）家数分桶（cap 3）。"""
    try:
        v = int(n)
    except (TypeError, ValueError):
        return "unknown"
    return str(min(v, 3))


def prev_peer_bucket(prev_peers: Any) -> str:
    """昨日同板块其它封板股家数分桶（None=昨日不可考）。"""
    if prev_peers is None:
        return "prev_unknown"
    v = int(prev_peers)
    if v == 0:
        return "prev0"
    if v <= 2:
        return "prev1-2"
    return "prev3+"


def _time_key(t: Any) -> str:
    s = str(t or "")[:5]
    return s if len(s) == 5 and s[2] == ":" else "99:99"


def rank_board_stocks(stocks: list[dict]) -> list[dict]:
    """板块内排序：真连板最高 → 封板时间最早（None 垫底）。龙一=首位。

    输入 `[{code, name?, time?, streak?}]`；纯排序不改输入。
    2026-10-27 起仅作历史窗口/回退口径（baseline 构建等）；当日标注龙一现用
    `rank_board_stocks_seal`（v12 复合排序，历史沿革见 AMMO 注记）。
    """
    return sorted(stocks, key=lambda s: (-(s.get("streak") or 0), _time_key(s.get("time"))))


def rank_board_stocks_seal(candidates: list[dict]) -> list[dict]:
    """龙一复合排序（v12 定稿，2026-10-28 用户三轮裁决合成）：空间板优先、首封时间次之。

    用户定义（定稿）：空间板 = **10日涨幅最高的高位股**，分三种情况——真连板 /
    断板反包 / 断板不反包未跌停；同板块内 10日涨幅一致（主要是首板，主板与双创涨跌幅
    限制不同不可同类对比）→ 涨停时间优先。

    可操作键（单一事实源；「空间」用连板高度判定身份，组内以 10日涨幅定最高——
    首板间 gain10 差异是回撤节奏不是空间，不可裸比，AI硬件 10-28 实证 gain10 主键会
    选出回撤股长缆 -1.6% 而漏掉早封自身催化的菲林格尔）：
    ① **空间板组整体优先**：候选高度 ≥2（`height`：当日封板股=当日真连板 streak 与
       近 3 日历史高度取大；断板反包/断板不反包股=近 3 日内最近封板日高度，由调用方
       填）——三种情况（真连板/断板反包/断板不反包未跌停）均参与；
    ② 空间板组内按 **10日涨幅最高**（用户规则 1）→ 并列时当日首封最早 → 高度降序
       （「涨停时间晚于龙二依然龙一」）；
    ③ 全首板（高度 ≤1 或不可算，gain10 不可比）：按当日首封最早 → 10日涨幅并列
       → 高度降序；
    ④ 断板不反包且**今日跌停**的候选由调用方剔除（「未跌停」条件，大面股不是龙一）；
       真连板不可算按首板参与时间排序（fail-visible，不猜）。
    v10 的 gain10 主键口径函数（rank_board_stocks_space）随 v12 淘汰删除（红线：改录用
    删除，历史见 AMMO 注记）。纯排序不改输入。
    """
    def _gain(s: dict) -> float:
        return s["gain10"] if s.get("gain10") is not None else float("-inf")

    def _h(s: dict) -> int:
        h = s.get("height")
        return h if isinstance(h, int) else 0

    # 两组排序键不同（空间板组内 gain10 最高优先，首板组内时间优先），分组各自排序拼接
    highs = [s for s in candidates if _h(s) >= 2]
    rest = [s for s in candidates if _h(s) < 2]
    highs.sort(key=lambda s: (-_gain(s), _time_key(s.get("time")), -_h(s)))
    rest.sort(key=lambda s: (_time_key(s.get("time")), -_gain(s), -_h(s)))
    return highs + rest


def segment_of(code: Any) -> str | None:
    """龙一轨别（v12 分轨，2026-10-28 用户裁决）：主板 main=60x/000-003；
    双创 growth=300/301/302（创业板）+ 688/689（科创板）。北交所已由上游口径剔除；
    未知前缀返回 None（fail-visible，不猜轨）。输入可带交易所前缀（sh600715），取后 6 位。
    """
    c = str(code or "")[-6:]
    if c[:2] == "60" or c[:3] in ("000", "001", "002", "003"):
        return "main"
    if c[:2] in ("30", "68"):
        return "growth"
    return None


SEGMENT_CN = {"main": "主板", "growth": "双创"}


def space_leaders_by_segment(candidates: list[dict]) -> list[tuple[str, dict]]:
    """分轨龙一（v12）：同一排序键（首封最早→真连板→10日涨幅，rank_board_stocks_seal）
    下主板/双创各取首位。

    复用单次排序（单一事实源：排序键只此一份），轨内取首位=全序过滤，与「每轨单独
    排序」同构。返回 [(segment, leader), ...]，顺序固定 main→growth（确定性，回归可比）；
    某轨无候选则不出该轨。候选 gain10 全缺的整板块跳过由调用方负责（沿用 2026-10-27
    fail-visible 裁决，本函数不重复判）。
    """
    picked: dict[str, dict] = {}
    for s in rank_board_stocks_seal(candidates):
        seg = segment_of(s.get("code"))
        if seg and seg not in picked:
            picked[seg] = s
    return [(seg, picked[seg]) for seg in ("main", "growth") if seg in picked]


def combo_key(row: dict) -> str:
    """结构组合桶键（与基线脚本一致：streak|boardN|sealTime）。"""
    return (f"streak{streak_bucket(row.get('streak'))}"
            f"|n{board_count_bucket(row.get('boardN'))}"
            f"|{seal_time_bucket(row.get('time'))}")


def _rate(rows: list[dict]) -> tuple[int, int, float | None]:
    n = len(rows)
    cont = sum(1 for r in rows if r.get("continued"))
    return cont, n, (round(cont / n, 4) if n else None)


def group_rates(rows: list[dict], key_fn: Callable[[dict], str]) -> dict[str, dict]:
    """按 key_fn 分桶统计次日连板率（升序键）。"""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[str(key_fn(r))].append(r)
    return {k: {"cont": c, "n": n, "rate": p}
            for k, v in sorted(buckets.items())
            for c, n, p in [_rate(v)]}


def combo_rates(rows: list[dict], min_n: int = 5) -> dict[str, dict]:
    """结构组合桶率（样本 < min_n 的不出，避免给模型 1-2 样本的假高率）。"""
    buckets: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        buckets[combo_key(r)].append(r)
    return {k: {"cont": c, "n": n, "rate": p}
            for k, v in sorted(buckets.items()) if len(v) >= min_n
            for c, n, p in [_rate(v)]}


def summarize_rows(rows: list[dict], min_combo_n: int = 5) -> dict:
    """基线汇总（口径与 scripts/theme_leader_sustain_baseline.py 逐项一致）。"""
    cont, n, rate = _rate(rows)
    return {
        "leaders": n, "continued": cont, "rate": rate,
        "byStreak": group_rates(rows, lambda r: streak_bucket(r.get("streak"))),
        "byBoardCount": group_rates(rows, lambda r: board_count_bucket(r.get("boardN"))),
        "bySealTime": group_rates(rows, lambda r: seal_time_bucket(r.get("time"))),
        "byFollowers": group_rates(rows, lambda r: ladder_bucket(r.get("ladderFollowers"))),
        "byPrevPeers": group_rates(rows, lambda r: prev_peer_bucket(r.get("prevPeers"))),
        "combo": combo_rates(rows, min_combo_n),
    }


# ── 题集（v1 定版，判据冻结：改动必须换代 + 预登记） ──
QUESTIONS_THEME_LEADER = {
    "theme_speculation_depth": {
        "type": "choice",
        "instructions": "仅依据所给证据（题材热度序列、产业树催化正文、题材事件与热度、"
                        "题材新闻 Kword 分布、前瞻日历、板块梯队结构），判断该题材当前的"
                        "**炒作深度/所处阶段**。只判题材层面阶段，不预测个股。判据要点："
                        "事件与新闻的新增密度（热度序列是否断流/见顶）、板块梯队形态"
                        "（首板潮/中军成形/高标分化）、龙头高度与板块家数变化。"
                        "证据不足的判定边界（v6 收紧）：仅当语料未采集，或产业树未映射 + "
                        "题材事件/新闻近 5 日均无痕迹 + 板内解析亦不可用**三层同时成立**"
                        "才判 insufficient。特别地（v12 修订「贫料 ≠ 断流」）："
                        "事件/新闻零痕迹而板块当日仍有涨停 = 「无新增催化的纯资金/情绪驱动」"
                        "信号，**不是证据缺失**，也不得直接等同退潮——产业树正文陈旧、"
                        "新闻供给稀疏属**贫料环境**，此时必须按板块结构定向：板块家数扩张"
                        "或首板潮在场 → **igniting 优先**；板块家数萎缩或龙头断板 → 才可判 "
                        "ebbing；高标孤军高度领先而家数不扩 → climax。不得借 insufficient "
                        "逃避归类。本题判**板块整体**；叙事若为双龙一并列（主板/双创分轨），"
                        "两列均为该板块结构事实。",
        "criteria": {
            "igniting": "启动期：题材由近 1-2 日新事件/新催化点燃，板块以首板为主、"
                        "家数扩张中，尚无连板梯队",
            "fermenting": "发酵期：事件/新闻持续新增（热度序列未见顶回落），2-3 板中军成形，"
                          "板块家数维持或增长",
            "climax": "高潮期：龙头高度显著领先（≥4 板）而板块开始分化——家数回落、"
                      "跟风断板增多、新闻/事件密度见顶回落",
            "ebbing": "退潮期：事件与新闻断流（热度序列连续走低）、板块家数萎缩、"
                      "龙头断板或出现大面",
            "insufficient": "证据不足：仅当语料未采集，或产业树/题材事件·新闻/板内解析"
                            "三层同时无该板块痕迹。事件新闻断流本身是 climax/ebbing 的"
                            "判据信号，不是证据不足",
        },
    },
    "theme_continuation": {
        "type": "choice",
        "instructions": "仅依据所给证据，判断该题材炒作的**延续性**：接下来 1-2 个交易日，"
                        "题材层面（板块整体，不是单指龙头）还能否继续炒作？判据要点："
                        "未来 1-3 日既定事件是否排队（前瞻日历）、题材事件/新闻是否仍在新增、"
                        "催化是否被其他题材分流稀释、板块梯队是否完整。"
                        "证据不足的判定边界（v6 收窄）：与程序门同口径——产业树未映射 + "
                        "事件/新闻无痕 + 板内解析不可用三层同时成立才判 insufficient。"
                        "无新增催化但板块仍活跃 = 存量惯性 → weak_extend；"
                        "分化/退潮信号明确 → ending——零痕迹不是 insufficient 的理由。"
                        "本题判**板块整体**；叙事若为双龙一并列（主板/双创分轨），"
                        "两列均为该板块结构事实。"
                        "引用义务（v12 修订）：判 ending 须在理由中点名至少 2 个判据信号"
                        "（新闻断流/家数萎缩/龙头分歧）在叙事中的对应事实，且**板块家数"
                        "扩张或家数序列不可考时不得判 ending**——只有单一信号时按存量"
                        "惯性归 weak_extend 并降低置信，不得凭单一信号判结束；"
                        "判 strong_extend 的引用源**二选一**：①排队中的既定事件或近 2 日"
                        "新增的题材事件/新闻标题（「个股打标交叉」行的新鲜度/买盘逻辑"
                        "判定可作引用源）；②**结构再点火信号**——当日首板潮（板块梯队形态行）、"
                        "板块家数环比扩张、断板龙一重新上板并带动板内 ≥2 家上板（结构行/"
                        "涨停原因行可作引用源）——贫料环境（语料陈旧/稀疏）不是否定结构"
                        "再点火的理由；叙事中龙一今日未封板（断板反包候选）时，个股层面"
                        "缺同构历史锚应保守，但板块层面结构再点火信号仍可按②引用。"
                        "跨题一致性（v12）：同一叙事的「题材炒作深度」若判 igniting/"
                        "fermenting，本题不得判 ending，除非点名基线/锚行具体数字并给出"
                        "锚外新证据。",
        "criteria": {
            "strong_extend": "强延续：有未落地的既定事件排队、题材事件/新闻持续新增，"
                             "或出现结构再点火（首板潮/家数扩张/断板反包带动板内上板），"
                             "梯队完整，预计板块还能炒 ≥2 个交易日",
            "weak_extend": "弱延续：仅存量情绪惯性，无明显新增催化且无结构再点火信号，"
                          "预计板块炒作 ≤1 个交易日",
            "ending": "临近结束：高潮分化/退潮信号明确（新闻断流+家数萎缩+龙头分歧；"
                      "家数扩张或序列不可考时不得判本档），题材层面随时收束",
            "insufficient": "证据不足：仅当语料未采集或三层证据（产业树/事件·新闻/板内解析）"
                            "同时无痕迹；无催化零痕迹时按存量惯性与分化信号归类",
        },
    },
    "leader_nextday_continue": {
        "type": "choice",
        "instructions": "仅依据所给证据（板块结构、封板质量、题材证据与前瞻事件、同桶历史基准率），"
                        "判断该板块龙头在**次一交易日**继续封板（涨停）的概率落在哪一档？"
                        "只判概率档位，不预测价格、不给出买卖建议。四条硬规则："
                        "①同桶历史基准率是必须先对齐的概率中枢——取叙事「结构基线」行中最细"
                        "同桶（方括号条件最全且已出率，即样本≥8 的那行）；偏离中枢一档以上"
                        "（上调或下调）都必须在理由中点名所依据的基线行具体数字，并给出锚未"
                        "覆盖的新证据（当日新催化、承接突变、封板质量异常等），不得凭感觉移动"
                        "档位；若最细同桶样本不足未出率，以「按连板高度」桶为中枢；"
                        "②题材证据（产业树催化、题材事件/题材新闻、前瞻日历、板内个股解析、"
                        "个股打标交叉行）"
                        "有明确日期与新鲜度时，其权重高于结构特征；"
                        "③关键证据缺失（语料未采集、板块在产业树/题材事件均无可用证据、"
                        "板块结构不可考）必须判 insufficient，不得用结构特征硬填空档；"
                        "④此规则由程序强制：当叙事「题材证据」标注证据缺失（产业树未映射且"
                        "题材事件与板内解析亦无可用证据）时，无论你给出何档，落库一律覆盖为 "
                        "insufficient（原答另存备查）——所以此时请直接选 insufficient，"
                        "不要用结构特征凑档位；⑤若叙事标注待判龙头**今日未封板**（断板反包"
                        "候选），本题=判断其次日**重新上板**的概率：封板质量/封板时间类结构"
                        "判据不适用，改按断板后承接（板内炸板面、昨日仍封数）、板块梯队与"
                        "题材证据判断；未封板龙一通常没有同构历史锚，此时以证据为主，锚缺失"
                        "如实对待、不得编造基准——锚缺失如实对待**不等于**可判 insufficient："
                        "只要叙事中结构基线行（含任一出率桶）、承接行、梯队行、题材证据任一"
                        "在场，就必须按规则①对齐中枢给档，此时锚缺失仅要求降低置信"
                        "（confidence ≤0.6），不得以「无同构历史锚」作为 insufficient 理由；"
                        "⑥若叙事标注分轨（主板/双创），待判龙头为"
                        "其轨内按 10 日涨幅取出的龙一，身位表述以轨内为准，另一轨龙一仅作"
                        "板块结构事实。",
        "criteria": {
            "high_ge65": "高概率 ≥65%：结构位置强（连板高度领先 + 封板早 + 板块家数多）"
                         "且题材有当日/近两日新催化（含题材事件/题材新闻新增），"
                         "或未来 1-2 日有既定事件",
            "mid_45_65": "中等 45%-65%：结构与题材一强一弱，或与同桶历史基准率同档",
            "low_25_45": "偏低 25%-45%：结构位置一般（封板偏晚/板块家数少/跟风薄），"
                         "或题材为老催化且近期无新增",
            "verylow_lt25": "很低 <25%：结构示警（板块家数少 + 封板晚 + 无梯队）"
                            "且题材无催化或已明显退潮",
            "insufficient": "证据不足：关键证据缺失（语料未采集、产业树与题材事件与板内解析均无"
                            "该板块证据、板块结构不可考），不强行归类；未封板场景：结构基线行"
                            "有任一出率桶时不得选本档（v13）",
        },
    },
    "leader_headroom": {
        "type": "choice",
        "instructions": "综合前三题的判断（题材炒作深度、题材延续性、次日续板概率）与该龙头"
                        "在题材内的身位（是否龙一/总龙头、高度领先度、封板质量），判断该龙头"
                        "**还有多少上涨空间**——在当前连板高度之上还能再走几个板。"
                        "注意：这是空间判断，不是次日概率判断——强延续题材的龙一通常仍有空间，"
                        "退潮题材的高标即使次日勉强封板也缺乏空间。硬规则：①关键证据缺失必须判 "
                        "insufficient；②叙事若提供「空间锚」行（历史同结构龙头自当日高度的"
                        "再走≥1板率/≥2板率/中位分布），它是必须先对的基准——若你的理由仅为"
                        "「身位强/题材强」这类与锚同源的结构特征，应选与锚一致的档位；无论上调"
                        "还是下调，偏离锚的档位都必须在理由中引用锚行的具体数字，并给出锚未"
                        "覆盖的新证据（当日新催化、身位显著领先、封板质量显著占优等）；"
                        "③默认起判档（按龙头当日连板高度）：1-3 板 → peak 起判、4 板及以上 → "
                        "space_1 起判——依据=历史同高度再走≥1板率（1-3 板桶仅一到三成、4+ 桶"
                        "约三成七）与主线核心退潮日照续的分层杀伤证据，非桶众数；连板高度不可算"
                        "时（含待判龙头今日未封板的断板反包候选）默认档按「空间锚」最细出率桶"
                        "起判（无按高度细分则用总体行，如总体再走≥1板率不足三成 → peak 侧"
                        "起判）；锚行同样必须先对齐，偏离仍须按 ② 点名锚行数字并给锚外新证据；"
                        "锚行整体缺席（叙事无空间锚行）才允许按证据自判，且此时若为未封板场景"
                        " confidence ≤0.6；默认档只是起点，偏离仍须按 ② 引用锚行"
                        "数字并给新证据；④跨题一致性（v12）：同一叙事的「题材炒作深度」若判 "
                        "igniting/fermenting，本题默认不得选 peak，除非点名锚行数字并给锚外"
                        "新证据；与延续题 strong_extend 明显矛盾时同样须引用锚行数字说明；"
                        "⑤若叙事标注分轨（主板/双创），待判龙头为其轨内龙一，空间判断以轨内"
                        "身位为准（双创 20cm 生态与主板 10cm 不同，另一轨龙一仅作板块结构"
                        "事实）。",
        "criteria": {
            "space_2plus": "仍有 ≥2 板空间：题材强延续（发酵期）且该龙头是身位无可替代的"
                           "龙一/总龙头，梯队与催化双支撑",
            "space_1": "还有约 1 板空间：题材尚可延续或龙头身位尚可，但催化新鲜度、"
                       "梯队完整性有一项已走弱（锚行读数参照：历史同高度再走≥1板率"
                       "三成上下）",
            "peak": "空间已尽：题材退潮/临近结束，或龙头身位被替代/催化断流，"
                    "当前高度大概率就是顶部（锚行读数参照：同高度再走≥1板率不足三成）",
            "insufficient": "证据不足：仅当语料未采集或三层证据（产业树/事件·新闻/板内解析）"
                            "同时无痕迹；叙事含空间锚行（有率值）时不得选本档（v13）",
        },
    },
}
QUESTION_SET_HASH_THEME_LEADER = _questions_hash(QUESTIONS_THEME_LEADER)

# 承接题集的最小单位（与驱动链同规：题目原文不改写）——本层暂不做承接（首版只判独立基线）。
THEME_LEADER_KEYS = tuple(QUESTIONS_THEME_LEADER)

# 档位中值（**仅供离线评估**：把模型返回的档位概率分布折算成单点概率算 Brier/校准；
# 不参与叙事、不下发给模型，避免把"我们自己的解读"混进题面）。
# `insufficient` 不给中值：评估时单独统计其质量并在其余四档上归一化，不拿"不足"当低概率。
CONTINUE_BUCKET_MIDPOINTS = {
    "high_ge65": 0.75,
    "mid_45_65": 0.55,
    "low_25_45": 0.35,
    "verylow_lt25": 0.125,
}


# 确定性「证据缺失」门（v2 引入，v3 收窄触发条件；纯函数，无 IO）。
# 触发只用**结构化**的缺失标志（`theme_event_digest` 返回的 `evidenceMissing`），不从叙事文字反推。
# v3 口径：`evidenceMissing` = L3（产业树/日历）与 L2（板内解析/早报段落）**均无**可用证据。
GATE_REASON_LABELS = {
    "corpus_not_collected": "题材语料未采集",
    # v2 历史档（10-08~10-22 落库）沿用旧名，保留标签供前端/审计回读：
    "board_unmapped": "板块未映射（产业树无同名/包含节点，不代表无催化）",
    "industry_tree_unmapped": "产业树未映射且题材事件/板内解析均无可用证据",
    "no_content_no_event": "已映射但正文为空且无可用事件",
}


def apply_evidence_gate(answers: Any, evidence: Any,
                        keys: tuple[str, ...] | None = None) -> tuple[Any, dict]:
    """证据缺失 → **全部判定题**强制 insufficient（原答原样存 gate 元数据）。

    v1 单日 pilot 实测缺口：未映射板块的催化题判了 insufficient，但同一份证据下
    概率题仍给 0.34/0.34/0.26/0.18——规则③只写在题面，靠模型自觉。v2 改为代码强制
    （仅概率题）；v5 起题集扩为四题（深度/延续性/概率/空间），**无证据时四题全部门**——
    无题材证据却判「发酵期/强延续/空间≥2板」与「无证据却给 0.34」是同一类失效。
    v12 A2 拆题（预登记 §2.3）：`keys` 给出时只门该子集（板块级 doc 只有深度/延续两题，
    个股级 doc 只有续板/空间两题），缺省仍全题（旧行为不变）。
    """
    ev = evidence if isinstance(evidence, dict) else {}
    gate: dict[str, Any] = {"applied": False, "reason": None}
    if not isinstance(answers, dict) or not ev.get("evidenceMissing"):
        return answers, gate
    reason = str(ev.get("evidenceMissingReason") or "unknown")
    prev_prob = answers.get("leader_nextday_continue") if isinstance(
        answers.get("leader_nextday_continue"), dict) else {}
    gate.update({"applied": True, "reason": reason,
                 "label": GATE_REASON_LABELS.get(reason, reason),
                 "modelChoice": prev_prob.get("choice"),
                 "modelProbabilities": prev_prob.get("probabilities"),
                 "forcedKeys": []})
    out = dict(answers)
    for key in (keys or tuple(QUESTIONS_THEME_LEADER)):
        prev = out.get(key) if isinstance(out.get(key), dict) else {}
        if prev.get("choice") == "insufficient":
            continue                      # 模型已自判不足，无须覆盖
        forced = {"type": "choice", "choice": "insufficient", "confidence": 1.0,
                  "gateReason": reason}
        if key == "leader_nextday_continue":
            forced["probabilities"] = {"insufficient": 1.0}
        out[key] = forced
        gate["forcedKeys"].append(key)
    return out, gate


def continue_point_estimate(probabilities: Any) -> tuple[float | None, float]:
    """档位概率分布 → (单点概率, insufficient 质量)。

    四档按其给出的概率加权求期望（不是取 argmax 档中值），其余四档质量归一化；
    归一化后质量为 0（全判 insufficient）时返回 (None, mass) —— 不编造概率。
    """
    probs = probabilities if isinstance(probabilities, dict) else {}
    mass = float(probs.get("insufficient") or 0.0)
    parts = {k: float(probs.get(k) or 0.0) for k in CONTINUE_BUCKET_MIDPOINTS}
    total = sum(parts.values())
    if total <= 0:
        return None, mass
    return sum(v * CONTINUE_BUCKET_MIDPOINTS[k] for k, v in parts.items()) / total, mass


# ── 叙事拼装（纯字符串，IO 全在 operations 层） ──
def baseline_line(rows: list[dict], row: dict, min_combo_n: int = 5) -> str:
    """该龙头所在结构桶的历史基准率行（组合桶样本不足时逐级回退，全部标注样本量）。

    2026-10-24c：补透出 `bySealTime`/`byFollowers`/`byPrevPeers` 三组单维桶率（此前
    `summarize_rows` 已算、仅落审计不喂模型）。verylow 判据「板块家数少+封板晚+无梯队」
    三维度现在语料都有对应率；各维独立出率（组合桶样本不足时不再整体丢失封板时间维度）。
    回退顺序：组合桶 → 连板高度 → 板块家数 → 封板时间 → 跟风梯队 → 昨日承接 → 总体；
    任一档样本 < min_combo_n 都明示样本量，让模型知道这条基准率的可信度（不隐藏小样本）。
    """
    combo = combo_rates(rows, min_combo_n).get(combo_key(row))
    parts: list[str] = []
    if combo:
        parts.append(f"同桶[{combo_key(row)}] 历史次日连板率 {combo['rate']:.1%}（{combo['n']} 样本）")
    else:
        parts.append(f"同桶[{combo_key(row)}] 样本不足（<{min_combo_n}），不出率")
    sk = streak_bucket(row.get("streak"))
    sb = group_rates(rows, lambda r: streak_bucket(r.get("streak"))).get(sk)
    if sb:
        parts.append(f"按连板高度[{sk}] {sb['rate']:.1%}（{sb['n']} 样本）")
    ck = board_count_bucket(row.get("boardN"))
    cb = group_rates(rows, lambda r: board_count_bucket(r.get("boardN"))).get(ck)
    if cb:
        parts.append(f"按板块家数[{ck}] {cb['rate']:.1%}（{cb['n']} 样本）")
    tk = seal_time_bucket(row.get("time"))
    tb = group_rates(rows, lambda r: seal_time_bucket(r.get("time"))).get(tk)
    if tb and tk != "unknown":
        parts.append(f"按封板时间[{tk}] {tb['rate']:.1%}（{tb['n']} 样本）")
    fk = ladder_bucket(row.get("ladderFollowers"))
    fb = group_rates(rows, lambda r: ladder_bucket(r.get("ladderFollowers"))).get(fk)
    if fb and fk != "unknown":
        parts.append(f"按跟风梯队[{fk}] {fb['rate']:.1%}（{fb['n']} 样本）")
    pk = prev_peer_bucket(row.get("prevPeers"))
    pb = group_rates(rows, lambda r: prev_peer_bucket(r.get("prevPeers"))).get(pk)
    if pb and pk != "prev_unknown":
        parts.append(f"按昨日承接[{pk}] {pb['rate']:.1%}（{pb['n']} 样本）")
    cont, n, rate = _rate(rows)
    if n:
        parts.append(f"总体 {rate:.1%}（{n} 样本）")
    return "结构基线：" + "；".join(parts)


# ── 空间题历史锚（Q1，2026-10-24b 置信度归因后加）────────────────────────────
# 归因（v6 两日 14 只实测）：空间题 conf 均值 0.435 全场最差且**无任何历史锚**——续板题有
# 同桶基准率，空间题全凭模型相对判断。「连板周期」= 同一 code 在 date 相邻交易日且
# streak 严格 +1 的连续段；自当日高度的剩余板数 = 段尾 streak − 当日 streak。
# 右删失：段尾样本次日仍封板（continued=True）但样本流断（让位龙头/THS 缺失），周期未
# 确认终结 → 整段剔除并披露，不把未知终点当 0 剩余。streak None（真连板不可算）不进锚。


def _leader_cycles(rows: list[dict]) -> tuple[list[tuple[dict, int]], int]:
    """历史龙头-日样本 → [(样本行, 自当日高度剩余板数), ...] + 右删失样本数。"""
    dates_axis = sorted({str(r.get("date")) for r in rows if r.get("date")})
    nxt_of = {d: dates_axis[i + 1] for i, d in enumerate(dates_axis[:-1])}
    by_code: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        code = str(r.get("code") or "")
        if code and isinstance(r.get("streak"), int):
            by_code[code].append(r)
    kept: list[tuple[dict, int]] = []
    censored = 0

    def _close(seg: list[dict]) -> None:
        nonlocal censored
        if not seg:
            return
        if seg[-1].get("continued") is not False:   # 次日仍封/结局不可考 = 周期未确认终结
            censored += len(seg)
            return
        end_streak = seg[-1]["streak"]
        for s in seg:
            kept.append((s, end_streak - int(s["streak"])))

    for samples in by_code.values():
        samples.sort(key=lambda r: str(r.get("date")))
        seg: list[dict] = []
        for s in samples:
            if (seg and str(s.get("date")) == nxt_of.get(str(seg[-1].get("date")))
                    and s.get("streak") == seg[-1]["streak"] + 1):
                seg.append(s)
            else:
                _close(seg)
                seg = [s]
        _close(seg)
    return kept, censored


def headroom_anchor_line(rows: list[dict], row: dict, min_combo_n: int = 8) -> str | None:
    """空间题历史锚行（与 baseline_line 同构的桶回退；样本量与删失全披露）。

    历史 rows 为空 / 无可用周期 → None（叙事不出行：没有锚时题面锚规则不触发，
    模型自行判断——fail-visible，不编造基准）。
    2026-10-26a 每档基率化：此前每档只给「平均再走 X 板」（实测全 <1 板）+ ≥2 板率，
    与档位语义（space_1≈1 板/peak=顶部）粒度错配——10-23 八龙头全 peak 塌缩归因之一。
    改为每档给「再走≥1板率/≥2板率/中位再走/均值/样本量」：率值口径与档位判定直接对齐
    （≥1板率低→peak 侧，≥1板率高→space_侧），均值降为参考量；题面判据零改动。
    """
    from statistics import median

    kept, censored = _leader_cycles(rows)
    if not kept:
        return None

    def _stat(pairs: list[tuple[dict, int]]) -> str:
        vals = [float(v) for _, v in pairs]
        n = len(vals)
        return (f"再走≥1板率 {sum(1 for v in vals if v >= 1) / n:.1%} · ≥2板率 "
                f"{sum(1 for v in vals if v >= 2) / n:.1%} · 中位再走 {median(vals):.1f} 板"
                f"（均值 {sum(vals) / n:.1f}，{n} 样本）")

    parts: list[str] = []
    ck = combo_key(row)
    combo_pairs = [p for p in kept if combo_key(p[0]) == ck]
    if len(combo_pairs) >= min_combo_n:
        parts.append(f"同桶[{ck}] {_stat(combo_pairs)}")
    else:
        parts.append(f"同桶[{ck}] 样本不足（<{min_combo_n}），不出锚")
    sk = streak_bucket(row.get("streak"))
    streak_pairs = [p for p in kept if streak_bucket(p[0].get("streak")) == sk]
    if len(streak_pairs) >= min_combo_n:
        parts.append(f"按连板高度[{sk}] {_stat(streak_pairs)}")
    cen = (f"；剔右删失样本 {censored} 个" if censored else "")
    # 2026-10-30d 语料精简：再走≥1板率定义在题面 ③ 已给，叙事侧不重复
    return ("空间锚："
            + "；".join(parts) + f"；总体 {_stat(kept)}{cen}")


def _prev_history_txt(prev_peers: Any, prev_board_n: Any, prev_total: Any,
                      prev_still: Any, history: list[tuple[str, int]] | None) -> tuple[str, str]:
    """昨日承接与家数序列两段文本（structure_line / structure_line_dual 共用，禁第二套）。"""
    still_txt = (f"今日仍封 {prev_still} 只" if isinstance(prev_still, int)
                 else (f"今日仍封 {prev_board_n} 只" if isinstance(prev_board_n, int)
                       else "今日仍封不可考"))
    if prev_peers is None:
        prev_txt = "昨日同板块不可考"
    elif isinstance(prev_still, int) and prev_total is not None:
        # 2026-10-30d 语料精简：断板 = 两数之差可推导，不再复述（断板不可算分支保留）
        prev_txt = f"昨日该板块封板 {prev_total} 只，{still_txt}"
    elif prev_total is None:
        prev_txt = f"昨日该板块封板总数不可考（{still_txt}）"
    else:
        duan = prev_total - prev_board_n if isinstance(prev_board_n, int) else None
        duan_txt = (f"断板 {duan}" if duan is not None and duan >= 0 else "断板不可算")
        prev_txt = f"昨日该板块封板 {prev_total} 只，{still_txt}（{duan_txt}）"
    hist_txt = ""
    # 2026-10-30d 语料精简：序列 <3 日时与昨日承接行几乎全重叠，不出行（≥3 日才列）
    if history and len(history) >= 3:
        seq = " · ".join(f"{d[5:]} {n}" for d, n in history)
        hist_txt = f"；近 {len(history)} 日该板块封板家数：{seq}"
    elif history is not None and not history:
        hist_txt = "；近数日家数序列不可考"
    return prev_txt, hist_txt


def _leader_brief(leader: dict, seg: str | None = None) -> str:
    """单个龙一简报（v12 双龙一结构行用）：轨别前缀 + 封板/未封板分情形 + 10日涨幅身位。"""
    seg_cn = (SEGMENT_CN.get(seg, seg or "") + "龙一") if seg else "龙一"
    gain = leader.get("gain10")
    gain_txt = (f"，10 日涨幅 {gain:+.1f}%" if isinstance(gain, (int, float))
                else "，10 日涨幅不可考")
    if leader.get("leaderSealedToday") is False:
        return (f"{seg_cn} {leader.get('name')}（{leader.get('code')}）今日未封板"
                f"（断板反包候选{gain_txt}）")
    streak = leader.get("streak")
    streak_txt = f"{streak} 连板" if streak else "连板高度不可算"
    time_txt = str(leader.get("time") or "时间不可考")
    return f"{seg_cn} {leader.get('name')}（{leader.get('code')}）{streak_txt}，首封 {time_txt}{gain_txt}"


def structure_line_dual(*, board: str, board_n: int, leader_rows: list[dict],
                        prev_board_n: Any = None, prev_peers: Any = None,
                        prev_total: Any = None, prev_still: Any = None,
                        history: list[tuple[str, int]] | None = None) -> str:
    """板块级双龙一并列结构行（v12 A2 拆题：深度/延续题每板块一次，预登记 §2.3/§4.2）。

    `leader_rows` = 该板块当日 ≤2 条分轨龙一事实行（`day_leader_rows` space_mode 产出，
    含 segment/gain10/leaderSealedToday），顺序 main→growth；行内轨别自描述。昨日承接/
    家数序列与单龙一结构行同一实现（`_prev_history_txt`，单一事实源）。跟随梯队/炸板面
    属板级事实，由梯队行/炸板面行承载，本行不重复。
    """
    if not leader_rows:
        raise ValueError("structure_line_dual: leader_rows 不能为空（无龙一不应到这）")
    briefs = "；".join(_leader_brief(r, r.get("segment")) for r in leader_rows)
    prev_txt, hist_txt = _prev_history_txt(prev_peers, prev_board_n, prev_total,
                                           prev_still, history)
    return (f"板块「{board}」今日封板 {board_n} 家；{briefs}；"
            f"{prev_txt}{hist_txt}")


# ── KPL 直播播报行（AMMO 2026-10-28a G1，预登记 §4.3） ──

def _lz_brief(lz_info: str, max_items: int = 4) -> str:
    """KPL LZInfo 梯队串 → 「大业股份(6连板)、正强股份(首板)」简报（G4 交叉披露）。"""
    parts = []
    for seg in str(lz_info or "").split(";"):
        f = [x.strip() for x in seg.split(",")]
        if len(f) >= 3 and f[1] and f[2]:
            parts.append(f"{f[1]}({f[2]})")
        if len(parts) >= max_items:
            break
    return "、".join(parts)


def rank_sentinel_warnings(rank_rows: list[dict] | None,
                           zt_rows: list[dict] | None) -> list[str]:
    """层1 raw[8]（主力净额）程序化哨兵（AMMO 2026-10-28a §9.6 处置）。

    raw[8] 已于 2026-10-29 App 同屏定档（data/backups/kpl-raw8-verify-20261029/），
    本哨兵转为**日常漂移监视器**：上游改列位/口径漂移时越界告警（fail-visible），由
    `plate_series_line` 拼入层1 段尾——只加披露、不改判据、不丢数据：

    - **量级**：|main_net| > amount（主力净额是成交额子集）→ 列位错挂/口径漂移信号；
    - **方向**：n≥4 且 main_net 与 pct 同号率 <0.5 → 净额方向与涨幅大面积背离；
      （全同号不告警：5~6 日窗内强趋势板块全同号属正常，不足以定性）
    - **秩相关**：层1 strength 与层2 QD 在 ≥3 个共同记录日 Spearman 秩相关 <0 →
      两条强度口径互证失败。

    字段缺失/样本不足的行如实跳过（不插值、不伪装）；无越界返回 []。
    """
    rows = [r for r in (rank_rows or []) if isinstance(r, dict)]
    zts = [z for z in (zt_rows or []) if isinstance(z, dict)]
    warns: list[str] = []

    def _f(v: Any) -> float | None:
        return float(v) if isinstance(v, (int, float)) else None

    # ① 量级：|净额| > 成交额
    bad_mag = [r for r in rows
               if (mn := _f(r.get("main_net"))) is not None
               and (amt := _f(r.get("amount"))) is not None and amt > 0
               and abs(mn) > amt]
    if bad_mag:
        warns.append(f"净额>成交额 ×{len(bad_mag)} 日")

    # ② 方向：净额与涨幅同号率
    pairs = [(mn, pc) for r in rows
             if (mn := _f(r.get("main_net"))) is not None and mn != 0
             and (pc := _f(r.get("pct"))) is not None and pc != 0]
    if len(pairs) >= 4:
        same = sum(1 for mn, pc in pairs if (mn > 0) == (pc > 0))
        if same / len(pairs) < 0.5:
            warns.append(f"净额与涨幅同号率 {same}/{len(pairs)} <0.5")

    # ③ 秩相关：层1 strength × 层2 QD（共同记录日）
    by_date = {str(z.get("date") or ""): z for z in zts}
    pair_sq = [(s, q) for r in rows
               if (s := _f(r.get("strength"))) is not None
               and (q := _f(by_date.get(str(r.get("date") or ""),
                                            {}).get("qd"))) is not None]
    if len(pair_sq) >= 3:
        def _ranks(vals: list[float]) -> list[float]:
            order = sorted(range(len(vals)), key=lambda i: vals[i])
            ranks = [0.0] * len(vals)
            i = 0
            while i < len(order):
                j = i
                while j + 1 < len(order) and vals[order[j + 1]] == vals[order[i]]:
                    j += 1
                avg = (i + j) / 2 + 1
                for k in range(i, j + 1):
                    ranks[order[k]] = avg
                i = j + 1
            return ranks

        rs, rq = _ranks([p[0] for p in pair_sq]), _ranks([p[1] for p in pair_sq])
        n = len(pair_sq)
        ds = [a - b for a, b in zip(rs, rq)]
        rho = 1 - 6 * sum(d * d for d in ds) / (n * (n * n - 1))
        if rho < 0:
            warns.append(f"层1强度×层2QD 秩相关 {rho:+.2f}<0（{n} 日）")
    return warns


def plate_series_line(rank_rows: list[dict] | None, zt_rows: list[dict] | None, *,
                      plate_name: str, label_date: str, window_days: int = 5,
                      zt_fetch_error: str | None = None,
                      trading_days: int | None = None,
                      window_first_date: str | None = None) -> str | None:
    """板块序列行（P1-1，G2/G3）：KPL 801xxx 稳定 ID 锚，双段口径各自如实标注。

    - **层 1 连续段**：近 N 个交易日（韭研日轴）排名/强度/主力净额（raw[8]，**推断口径
      待 App 同屏核对**，行内显式标注）——连续无缺口；
    - **层 2 涨停家段**：ZTNum 仅记录有涨停家/爆发日，记录间缺口**不能解读为零涨停**
      （2026-10-29 反查实证：缺口日 HisDaBanList 有该板块涨停股，上游缺记），只列记录
      日并显式标注该限制与窗口缺口率（`trading_days` 给出时）——堵死
      「无行=零涨停」的伪趋势误读（§4.0 禁伪装缺口）；
    - 尾附当日 LZInfo 梯队串（G4：KPL 预计算，交叉披露**不替换自算口径**）。
    `window_first_date`（review P1-1 修复，2026-10-29）：声明交易窗口首日时，层2 记录先按
    [首日, 标注日] 过滤再计数/展示——否则展示切片（最近 N 条）可能把窗口内首日挤掉
    （无缺口说成有缺口）或把窗外记录算作在场（不在场说成在场），两个方向都违 §4.0；
    且窗口声明后即使窗内 0 条记录也出层2 段（「仅0条记录」本身是强缺口信号，不得缺席）。
    缺省 None = 旧口径（≤标注日最近 window_days 条，不变）。
    rank_rows 与 zt_rows 均空且未声明窗口 → None（调用方不出行；匹配状态由板块强度行披露）。
    """
    rank_rows = [r for r in (rank_rows or [])
                 if str(r.get("date") or "") <= str(label_date)][-window_days:]
    zt_rows = [r for r in (zt_rows or [])
               if str(r.get("date") or "") <= str(label_date)]
    window_declared = bool(window_first_date)
    if window_declared:
        zt_rows = [r for r in zt_rows
                   if str(window_first_date) <= str(r.get("date") or "")]
    else:
        zt_rows = zt_rows[-window_days:]
    if not rank_rows and not zt_rows and not zt_fetch_error and not window_declared:
        return None
    if not rank_rows and not zt_rows and not window_declared:
        # P2-11（review）：层2 拉取失败不得静默缺席（§4.0）——失败行显式披露
        return (f"板块序列 {plate_name}："
                f"层1/层2 均无记录；层2 涨停梯队历史拉取失败：{zt_fetch_error}")
    head = f"板块序列 {plate_name}："
    parts: list[str] = []
    if rank_rows:
        segs = []
        for r in rank_rows:
            qd = r.get("strength")
            mn = r.get("main_net")
            seg = f"{str(r['date'])[5:]} 强度{qd if isinstance(qd, (int, float)) else '?'}"
            if isinstance(mn, (int, float)):
                seg += f" 净额{mn / 1e8:+.1f}亿"
            else:
                seg += " 净额?"
            segs.append(seg)
        parts.append(f"近{len(segs)}交易日强度/净额：" + "；".join(segs))
        sentinel = rank_sentinel_warnings(rank_rows, zt_rows)
        if sentinel:
            # §9.6 处置：raw[8] 口径哨兵越界 → 行内显式告警（fail-visible），不静默
            parts.append("口径哨兵告警：" + "；".join(sentinel))
    if zt_rows or window_declared:
        segs = [f"{str(r['date'])[5:]} 家{r['zt_num'] if r.get('zt_num') is not None else '?'}"
                for r in zt_rows]
        head_txt = "板块涨停家："
        if not zt_rows:
            # 窗口声明后 0 条记录：缺席本身是强缺口信号，显式出段（§4.0），不静默无层2
            parts.append(head_txt + "窗口内无记录")
        else:
            parts.append(head_txt + "；".join(segs))
    if zt_rows:
        last = zt_rows[-1]
        lz = _lz_brief(last.get("lz_info") or "")
        if lz:
            # P1-3（review）：层2 仅记录有涨停家日，最新记录日≠标注日常见——
            # 不得把昨日/更早的梯队串标成「当日」
            day_txt = ("当日" if str(last.get("date")) == str(label_date)
                       else f"{str(last.get('date'))[5:]} 最近记录日 ")
            parts.append(f"{day_txt}梯队串：{lz}")
    return head + "；".join(parts)


def kpl_live_line(entries: list[dict] | None, *, board: str, total: int = 0,
                  window: str = "", unavailable: str | None = None,
                  clip_chars: int = 120, max_items: int = 3) -> str:
    """KPL 直播播报行（G1，用户裁决接入）：直播解说流按板块过滤后的原料行。

    `entries` = [{time, comment}]（时间升序，由调用方过滤拼装）；`total` = 直播窗口内
    总条数；`window` = 窗口文本（如「14:21~15:00」）；`unavailable` 给出时整行降级
    （fail-visible：实时流不可回放/接口异常），不伪装成「无播报」。
    大模型自动生成尾注由调用方剥离；本行只渲染，不做匹配（匹配在 operations 层，
    复用 digest 关键词口径）。
    """
    head = f"KPL直播播报（"
    if window:
        head += f"窗口 {window}"
    head += f"{'，' if window else ''}全窗 {total} 条）"
    if unavailable:
        return f"KPL直播播报：不可用，{unavailable}"
    if not entries:
        return f"{head}：当日无「{board}」相关播报"
    parts = []
    for e in entries[:max_items]:
        c = re.sub(r"\s+", " ", str(e.get("comment") or "")).strip()
        if len(c) > clip_chars:
            c = c[:clip_chars] + f"…[截断，原文 {len(c)} 字]"
        parts.append(f"{e.get('time') or '时间不可考'} {c}")
    more = len(entries) - max_items
    tail = f"（另 {more} 条略）" if more > 0 else ""
    return head + "：" + "；".join(parts) + tail


def structure_line(*, board: str, board_n: int, leader: dict, followers_ge_ladder: int,
                   prev_board_n: int | None, prev_peers: int | None,
                   prev_total: int | None = None,
                   prev_still: int | None = None,
                   history: list[tuple[str, int]] | None = None,
                   leader_sealed_today: bool | None = None,
                   gain10: float | None = None) -> str:
    """该板块当日结构事实行（不含预测）。

    `history`（S1，2026-10-24b）= 近 5 日 (date, boardN) 序列：深度/延续题判据
    「家数扩张中/萎缩」此前只有今日/昨日两点，序列才看得出形状。缺口日如实不列。
    `prev_total`（2026-10-24c）= 昨日该板块封板总数：此前叙事把 `prev_board_n`（语义=
    昨日封板且今日仍封）误写成「昨日该板块封板 N 只」，断板数被吞——本版修正口径，
    断板 = prev_total − prev_board_n 显式给出；prev_total 不可考（板块改名/昨日池缺失）
    时如实写不可考，不拿仍封数冒充总数。
    `prev_still`（2026-10-24d）= 昨日**同名板块**封板股中今日仍封数，断板 = prev_total −
    prev_still 按它算（恒 ≥0）——2026-10-24 review 处置：prev_board_n 是今日成员交集，
    含昨日他板块迁入股，迁移场景减出负数甚至「昨日封 0 仍封 2」自相矛盾；prev_still
    缺席（手造/旧形状行）时退回 prev_board_n 口径，差值为负则不出断板数只说不可算。
    `leader_sealed_today=False`（2026-10-27 空间龙一规则，v10 题面配套）= 待判龙一当日
    未封板（断板反包候选）——显式标注替代「连板高度不可算/时间不可考」的哑谜，并给
    10 日涨幅身位（排序依据）；模型按 v10 题面⑤分情形判「重新上板概率」。
    """
    unsealed = leader_sealed_today is False
    if unsealed:
        leader_txt = f"待判龙一 {leader.get('name')}（{leader.get('code')}）今日未封板（断板反包候选"
        if gain10 is not None:
            leader_txt += f"，10 日涨幅 {gain10:+.1f}%"
        leader_txt += "）"
    else:
        streak = leader.get("streak")
        streak_txt = f"{streak} 连板" if streak else "连板高度不可算"
        time_txt = str(leader.get("time") or "时间不可考")
        leader_txt = (f"龙头 {leader.get('name')}（{leader.get('code')}）"
                      f"{streak_txt}，首封 {time_txt}")
    prev_txt, hist_txt = _prev_history_txt(prev_peers, prev_board_n, prev_total,
                                           prev_still, history)
    follow_txt = (f"板块内真连板≥{max(1, ((leader.get('streak') or 1)) - 1)} 的跟风 "
                  f"{followers_ge_ladder} 家"
                  if isinstance(followers_ge_ladder, int)
                  else "跟风梯队不可算")
    return (f"板块「{board}」今日封板 {board_n} 家；{leader_txt}；{follow_txt}；"
            f"{prev_txt}{hist_txt}")


def board_ladder_line(row: dict) -> str | None:
    """板内梯队形态行（2026-10-24c）：首板潮/中军成形/高标分化直接可读。

    深度题 climax 判据点名「板块梯队形态（首板潮/中军成形/高标分化）」「龙头高度显著
    领先」，此前语料只有封板总数与跟风数两点。`ladderShape` 缺席（旧代行/极端缺失）→
    None 不出行；次高连板 None=板内无其它可算真连板（孤军），如实写不可考。
    """
    shape = row.get("ladderShape")
    if not isinstance(shape, dict):
        return None
    seg = (f"板块梯队形态：首板 {shape.get('first', 0)} 家 / 2板 {shape.get('two', 0)} 家 / "
           f"3板+ {shape.get('threePlus', 0)} 家")
    unk = shape.get("unknown", 0)
    if unk:
        seg += f"；另有 {unk} 只连板高度不可算"
    leader_streak = row.get("streak")
    second = row.get("secondStreak")
    if isinstance(leader_streak, int) and isinstance(second, int):
        seg += f"；龙头 {leader_streak} 板，次高 {second} 板（领先 +{leader_streak - second}）"
    elif isinstance(leader_streak, int):
        seg += f"；龙头 {leader_streak} 板，次高 不可算"
    else:
        seg += "；龙头连板高度不可算"
    return seg


def board_zhaban_line(row: dict) -> str | None:
    """板内炸板面行（2026-10-24c）：分化/退潮的板内证据。

    climax 判据「跟风断板增多」、ebbing「龙头断板或出现大面」此前只有全市场炸板率，
    板内触板未封（韭研曾触板−THS炸板二分同口径，剔 ST/北交所）缺席。昨日数不可考
    （昨日池缺失/板块改名）时只出今日，如实不列对比。
    """
    z = row.get("zhabanN")
    if not isinstance(z, int):
        return None
    seg = f"板内炸板面：今日触板未封 {z} 家"
    pz = row.get("prevZhabanN")
    if isinstance(pz, int):
        seg += f"（昨日 {pz} 家）"
    return seg


# ── 打标交叉行（AMMO 2026-10-27b，用户批准；预登记 §22） ──
# 枚举短名（与 jev_driver_ammo 判据中文名对齐，压缩为一词便于行内并列）。
DRIVER_LABEL_CN = {
    "policy": "政策", "order_earnings": "订单业绩", "product_event": "产品事件",
    "ma_restructure": "重组并购", "industry_cycle": "行业周期",
    "capital_flow": "资金接力", "concept_stretch": "蹭概念",
    "insufficient_evidence": "信息不足",
}
DRIVER_DEPTH_CN = {
    "core_main_business": "核心主业", "new_business_scaling": "新业务放量",
    "new_business_early": "新业务早期", "equity_or_affiliate": "股权关联",
    "concept_assembly": "概念组装", "insufficient_evidence": "信息不足",
}
DRIVER_FRESHNESS_CN = {
    "fresh_catalyst": "新催化（≤2 交易日）", "continuing": "老催化续命",
    "none": "无明确催化", "unclear": "日期不可考",
}
DRIVER_BUYSIDE_CN = {
    "independent_catalyst": "自身独立催化", "sector_follow": "板块联动跟随",
    "high_board_relay": "高位卡位/情绪接力", "pure_sentiment": "纯情绪修复",
    "insufficient": "信息不足",
}
DRIVER_CROSS_NONE_LINE = "个股打标交叉：无当日个股打标记录"
# 承接披露映射（打标链 carriedQuestionKeys 题键 → 交叉行轴名）：
# 解析正文与前一日逐字相同时打标链不重问（carriedFrom=前一日），交叉行必须如实标注
# 「承接判定」——新鲜度等轴是昨日判断，不是当日重问（防模型把承接值当当日新鲜证据）。
DRIVER_CARRY_AXIS_CN = {
    "driver_type": "驱动类别", "catalyst_depth": "催化深度",
    "catalyst_freshness": "新鲜度", "buy_side_logic": "买盘逻辑",
}


def _top2(probabilities: Any, cn: dict[str, str]) -> str:
    """top-2 枚举短名+整数百分比并列；逃生桶（insufficient 系）不进排名，为空返回空串
    （调用方兜底用已选枚举值，全缺「不可考」，不编 0）。两档比值 ≥0.9 标「近并列」——
    近并列本身是信息（判定不稳），必须披露。"""
    if not isinstance(probabilities, dict):
        return ""
    items = [(cn.get(str(k), str(k)), float(v)) for k, v in probabilities.items()
             if isinstance(v, (int, float)) and v > 0 and k not in ("insufficient_evidence", "insufficient")]
    items.sort(key=lambda kv: -kv[1])
    items = items[:2]
    if not items:
        return ""
    tie = len(items) == 2 and items[0][1] > 0 and items[1][1] / items[0][1] >= 0.9
    seg = "/".join(f"{name}{v:.0%}" for name, v in items)
    return f"{seg}（近并列）" if tie else seg


def _enum_cn(value: Any, cn: dict[str, str]) -> str:
    if not value:
        return "不可考"
    return cn.get(str(value), str(value))


def driver_cross_line(label_doc: dict | None) -> str:
    """个股打标交叉行（AMMO 2026-10-27b）：join 打标链当日该股判定，零调用纯原料。

    行内自描述口径（模型每次都是第一次见「打标交叉」这个词）：另一条打标链对该公司
    当日涨停的机器判定，供交叉参考；四轴=驱动类别 top-2/催化深度/新鲜度/买盘逻辑，
    枚举译名+概率并列。槽位显式（final=收盘槽、midday=午盘槽）；打标链题集版本一并
    披露（v3.1/v4.0 校准代际不同）。label_doc=None → fail-visible 缺席行（不伪装成
    「无催化」等任何方向性结论）。
    """
    if not label_doc:
        return DRIVER_CROSS_NONE_LINE
    slot = str(label_doc.get("labelSlot") or "")
    slot_cn = {"final": "收盘槽", "midday": "午盘槽"}.get(slot, slot or "槽位不可考")
    qs = str(label_doc.get("questionSetVersion") or "版本不可考")
    head = f"个股打标交叉（{slot_cn}）："
    # 驱动类别概率真身=driverProbabilities（labelProbabilities 为 API 层旧别名，兜底旧档）
    label_seg = _top2(label_doc.get("driverProbabilities")
                      or label_doc.get("labelProbabilities"), DRIVER_LABEL_CN) \
        or _enum_cn(label_doc.get("label"), DRIVER_LABEL_CN)
    buyside_seg = _top2(label_doc.get("buySideProbabilities"), DRIVER_BUYSIDE_CN) \
        or _enum_cn(label_doc.get("buySideLogic"), DRIVER_BUYSIDE_CN)
    parts = [
        f"驱动类别={label_seg}",
        f"催化深度={_enum_cn(label_doc.get('catalystDepth'), DRIVER_DEPTH_CN)}",
        f"新鲜度={_enum_cn(label_doc.get('freshness'), DRIVER_FRESHNESS_CN)}",
        f"买盘逻辑={buyside_seg}",
    ]
    tail = ""
    carried_set = {DRIVER_CARRY_AXIS_CN[k] for k in
                   (label_doc.get("carriedQuestionKeys")
                    or label_doc.get("carriedAnswers") or {})
                   if k in DRIVER_CARRY_AXIS_CN}
    carried = [a for a in ("驱动类别", "催化深度", "新鲜度", "买盘逻辑") if a in carried_set]
    if carried:
        frm = label_doc.get("carriedFrom")
        tail = f" · {'/'.join(carried)}=承接 {frm or '上一交易日'} 判定（非当日重问）"
    return head + " · ".join(parts) + tail


# ── 涨停原因行 / 板块强度行（AMMO 2026-10-28a，v12 批次；预登记 §4.1/§4.3） ──

def limitup_reason_line(entries: list[tuple[str, str | None]]) -> str | None:
    """涨停原因行（v12，裁决③）：join 韭研板内解析 expound（已落库零外呼），仅待判龙一自身。

    `entries` = [(标签, reason|None), ...]，标签如「主板龙一 菲林格尔」；板块成员原因
    **不列**（2026-10-28 用户裁决：只需龙头自己的；板内同伴由既有板内解析行承载）。
    单一事实源 = `jev_label_jiuyan.expound_reason()`（与打标链读口同源，禁第二套解析）。
    entries 空 → None（调用方不出行）；缺失 → fail-visible「不可考」，不伪装成无催化。
    """
    if not entries:
        return None
    parts = [f"{label}={reason}" if str(reason or '').strip()
             else f"{label}=不可考" for label, reason in entries]
    return "涨停原因：" + "；".join(parts)


def plate_strength_line(match: dict) -> str:
    """板块强度行（v12 G2）：KPL 层1 RealRankingInfo（`get_sector_ranking`，按日查史口径）。

    `match` 由调用方组装（取数/匹配一次，全板块共用）：
    - {ok: True, rank, total, name, strength, pct} → 当日排名/强度/涨幅；
    - {ok: False, reason: "unmatched"} → 名称桥未匹配（fail-visible，不猜近似）；
    - {ok: False, reason: "fetch_failed: ..."} → 接口异常；
    - 缺字段行如实「不可考」，不掩盖。v1 为当日单点（序列扩展另行立项，预登记 §9）。
    """
    if not isinstance(match, dict) or not match.get("ok"):
        reason = str((match or {}).get("reason") or "unknown")
        # 2026-10-30g：工程词中文化（unmatched/fetch_failed），降级原因不带括号
        if reason == "unmatched":
            reason = "未匹配到 KPL 板块"
        elif reason.startswith("fetch_failed"):
            reason = "接口异常 " + reason.split(":", 1)[-1].strip()
        elif reason.startswith("payload_not_ok"):
            reason = "上游返回异常 " + reason.split(":", 1)[-1].strip()
        return f"板块强度：不可用，{reason}"
    rank, total = match.get("rank"), match.get("total")
    rank_txt = (f"#{rank}/{total}" if isinstance(rank, int) and isinstance(total, int)
                else "排名不可考")
    strength = match.get("strength")
    strength_txt = (f"强度 {strength}" if isinstance(strength, (int, float))
                    else "强度不可考")
    pct = match.get("pct")
    pct_txt = f"板块涨幅 {pct}%" if isinstance(pct, (int, float)) else "涨幅不可考"
    name = str(match.get("name") or "")
    head_txt = f"板块强度「{name}」：" if name else "板块强度：匹配信息缺失，"
    return (f"{head_txt}"
            f"当日排名 {rank_txt}，{strength_txt}，{pct_txt}")


# ── 龙虎榜事实行（AMMO 2026-10-30a，2026-10-30 用户指示；预登记 §23） ──

def lhb_line(facts: dict | None, *, codes: Any, roles: dict[str, str] | None = None,
             max_items: int = 6) -> str:
    """龙虎榜事实行（AMMO 2026-10-30a）：按叙事相关个股过滤当日 HisBeOnTheLHB 事实。

    `facts` = `jev_lhb_ammo.collect_lhb_facts(date)` 归一产物（operations 层一次取数全日
    共用，与板块强度/直播同哲学；本函数零 IO 零模型）；`codes` = 叙事相关代码（个股级=
    待判龙一 + 板内封板成员；板块级=双龙一 + 板内封板成员；可带交易所前缀，取后 6 位）；
    `roles` = code(后 6 位) → 身位（如「待判龙一」「主板龙一」），缺省「相关个股」。

    四种结构化状态全 fail-visible（§4.0，不伪装、不插值、不给方向结论）：
    - 取数失败/双端点均不可用 → 「--（reason）」；
    - 当日分组榜单未生成（榜约盘后生成；挂链 17:30（2026-10-30 改时）晚于生成时点，
      日常可得，上游延迟未生成时才出本状态）→ 显式披露 orderSign；
    - 榜单已生成但相关个股 0 只上榜 → 显式披露 0 只（事实陈述，非方向信号）；
    - 有相关上榜 → 按传入 codes 顺序（龙一优先）列主力净额/买/卖（元→亿）与上榜原因。
    席位/机构扩维（2026-10-30c）：相关个股若在 GetStockList 营业部个股榜/GetAgencyListV2
    机构榜（同 facts 归一层，逐端点 fail-visible），追加「席位买入 X亿」「机构净买 X亿
    （N 家）」；不在榜/端点失败时该段缺席不伪装。机构净买可负（负=净卖出，如实呈现）。
    资金字段非数值一律「--」不伪装 0（复用 jev_lhb_ammo._fmt_yi 单一口径）；主力净额=
    盘中主力大单资金流，非交易所龙虎榜席位额（§13.3 task-3 裁决），行内标注防误消费。
    """
    from backend.analysis.hotlist.jev_lhb_ammo import _fmt_yi

    head = "龙虎榜："
    stocks = [s for s in (facts or {}).get("stocks") or [] if isinstance(s, dict)]
    if not stocks:
        if (facts or {}).get("empty_structured"):
            return head + "--，当日分组榜单未生成，缺当日事实≠无上榜"
        reason = str((facts or {}).get("reason")
                     or ("当日无上榜个股行" if (facts or {}).get("ok") else "无数据"))
        # 2026-10-30g+：工程词中文化（用户裁决），降级原因不带括号
        if reason == "no_data":
            reason = "无数据"
        elif reason.startswith("lhb_list_fetch_failed"):
            reason = "榜单拉取失败 " + reason.split(":", 1)[-1].strip()
        elif reason.startswith("fetch_failed"):
            reason = "榜单拉取失败 " + reason.split(":", 1)[-1].strip()
        return f"{head}--，{reason}"
    by_code = {str(s.get("code") or "")[-6:]: s for s in stocks if str(s.get("code") or "")[-6:]}
    ordered: list[str] = []
    for c in (codes or []):
        k = str(c or "")[-6:]
        if k and k in by_code and k not in ordered:
            ordered.append(k)
    if not ordered:
        return (head + f"当日全市场上榜 {len(stocks)} 只，"
                "本叙事相关个股 0 只上榜（事实披露，非方向信号）")

    def _seg(k: str) -> str:
        s = by_code[k]
        role = (roles or {}).get(k, "相关个股")
        name = str(s.get("name") or "") or k
        buy, sell = s.get("main_buy_yuan"), s.get("main_sell_yuan")
        seg = f"{role} {name}（{k}）：主力净额 {_fmt_yi(s.get('main_net_yuan'))}"
        if buy is not None or sell is not None:
            seg += f"（买 {_fmt_yi(buy)} / 卖 {_fmt_yi(sell)}）"
        seg += f"，上榜原因 {str(s.get('reason') or '').strip() or '--'}"
        # 席位/机构扩维（2026-10-30c）：不在榜/端点失败时缺席，不伪装零（§4.0）
        sb = ((facts or {}).get("stock_board") or {}).get(k)
        if sb and sb.get("buy_in") is not None:
            seg += f"；席位买入 {_fmt_yi(sb.get('buy_in'))}"
        ag = ((facts or {}).get("agency") or {}).get(k)
        if ag and ag.get("buy_in") is not None:
            jn = ag.get("join_num")
            seg += f"；机构净买 {_fmt_yi(ag.get('buy_in'))}" + (f"（{jn} 家）" if jn else "")
        return seg

    parts = [_seg(k) for k in ordered[:max_items]]
    more = len(ordered) - max_items
    tail = f"（另 {more} 只相关上榜略）" if more > 0 else ""
    return head + "；".join(parts) + tail


def market_summary_line(entry: dict | None) -> str | None:
    """15:00 收盘总结行（AMMO 2026-10-30e，用户指示）：当日盘面全市场介绍。

    `entry` = operations 层 `market_summary_entry(live_payload, date)` 产物（一次取数
    全板块共用）；本函数零 IO 零模型。None（无归档/非当日/无该条目）→ None 不出行
    （补充行缺席不伪装；直播可用性由 live_line 披露）。"""
    if not entry or not str(entry.get("comment") or "").strip():
        return None
    comment = str(entry.get("comment") or "").strip()
    if len(comment) > 600:
        comment = comment[:600] + f"…[截断，原文 {len(comment)} 字]"
    return f"盘面总结（KPL 15:00）：{comment}"


def build_leader_narrative(*, date: str, market_line: str, structure: str, baseline: str,
                           evidence_block: str, leader_name: str,
                           leader_code: str, headroom: str | None = None,
                           forward_axis: str | None = None,
                           market_summary: str | None = None,
                           ladder_line: str | None = None,
                           zhaban_line: str | None = None,
                           driver_cross: str | None = None,
                           reason_line: str | None = None,
                           lhb_facts_line: str | None = None,
                           plate_strength: str | None = None,
                           series_line: str | None = None,
                           live_line: str | None = None,
                           segment: str | None = None) -> str:
    """投喂给 jev 的完整叙事（顺序固定，便于逐字复现与回归比对）。

    evidence_block 由 `theme_event_digest.build_theme_evidence_block` 生成（fail-visible 文本），
    其头部已含语料采集日/节点数/条数与新鲜度（含未采集分支），2026-10-24a 起不再单列
    corpus_line 行（原两处信息完全重复，纯 token 浪费）；evidence_block 必须原样嵌入，
    不得在 runner 里二次改写。`headroom`（2026-10-24b Q1）= 空间题历史锚行，排在基线后、
    证据块前；None（无历史样本/无可用周期）不出行。
    2026-10-24c 三行：`forward_axis`（前向交易日轴，紧跟盘面行后）、`ladder_line`
    （板内梯队形态）、`zhaban_line`（板内炸板面），均 None 不出行（旧调用形状不变）。
    `driver_cross`（AMMO 2026-10-27b）= 个股打标交叉行，排在空间锚后、证据块前；
    None 不出行（打标缺席由 driver_cross_line 出 fail-visible 缺席行，不走本参数）。
    `plate_strength`（AMMO 2026-10-28a G2）= KPL 板块强度行，属板级盘面事实，排在炸板面行后、
    基线前；None 不出行。`reason_line`（AMMO 2026-10-28a §4.1）= 涨停原因行（韭研 expound），
    排在打标交叉行后、证据块前；None 不出行。`lhb_facts_line`（AMMO 2026-10-30a）= 龙虎榜
    事实行（lhb_line 产出，取数单一源 jev_lhb_ammo.collect_lhb_facts），排在涨停原因行后、
    证据块前；None 不出行（未传入时旧行为不变）。
    """
    lines = [
        f"{date} 交易日 · {market_line}",
    ]
    if market_summary:
        lines.append(market_summary)
    if forward_axis:
        lines.append(forward_axis)
    # P1-4（review）：轨别身位必须在叙事头部显式标注（题面规则⑥/空间题⑤的前提
    # 「若叙事标注分轨」，否则双轨龙一身位对模型不可见）
    seg_cn = {"main": "主板龙一", "growth": "双创龙一"}.get(segment)
    seg_txt = f"〔{seg_cn}〕" if seg_cn else ""
    lines.append(f"待判龙头：{leader_name}（{leader_code}）{seg_txt}")
    lines.append(structure)
    if ladder_line:
        lines.append(ladder_line)
    if zhaban_line:
        lines.append(zhaban_line)
    if plate_strength:
        lines.append(plate_strength)
    if series_line:
        lines.append(series_line)
    if live_line:
        lines.append(live_line)
    lines.append(baseline)
    if headroom:
        lines.append(headroom)
    if driver_cross:
        lines.append(driver_cross)
    if reason_line:
        lines.append(reason_line)
    if lhb_facts_line:
        lines.append(lhb_facts_line)
    lines.append(evidence_block)
    return "\n".join(lines)


def build_sector_narrative(*, date: str, market_line: str, structure: str, baseline: str,
                           evidence_block: str, board: str,
                           forward_axis: str | None = None,
                           market_summary: str | None = None,
                           ladder_line: str | None = None,
                           zhaban_line: str | None = None,
                           plate_strength: str | None = None,
                           series_line: str | None = None,
                           live_line: str | None = None,
                           reason_line: str | None = None,
                           lhb_facts_line: str | None = None) -> str:
    """板块级叙事（v12 A2 拆题：深度/延续题每板块一次，预登记 §2.3）。

    与个股级叙事差异：头部「待判板块」，结构行=双龙一并列（structure_line_dual）；
    基线行以第一轨（main 优先）龙一为参照行（分轨锚缺位如实，历史窗人群不随规则换代）；
    **不含**空间锚行（空间题不在板块级子集）与个股打标交叉行（个股轴归各自龙头叙事，
    板块级以涨停原因行提供带动证据关键词）。`lhb_facts_line`（AMMO 2026-10-30a）= 龙虎榜
    事实行（双龙一 + 板内封板成员代码过滤），排在涨停原因行后、证据块前；None 不出行。
    顺序固定，便于逐字复现与回归比对。
    """
    lines = [f"{date} 交易日 · {market_line}"]
    if market_summary:
        lines.append(market_summary)
    if forward_axis:
        lines.append(forward_axis)
    lines.append(f"待判板块：{board}")
    lines.append(structure)
    if ladder_line:
        lines.append(ladder_line)
    if zhaban_line:
        lines.append(zhaban_line)
    if plate_strength:
        lines.append(plate_strength)
    if series_line:
        lines.append(series_line)
    if live_line:
        lines.append(live_line)
    lines.append(baseline)
    if reason_line:
        lines.append(reason_line)
    if lhb_facts_line:
        lines.append(lhb_facts_line)
    lines.append(evidence_block)
    return "\n".join(lines)