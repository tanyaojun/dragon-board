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

import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from backend.analysis.hotlist.jev_driver_ammo import _questions_hash
from backend.analysis.hotlist.jev_lhb_ammo import _fmt_yi
from backend.services.kpl_socket_protocol import RPLATE_INC_IS_PERCENT, bdo_item_yuan

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
# **v14 = 2026-11-02 新龙人气成色题（P3 工作流 B，预登记
# theme-leader-v14-rebound-popularity-preregistration-20261102，用户裁决 B1-B5 全 A
# + 预算批 ≤60 calls/月）**：①新增事件驱动题 `leader_rebound_popularity`（三档：
# dragon_confirm 新龙确立/one_day_pop 单日反抽/insufficient；B2:A 低置信用
# confidence 表达不新增档位）；②B1:A 事件门——仅当日命中弱转强事件
# （leaderRebound/benchmarkAdvance，事件股=当日分轨空间龙一）的叙事判答本题，
# 非事件日叙事不含本题零额外调用（程序门在 operations 层）；③人气证据链叙事行
# （AMMO 2026-11-02a，`rebound_popularity_line`）：全部复用已落地结构证据零新采集
# （B3:A）——事件行/窗内逐日表现（观察池 windowChanges）/板内跟随（当日板内上板
# 家数）/周期背景（theme_cycle 当日态，只披露不进判档硬判据）；④四题题面一字不改
# （v13 §2.4 纪律），hash 随换代变更跨代不可比。
# **v15 = 2026-11-04/05 续板题桶校准锚 + 结构事实行（预登记
# theme-leader-v15-seal-calibration-preregistration-20261104，用户批准实施；门槛已达成：
# settled live 112≥100、wzs 数据轨 122 文档/413 事件≥20）**：①C1 续板题规则①加全样本基础率锚
# （实测 n=112 续板率 21.4%，程序直算可复算 backend.operations.theme_leader_seal_stats）——
# 归因发现四桶无区分力且系统性高估（0 行 ≥65%、verylow>low 颠倒、pEst≈30% vs 21.4%）；
# ②P1 结构事实行（structure_facts_line，Q8:A 并列披露不仲裁）：周期状态/当日封板/
# 真连板高度/板内梯队四字段程序直读随语料投喂，行首标注「供校准参考 · 不作判据」；
# ③深度/延续/空间/人气四题题面一字不改（v13 §2.4 纪律），hash 随续板题面变更跨代不可比。
# **v17 = 2026-11-11 题集 × 语料匹配优化 + 个股级两新题**（用户裁决「两个问题有点少」，
# 预登记 theme-leader-v17-questionset-corpus-match-preregistration-20261111，D1-D8 批准）：
# ①续板题重写——先验底改读程序注入「续板基础率」锚行（废写死 21.4%，率值单一事实源，
# 窗口随结算滚动）；竞价/封板质量行给方向读法（封单占比低+峰值大幅回落+主力净流出=弱）；
# high 档不再字面要求高度领先（持平但承接强+催化硬新鲜可达）；周期状态解禁为调档佐证
# （D5，不得单独定档）；7 条元规则压成 4 条；②空间题重写——起判档从「1-3 板→peak」
# 硬编码改空间锚最细出率桶读数直接映射（<三成 peak／≥三成 space_1／≥2板率≥两成且板块
# 发酵/强延续 space_2plus），修复题面与锚行窗口漂移（光洋 11-11 案：3 板桶 47.5% vs
# 题面写死「仅一到三成」）；「综合前三题」改综合可见的板块判定行+同调用三题（修复 v12
# A2 拆题后跨题引用悬空）；③新增 leader_catalyst_hardness（催化硬度：hard_fact/
# sector_story/soft_meme）与 leader_seat_durability（身位稳固度：core_seat/
# contested_seat/relay_seat）——题材深度/广度的个股侧显式中间判断，结局锚复用
# outcomeSealedNextDay/outcomeDay2/supersededBy 零新结算；④人气题一字不改；⑤板块级
# 两题一字不改。配套 AMMO 2026-11-12a：板块判定行（板块 doc 判答注入个股叙事，纯 join）
# + 续板基础率锚行（seal_stats 滚动直算）+ GENE_CN「首板被板」错字修复。
QUESTION_SET_VERSION_THEME_LEADER = "v17"
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
# 2026-11-02a（P3 工作流 B 人气证据链行，2026-11-02 用户裁决 B1-B5 全 A）：新增
# rebound_popularity_line——弱转强事件股专属证据行组（事件行/窗内逐日表现/板内跟随/
# 周期背景），全部复用已落地数据零新采集；仅事件日出行，与 v14 事件门同源。原四题
# 判据引用源未变，不构成题面改动。
# 2026-11-08a（用户需求：涨停基因语料接入题集，前端不上）：新增 `zt_gene_line`（个股级
# 叙事，排涨停原因行前、龙虎榜行前）：待判龙一自身「涨停次数/溢价5%次数/次日红盘率/
# 首板封板率/首板被板率/连板率」六元（单一事实源 = kpl_daban_pool.gene_items，
# apphq StockL2Data/GetZhangTingGene 逐股懒取落库）。上游**未标注统计窗口** → 口径注
# 原样保留不自算；回填条目（抓取日≠日档交易日，值含此后信息）显式标注抓取日。缺失走
# 「不可考」不补 0。判据零改动，沿 2026-10-24c/2026-11-02a 先例：纯语料补行不动题面 hash。
# 2026-11-08e（纯语料补行，题面 hash 不动）：新增 notice_count_line——公告/新闻/研报
# 计数（apphis CompanyNotice/GetCompanyCount，题材龙头语料第 3 项），排涨停原因行后、
# 龙虎榜行前（事件/风险画像族）；单一事实源 kpl_daban_pool.notice_items；计数统计窗口
# 上游未标注 → window_note 随行带出；公告标题/正文不进叙事（只出计数与日期）。
# 2026-11-08d（纯语料补行，题面 hash 不动）：新增 theme_heat_line——KPL 题材库
# （socket 2013 StockRelatedThemeResp，题材龙头语料第 2 项）个股级「题材热度」行，
# 排打标交叉行后、基因行前（题材族聚拢）；单一事实源 kpl_daban_pool.theme_items。
# 2026-11-08 深度题点名「题材热度」的判据缺口先落语料，判据义务是否换代另行裁决。
# 2026-11-08c（纯语料补行，题面 hash 不动，沿 gene/AMMO 2026-11-08a 先例）：封板质量行
# 增「首板 X（回封 Y）」时点段——zt_time/last_zt_time（epoch 秒→Asia/Shanghai HH:MM，
# 11-06 实测 33/33 数值齐全）已在库零新采集；回封时点=当日曾炸板回封的直读证据；
# 历史若为 "HH:MM" 字符串原样带出，缺失出「首板时点不可考」，不补 0。
# 2026-11-08b（题集 v16，用户裁决「同步改题面判据」）：①新增 `seal_quality_line`（个股级
# 叙事，排板内炸板面行后、基线前）——待判龙一「封单额=实际流通%/峰值封单回落/实际换手/
# 主力净额=成交额%」，单一事实源 = kpl_daban_pool.items 的 2103 quotas 具名字段（已落库
# 零新采集）；②**题面换代**：续板题规则⑦、空间题规则⑥ 把「封板质量」行写成显式判据
# 引用源（偏离锚须点名该行数字；不可考/单位待校验时不得据此调档），criteria 各档文案不动；
# hash 随换代变更，v15 旧答跨代不可比（预登记
# docs/hotlist-jev/theme-leader-v16-seal-quality-preregistration-20261108.md）。
# 封单单位未与 App 逐列对照 → 行内做元/手双假设自证（占实际流通比须落在合理带内），
# 不成立只原样透出并标「单位待校验」，禁猜换算（评审修订：元/手双假设在低价股区间
# 数学上不可分，改为只按元假设带校验，手假设待 GetStockPanKou 实弹复核钉死单位后再
# 启用——_seal_unit 一处切换，行文与下游零改动）。
# 2026-11-11（KPL 语料缺口补全，纯语料补行，题面 hash 零改动，沿 2026-10-24c 先例）：
# ①2203 伴生字段进叙事：涨停原因行追加「热点摘引」（plate）；新增热度排名行/风险画像行
#   （rank/rank_total/rank_top/zt_group/fx/jc/jj/pledge，仅非空字段出场）；zt_tag 为数值
#   tag 无文案映射 → 只透传落库不渲染。
# ②bid/zb/dt 三通道进叙事：竞价承接行（bid_items）/板内炸板明细升级（zb_items 触板/开板
#   时刻）/板内跌停行（dt_items，采集成功且板内无成员=「板内无跌停」验证缺席行）。
# ③2112/3004/3101 落库语料进叙事：上榜预测行（fc_items：热度=人气值口径，与 rank=排名
#   严格区分）/实时龙虎榜行（rt_items 命中板内成员）。
# ④2014/2202/2030/2010 四通道进叙事：封板大单行（2026-11-11 实弹值校准后元口径万/亿
#   格式化，尾条最新态）/ 爆发原因行 / 异动提醒行（zf 口径未钉死整行暂停渲染）/
#   板块归属行（剔题材热度已知板块防重复）。
# AMMO_VERSION 随原料合同变更 bump（fetch_reason_corpus 形状 dict[str,str]→dict[str,dict]）。
# 2026-11-12a（题集 v17 批次，用户批准预登记 D1-D8）：①板块判定行 sector_judgment_line——
# 板块级 doc 深度/延续判答注入个股叙事（修复 v12 A2 个股级跨题引用悬空；纯 join 零调用，
# 同轮缓存+库读兜底由 operations 层承担；degraded/insufficient 整行缺席 + 结构化
# sectorJudgmentState 留痕，§1.2-8）；②续板基础率锚行 base_rate_line——live 已结算人群
# 滚动直算（theme_leader_seal_stats.live_base_rate，窗 2026-10-23~当日之前），题面不再
# 写死率值（v15 锚 21.4% 窗口漂移教训，单一事实源）；③GENE_CN first_broken_pct 译名
# 「首板被板」→「首板炸板」（错字修复，光洋 11-11 案例登记 §1.5-1）。
# 2026-11-12b（v17 开火前修订，2026-11-11 用户裁决）：11-10 上海海洋观测新闻含
# 「海洋智能机器人、潜水器」，与光洋减速器/机器人零部件业务强相关=**真实命中**，
# 初判「误命中」推翻、O1 匹配锚扩展立项撤销（匹配层正确）。题面新闻核实改按
# 业务/产业链关联（标题未点名公司≠无关），硬度题 sector_story 同口径。v17 零
# 已标答 doc，开火前修订不跨代污染；hash 随题面自动重算。
AMMO_VERSION_THEME_LEADER = "2026-11-15a"   # 纯语料供给换代：监管风险行（KPL 异动提醒页 严重异动/重点监控 五组，预登记 theme-leader-regulatory-risk-20261115）；题面 hash 不动；前一版 2026-11-14a = S3 成分验证门+产业树残桩正文剔除


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
        # v17 重写（预登记 v17 §2.1）：先验底改读「续板基础率」锚行（程序直算滚动，
        # 废 v15 写死 21.4%）；竞价/封板质量给方向读法；周期状态解禁为佐证（D5）；
        # 7 条元规则压成 4 条。四档阈值（25/45/65）与 Brier 验收链不变。
        "instructions": "仅依据所给证据，判断该板块龙头在**次一交易日**继续封板（涨停）的概率"
                        "落在哪一档。只判概率档位，不预测价格、不给买卖建议。硬规则："
                        "①锚对齐：概率中枢=叙事「结构基线」行最细出率同桶（方括号条件最全"
                        "且样本≥8；无则用「按连板高度」桶）；先验底=「续板基础率」锚行"
                        "（程序直算、随窗滚动）。档位高于先验底两档（即≥45%）或偏离中枢"
                        "一档以上（上调或下调），理由必须点名基线/锚行具体数字，并给出锚未"
                        "覆盖的当日新证据（新催化、竞价承接突变、封板质量异常等），不得凭"
                        "整体行情乐观或悲观移动档位；"
                        "②量化证据：「竞价」行（高开幅度/竞价额）与「封板质量」行（封单额="
                        "实际流通比/峰值封单回落/实际换手/主力净额占成交额比）是当日承接与"
                        "封板强度的唯一可量化判据源——封单占比低、峰值大幅回落、主力净额"
                        "大幅流出=封板质量弱；竞价放量高开=承接强。偏离中枢而引用时必须点名"
                        "具体数字；行缺席、不可考或标单位待校验时不得以该行为由调档，也不得"
                        "自行补 0。「结构事实」行的周期状态可作调档佐证之一（转弱=降档佐证、"
                        "主升=升档佐证），不得单独定档，仍须点名基线/锚行数字。有明确日期与"
                        "新鲜度的题材证据（产业树/题材事件·新闻/前瞻日历/板内解析/个股打标"
                        "交叉）权重高于结构特征；引用新闻须按业务/产业链关联核实（公司主营/基因/板块标签"
                        "与新闻主题的实质联系，如机器人零部件/减速器业务↔水下机器人/海洋装备"
                        "政策）——标题未点名公司、关联股列表不含本公司不等于无关，经核实的"
                        "板块级政策/产业新闻按板块叙事催化计；"
                        "③缺失门：三层证据（产业树/题材事件·新闻/板内解析）同时缺失判 "
                        "insufficient（程序强制覆盖，原答另存备查），不得用结构特征硬填空档；"
                        "④特殊场景：叙事标注待判龙头**今日未封板**（断板反包候选）时，本题="
                        "次日**重新上板**概率：封板质量/封板时间判据不适用，改按断板承接"
                        "（板内炸板面/昨日仍封数）、板块判定行与题材证据判断；结构基线行"
                        "（含任一出率桶）、承接行、梯队行、题材证据任一在场必须按①给档，"
                        "锚缺失仅要求降低置信（confidence ≤0.6），不得以「无同构历史锚」"
                        "判 insufficient；叙事标注分轨（主板/双创）时，待判龙头为其轨内按 "
                        "10 日涨幅取出的龙一，身位表述以轨内为准，另一轨龙一仅作板块结构事实。",
        "criteria": {
            "high_ge65": "高概率≥65%：结构强（高度领先，或竞价放量高开+昨日承接强）且催化"
                         "硬而新鲜（涨停原因/打标交叉=新催化≤2 日，或当日新增题材事件/新闻，"
                         "或未来 1-2 日既定事件），且封板质量无示警（封单占比不低、峰值未"
                         "大幅回落、主力未大幅净流出）",
            "mid_45_65": "中等 45%-65%：结构与催化一强一弱，或与中枢同档；典型：催化新鲜"
                         "但封板质量弱/身位持平，或结构强但催化陈旧",
            "low_25_45": "偏低 25%-45%：结构一般（封板偏晚/跟风薄/板块家数少）或催化陈旧"
                         "无新增，或封板质量示警（封单占比低+峰值大幅回落+主力净流出）",
            "verylow_lt25": "很低<25%：结构示警（家数少+封板晚+无梯队）且题材退潮（板块判定"
                            "=退潮期/临近结束，或家数萎缩+炸板面扩大）",
            "insufficient": "证据不足：三层证据（产业树/题材事件·新闻/板内解析）同时缺失或"
                            "板块结构不可考；未封板场景：结构基线行有任一出率桶时不得选本档"
                            "（v13）",
        },
    },
    "leader_headroom": {
        "type": "choice",
        # v17 重写（预登记 v17 §2.2）：起判档改空间锚读数映射（废「1-3 板→peak」硬编码，
        # 修复窗口漂移）；跨题引用改可见的板块判定行+同调用三题（修复 A2 悬空）；
        # 身位/催化硬度从隐式前提变显式判据（两新题）。映射阈值（三成/两成）是冻结
        # 设计常数，非窗口统计量。
        "instructions": "综合「板块判定」行（题材深度/延续性）、本次调用中催化硬度/身位稳固度/"
                        "次日续板概率的判断与「空间锚」行（历史同结构龙头自当日高度的再走≥1板率/"
                        "≥2板率/中位分布），判断该龙头在当前连板高度之上**还能再走几个板**。"
                        "注意：这是空间判断，不是次日概率判断——强延续题材的龙一通常仍有空间，"
                        "退潮题材的高标即使次日勉强封板也缺乏空间。硬规则："
                        "①起判档由空间锚最细出率桶读数直接映射（不按连板高度硬编码）：再走"
                        "≥1板率不足三成 → peak 起判；三成及以上 → space_1 起判；其中≥2板率"
                        "两成及以上且板块判定为发酵期/强延续 → space_2plus 起判。连板高度"
                        "不可算时（含待判龙头今日未封板的断板反包候选）同样按最细出率桶起判"
                        "（无按高度细分则用总体行）；锚行整体缺席（叙事无空间锚行）才允许按"
                        "证据自判，且此时若为未封板场景 confidence ≤0.6；"
                        "②偏离起判档（上调或下调）必须点名锚行具体数字，并给出锚外新证据"
                        "（封板质量行数字、催化硬度、身位稳固度、板块判定、当日新催化）；"
                        "仅「连板高/身位强/题材强」这类与锚同源的结构特征不得作为偏离理由；"
                        "③跨题一致性：板块判定深度=启动期/发酵期时本题默认不得选 peak；"
                        "延续性=临近结束，或催化硬度=soft_meme 且身位=relay_seat 时默认"
                        "不得选 space_2plus；偏离须点名锚行数字并给锚外新证据；"
                        "④叙事标注分轨（主板/双创）时，待判龙头为其轨内龙一，空间判断以轨内"
                        "身位为准（双创 20cm 生态与主板 10cm 不同，另一轨龙一仅作板块结构"
                        "事实）；⑤三层证据（产业树/题材事件·新闻/板内解析）同时缺失判 "
                        "insufficient；叙事含空间锚行（有率值）时不得选本档（v13）。",
        "criteria": {
            "space_2plus": "仍有≥2 板空间：锚≥2板率两成及以上或锚外强新证据，且板块判定"
                           "发酵期/强延续、身位 core_seat、催化硬而新鲜，梯队与催化双支撑",
            "space_1": "还有约 1 板空间：锚再走≥1板率三成上下或起判档，题材尚可延续或身位"
                       "尚可，但催化新鲜度/身位/封板质量有一项已走弱",
            "peak": "空间已尽：锚再走≥1板率不足三成，或板块判定退潮期/临近结束，或身位被"
                    "替代/催化断流，当前高度大概率就是顶部",
            "insufficient": "证据不足：仅当语料未采集或三层证据（产业树/事件·新闻/板内解析）"
                            "同时无痕迹；叙事含空间锚行（有率值）时不得选本档（v13）",
        },
    },
    # ── v17 两新题（预登记 v17 §2.3，用户裁决「两个问题有点少」）：题材深度/广度的
    # 个股侧显式中间判断，随续板/空间同调用判答（零额外调用次数）；结局锚复用已落库
    # 字段（outcomeSealedNextDay/outcomeDay2/supersededBy），零新结算代码。──
    "leader_catalyst_hardness": {
        "type": "choice",
        "instructions": "仅依据所给证据（涨停原因行/爆发原因行/板内解析/题材证据块/打标交叉行/"
                        "公告计数行），判断驱动该龙头涨停的**催化硬度**——催化有多可证实。"
                        "只判催化性质，不预测价格、不给买卖建议。硬规则："
                        "①按「最硬的可证实事实」判档，理由必须点名硬事实的日期与来源"
                        "（公告/投资者关系记录/研报/订单交付/并购并表/新业务放量）；"
                        "②软成分（名称谐音梗、未证实网传纪要/研报、蹭概念）并存时理由必须"
                        "披露，但不降低硬事实档位；「未证实」是程序对来源可靠性的标注，"
                        "此类内容按软证据计；③打标交叉行的驱动类别/催化深度/新鲜度是另一条"
                        "打标链的判定，只作交叉参考，不替代本题证据判读；④三层证据（产业树/"
                        "题材事件·新闻/板内解析）同时缺失且涨停原因行亦缺席才判 insufficient；"
                        "证据部分缺位按在场证据判档并降低置信。",
        "criteria": {
            "hard_fact": "公司级硬催化：公告/投资者关系记录/机构研报/订单交付/并购并表/"
                         "新业务放量等可证实事实，可点名日期与来源",
            "sector_story": "板块级叙事：政策/行业新闻/板块事件驱动，公司受益但无自身"
                            "公司级硬事实；新闻与公司的业务/产业链关联经核实即计"
                            "（标题未点名公司、关联股不含本公司不影响）",
            "soft_meme": "软催化：未证实网传消息/名称谐音梗/蹭概念驱动，或纯资金接力无催化",
            "insufficient": "证据不足：三层证据（产业树/事件·新闻/板内解析）同时缺席且涨停"
                            "原因行亦缺席；部分缺位按在场证据判档并降低置信",
        },
    },
    "leader_seat_durability": {
        "type": "choice",
        "instructions": "仅依据所给证据（梯队形态行/结构行/热度排名行/打标交叉行/板内同伴驱动/"
                        "龙虎榜行/板块判定行/题材热度行），判断该龙头在板块内的**身位稳固度**"
                        "——是稳固核心、被挑战，还是可替代的接力位。只判身位性质，不预测价格、"
                        "不给买卖建议。硬规则：①判档必须点名梯队领先差/热度排名/买盘逻辑中"
                        "至少一项具体事实；②买盘逻辑=高位卡位/情绪接力为主且无独立催化时"
                        "默认 relay_seat，除非高度显著领先（领先差≥1 板）或热度排名 Top3；"
                        "③板块判定=退潮期/临近结束时默认不得判 core_seat；④板块结构不可考"
                        "且三层证据（产业树/题材事件·新闻/板内解析）同时缺失才判 insufficient；"
                        "证据部分缺位按在场证据判档并降低置信。",
        "criteria": {
            "core_seat": "身位稳固：高度领先（领先差≥1 板）或热度/催化无可替代，梯队有真"
                         "连板跟风支撑，板块判定活跃",
            "contested_seat": "身位被挑战：与次高持平或热度分流（排名非 Top3/龙虎榜席位"
                              "机构分歧），但板块仍活跃，走向取决于次日卡位",
            "relay_seat": "接力位：高位卡位/情绪接力驱动、无独立催化、梯队薄，随时可被替代",
            "insufficient": "证据不足：板块结构不可考且三层证据同时缺失；部分缺位按在场"
                            "证据判档并降低置信",
        },
    },
    "leader_rebound_popularity": {
        "type": "choice",
        "instructions": "仅依据所给证据（人气证据链行、板块结构、空间锚行、题材证据），"
                        "判断该板块龙头的弱转强反包（人气股反包/标杆晋级，当日收盘封板"
                        "确认）的**人气聚合成色**：是真聚合（新龙确立）还是存量情绪脉冲"
                        "（单日反抽）。只判当次反包的性质，不预测价格、不给买卖建议。"
                        "硬规则：①「空间锚」行若在场，它是必须先对的概率中枢——你的"
                        "理由仅为「身位强/题材强」等与锚同源的结构特征时，应选与锚"
                        "一致的档位；无论上调或下调，偏离锚的档位都必须在理由中点名"
                        "锚行具体数字，并给出锚未覆盖的新证据；②人气证据链行是本题"
                        "专属判据源：判档必须在理由中点名链行具体事实（窗内逐日表现/"
                        "板内跟随/板块家数方向）；③跨题一致性：同一叙事的「题材延续性」"
                        "若判 ending，本题默认不得判 dragon_confirm，除非点名锚行数字"
                        "并给锚外新证据；④关键证据缺失判 insufficient：仅当窗内逐日"
                        "表现缺失**且**板块结构不可考两者同时成立；证据部分缺位（如无"
                        "跟随数/无周期背景）不是 insufficient 理由，按在场证据判档并"
                        "降低置信；⑤若叙事标注分轨（主板/双创），待判龙头为其轨内龙一，"
                        "判档以轨内身位为准。",
        "criteria": {
            "dragon_confirm": "新龙确立：人气聚合——板内跟随在场（当日板内上板≥2 家，"
                              "含龙头自身）或窗内表现稳住高位（反包前未深度溃散），"
                              "或题材延续信号支撑",
            "one_day_pop": "单日反抽：封板但人气未聚——板内无跟随（当日仅龙头自身上板）、"
                           "题材无新增催化，或窗内表现已深度走弱",
            "insufficient": "证据不足：仅当窗内逐日表现缺失且板块结构不可考两者同时成立；"
                            "证据部分缺位按在场证据判档并降低置信，不得硬填",
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
                        keys: tuple[str, ...] | None = None,
                        prob_key: str = "leader_nextday_continue") -> tuple[Any, dict]:
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
    prev_prob = answers.get(prob_key) if isinstance(
        answers.get(prob_key), dict) else {}
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
        if key == prob_key:
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

    kept, _censored = _leader_cycles(rows)   # 删失数只供结构化审计，叙事已不披露
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
    # 右删失样本数只进结构化审计，不进叙事（AGENTS §1.2-8）
    # 2026-10-30d 语料精简：再走≥1板率定义在题面 ③ 已给，叙事侧不重复
    return ("空间锚："
            + "；".join(parts) + f"；总体 {_stat(kept)}")


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
    """板块序列行（P1-1，G2/G3）：双段强度/涨停家数据，各自如实标注。

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
        return f"板块序列 {plate_name}：强度无记录；涨停家不可考"
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
        # 口径哨兵（rank_sentinel_warnings）只进结构化审计，不进叙事（AGENTS §1.2-8）
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
                       else f"{str(last.get('date'))[5:]} ")
            parts.append(f"{day_txt}梯队：{lz}")
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
    head = f"直播播报（"
    if window:
        head += f"{window}"
    head += "）"
    if unavailable:
        return None
    if not entries:
        return f"{head}：当日无「{board}」相关播报"
    parts = []
    for e in entries[:max_items]:
        c = re.sub(r"\s+", " ", str(e.get("comment") or "")).strip()
        if len(c) > clip_chars:
            c = c[:clip_chars] + "…"
        parts.append(f"{e.get('time') or '时间不可考'} {c}")
    return head + "：" + "；".join(parts)


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
        # P2-4（review 2026-11-05）：负差原拼接成「领先 +-1」，改带符号数；0 差写持平
        diff = leader_streak - second
        lead_txt = "持平" if diff == 0 else f"{diff:+d}"
        seg += f"；龙头 {leader_streak} 板，次高 {second} 板（领先 {lead_txt}）"
    elif isinstance(leader_streak, int):
        seg += f"；龙头 {leader_streak} 板，次高 不可算"
    else:
        seg += "；龙头连板高度不可算"
    return seg


def board_zhaban_line(row: dict, detail: list[dict] | None = None) -> str | None:
    """板内炸板面行（2026-10-24c）：分化/退潮的板内证据。

    climax 判据「跟风断板增多」、ebbing「龙头断板或出现大面」此前只有全市场炸板率，
    板内触板未封（韭研曾触板−THS炸板二分同口径，剔 ST/北交所）缺席。昨日数不可考
    （昨日池缺失/板块改名）时只出今日，如实不列对比。
    `detail`（2026-11-11 ②纯语料补行）：板内成员在 zb_items 的触板/开板时刻
    （[{name, zt_time, open_time}]，时刻 epoch 秒→HH:MM；字段不可读该段缺席，
    不猜时间形态），均缺 → 不追加，家数行原样。
    """
    z = row.get("zhabanN")
    if not isinstance(z, int):
        return None
    seg = f"板内炸板面：今日触板未封 {z} 家"
    pz = row.get("prevZhabanN")
    if isinstance(pz, int):
        seg += f"（昨日 {pz} 家）"
    for d in detail or []:
        name = str((d or {}).get("name") or "").strip() or "成员"
        bits: list[str] = []
        zt = _hhmm_from_ts((d or {}).get("zt_time"))
        if zt:
            bits.append(f"触板 {zt}")
        ot = _hhmm_from_ts((d or {}).get("open_time"))
        if ot:
            bits.append(f"开板 {ot}")
        if bits:
            seg += f"；{name} {'，'.join(bits)}"
    return seg


def bid_line(entries: list[dict]) -> str | None:
    """竞价承接行（2026-11-11 ②纯语料补行，题面 hash 不动）：当日集合竞价承接事实。

    `entries` = [{"label", "item"}]，item 取自 `kpl_daban_pool` bid_items
    （fetch_daban_lanes 归一产物，quotas 具名字段）。口径纪律：
    - 信息量门槛：竞价额>0 或竞价涨幅≠0 才出；全空/缺该股 → 该股缺席；
    - 竞价额（元原样）用 _fmt_amount_yuan（亿/万自适应）；涨幅带符号百分串；
    - 单段缺位用「不可考」最简标注（AGENTS §1.2-8 允许的最简缺失标注）。
    entries 空 → None（调用方不出行）。
    """
    if not entries:
        return None
    parts: list[str] = []
    for entry in entries:
        item = (entry or {}).get("item")
        if not isinstance(item, dict):
            continue    # 竞价通道缺该股 → 整段缺席（不伪装零）
        pct = _qnum(item.get("bidding_pct"))
        amt = _qnum(item.get("bidding_amount"))
        # 信息量门槛：竞价额>0 或竞价涨幅≠0 才有判读价值
        has_amt = amt is not None and amt > 0
        has_pct = pct is not None and pct != 0
        if not (has_amt or has_pct):
            continue
        pct_txt = f"{pct:+.2f}%" if pct is not None else "竞价涨幅不可考"
        amt_txt = _fmt_amount_yuan(amt) if has_amt else "不可考"
        parts.append(f"{entry.get('label') or '该股'} {pct_txt} 竞价额 {amt_txt}")
    return "竞价：" + "；".join(parts) if parts else None


def board_dt_line(names: list[str], lane_ok: bool) -> str | None:
    """板内跌停行（2026-11-11 ②纯语料补行）：dt_items 板内成员名单。

    缺席语义（§4.0）：
    - lane 采集成功（ok=True 含「采集成功且 0 家」空档）且板内无成员 →
      「板内无跌停」（验证后的缺席，一行事实）；
    - lane 无档/读口异常（lane_ok=False）→ 整行缺席（全市场家数已有 market_line
      承载，不重复、不伪装）；
    - 有成员 → 名单行（顿号并列，升序由调用方保序）。
    """
    if not lane_ok:
        return None
    if not names:
        return "板内无跌停"
    shown = [str(n).strip() for n in names if str(n).strip()]
    return "板内跌停：" + "、".join(shown) if shown else "板内无跌停"


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
# 承接披露映射（打标链 carriedQuestionKeys 题键 → 交叉行轴名）：
# 解析正文与前一日逐字相同时打标链不重问（carriedFrom=前一日），交叉行必须如实标注
# 「承接判定」——新鲜度等轴是昨日判断，不是当日重问（防模型把承接值当当日新鲜证据）。
DRIVER_CARRY_AXIS_CN = {
    "driver_type": "驱动类别", "catalyst_depth": "催化深度",
    "catalyst_freshness": "新鲜度", "buy_side_logic": "买盘逻辑",
}


def _top2(probabilities: Any, cn: dict[str, str]) -> str:
    """top-2 枚举短名+整数百分比并列；逃生桶（insufficient 系）不进排名，为空返回空串
    （调用方兜底用已选枚举值，全缺「不可考」，不编 0）。两档比值 ≥0.9 的近并列信息
    由百分比自身承载，不加注（AGENTS §1.2-8）。"""
    if not isinstance(probabilities, dict):
        return ""
    items = [(cn.get(str(k), str(k)), float(v)) for k, v in probabilities.items()
             if isinstance(v, (int, float)) and v > 0 and k not in ("insufficient_evidence", "insufficient")]
    items.sort(key=lambda kv: -kv[1])
    items = items[:2]
    if not items:
        return ""
    return "/".join(f"{name}{v:.0%}" for name, v in items)


def _enum_cn(value: Any, cn: dict[str, str]) -> str:
    if not value:
        return "不可考"
    return cn.get(str(value), str(value))


def driver_cross_line(label_doc: dict | None) -> str | None:
    """个股打标交叉行（AMMO 2026-10-27b）：join 打标链当日该股判定，零调用纯原料。

    行内自描述口径（模型每次都是第一次见「打标交叉」这个词）：另一条打标链对该公司
    当日涨停的机器判定，供交叉参考；四轴=驱动类别 top-2/催化深度/新鲜度/买盘逻辑，
    枚举译名+概率并列。槽位显式（final=收盘槽、midday=午盘槽）。label_doc=None →
    **整行缺席**（AGENTS §1.2-8：缺数据不投喂占位；缺席状态只留打标链落库文档）。
    """
    if not label_doc:
        return None
    slot = str(label_doc.get("labelSlot") or "")
    slot_cn = {"final": "收盘槽", "midday": "午盘槽"}.get(slot, slot or "槽位不可考")
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
        tail = f" · {'/'.join(carried)}=承接 {frm or '上一交易日'}"
    return head + " · ".join(parts) + tail


# ── 涨停原因行 / 板块强度行（AMMO 2026-10-28a，v12 批次；预登记 §4.1/§4.3） ──

def limitup_reason_line(entries: list[dict]) -> str | None:
    """涨停原因行（v12，裁决③；2026-11-11 ①升级）：join 2203 语料（已落库零外呼），

    仅待判龙一自身。`entries` = [{"label", "item"}]，item 取自
    `kpl_daban_pool.reason_items`（fetch_reason_corpus 归一产物，非空字段透传）；
    板块成员原因**不列**（板内同伴由既有板内解析行承载）。原因缺位 → 该股整段缺席
    （AGENTS §1.2-8）；全部缺原因 → None（整行不出）。
    2026-11-11 ①：item.plate 非空时追加「热点摘引」（与题材新闻行可能重复，
    用户裁决接受，保真异动解析页全文）。
    """
    if not entries:
        return None
    parts: list[str] = []
    for entry in entries:
        item = (entry or {}).get("item") or {}
        zt = str(item.get("zt") or "").strip()
        if not zt:
            continue    # 原因缺位 → 该股整段缺席（缺数据不占行）
        seg = f"{entry.get('label') or '该股'}={zt}"
        plate = str(item.get("plate") or "").strip()
        if plate:
            seg += f"；热点摘引：{plate}"
        parts.append(seg)
    return "涨停原因：" + "；".join(parts) if parts else None


def popularity_rank_line(entries: list[dict]) -> str | None:
    """热度排名行（2026-11-11 ①纯语料补行，题面 hash 不动）：待判龙一全市场热度排名。

    `entries` 与涨停原因行同形状（单一事实源 = fetch_reason_corpus）；
    - rank>0 且 rank_total>0 才出（2203 rank 族口径=全市场涨停原因榜排名）；
      与上榜预测行 hot_val（人气值）是不同口径，行文命名严格区分；
    - rank_top（Top 榜名单）非空 → 取前 3 名并列；zt_group（涨停梯队串）非空并入；
    - 排名缺位 → 该股整段缺席；全部缺席 → None（整行不出）。
    """
    if not entries:
        return None
    parts: list[str] = []
    for entry in entries:
        item = (entry or {}).get("item") or {}
        rank, total = item.get("rank"), item.get("rank_total")
        if not (isinstance(rank, int) and not isinstance(rank, bool) and rank > 0
                and isinstance(total, int) and not isinstance(total, bool) and total > 0):
            continue    # 排名不可考/不在榜 → 该股整段缺席
        seg = f"{entry.get('label') or '该股'} {rank}/{total}"
        top = [str(x).strip() for x in (item.get("rank_top") or []) if str(x).strip()]
        if top:
            seg += f"（Top3：{'、'.join(top[:3])}）"
        group = str(item.get("zt_group") or "").strip()
        if group:
            seg += f"（梯队：{group}）"
        parts.append(seg)
    return "热度排名：" + "；".join(parts) if parts else None


# 风险画像行字段序（2026-11-11 ①）：减持/解禁/质押/风险提示，逐字段非空才出
_RISK_FIELDS = (("jc", "减持"), ("jj", "解禁"), ("pledge", "质押"), ("fx", "风险提示"))


def risk_profile_line(entries: list[dict]) -> str | None:
    """风险画像行（2026-11-11 ①纯语料补行，题面 hash 不动）：待判龙一风险事件画像。

    `entries` 与涨停原因行同形状；fx/jc/jj/pledge 逐字段非空才出（缺位项不出，
    不补「不可考」占位），整行无任一字段 → 该股缺席；全部缺席 → None。
    """
    if not entries:
        return None
    parts: list[str] = []
    for entry in entries:
        item = (entry or {}).get("item") or {}
        segs: list[str] = []
        for key, cn in _RISK_FIELDS:
            v = re.sub(r"\s+", " ", str(item.get(key) or "")).strip()
            if v:
                segs.append(f"{cn}：{v}")
        if segs:
            parts.append(f"{entry.get('label') or '该股'} " + "；".join(segs))
    return "风险：" + "；".join(parts) if parts else None


def _reg_pct(v: Any) -> str | None:
    """监管行百分比渲染：上游数值=百分数原样+%后缀（探针定档）；缺位 None 不补 0。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return f"{v:g}%"


def regulatory_risk_line(entries: list[dict]) -> str | None:
    """监管风险行（2026-11-15 预登记 theme-leader-regulatory-risk，纯语料补行，题面 hash 不动）。

    `entries` = [{"label", "hit"}]，hit = kpl_daban_pool reg_by_code 索引项
    {monitor_current?, monitor_history?, recent[], today?, tomorrow?}（KPL 异动提醒页
    市场级监管事实，fetch_regulatory_corpus 归一产物）。口径纪律：
    - 只放数据事实：上游日期串/周期标签原样，百分比数值原样+%后缀，不自算不反推；
    - 触发组=条件事实（「今日/明日涨停即触发严重异动」），不伪装既成异动；
    - 逐字段非空才出段；该股无任何监管事实 → 缺席；全部缺席 → None（§1.2-8 整行缺席）；
    - lane 降级由调用方不传 entries + 结构化 regulatoryState 留痕（不进叙事）。
    """
    if not entries:
        return None
    parts: list[str] = []
    for entry in entries:
        hit = (entry or {}).get("hit")
        if not isinstance(hit, dict) or not hit:
            continue
        segs: list[str] = []
        mc = hit.get("monitor_current") or {}
        if mc.get("start_date") or mc.get("end_date"):
            segs.append(f"重点监控({mc.get('start_date') or '不可考'}~{mc.get('end_date') or '不可考'})")
        for r in (hit.get("recent") or [])[:2]:
            d = (r or {}).get("abnormal_date")
            if not d:
                continue
            seg = f"严重异动{d}"
            if r.get("suspended_flag"):
                seg += " 停牌"
                if r.get("resume_date"):
                    seg += f" 预计复牌{r['resume_date']}"
            elif r.get("triggered_flag"):
                seg += " 触发严重异动"
            if r.get("monitor_flag"):
                seg += " 重点监控"
            if r.get("period"):
                seg += f" {r['period']}"
            segs.append(seg)
        for key, cn in (("today", "今日"), ("tomorrow", "明日")):
            t = hit.get(key) or {}
            if not t:
                continue
            bits: list[str] = []
            tp = _reg_pct(t.get("trigger_pct"))
            sp = _reg_pct(t.get("space_pct"))
            if tp:
                bits.append(f"触发涨幅{tp}")
            if sp:
                bits.append(f"偏离空间{sp}")
            if t.get("period"):
                bits.append(str(t["period"]))
            seg = f"{cn}涨停即触发严重异动" + (f"({' '.join(bits)})" if bits else "")
            if t.get("streak_tag"):
                seg += f" {t['streak_tag']}"
            segs.append(seg)
        mh = hit.get("monitor_history") or {}
        if mh.get("start_date") or mh.get("end_date"):
            segs.append(f"历史重点监控({mh.get('start_date') or '不可考'}~{mh.get('end_date') or '不可考'})")
        if not segs:
            continue
        src = mc or mh or (hit.get("today") or {}) or (hit.get("tomorrow") or {}) \
            or ((hit.get("recent") or [{}])[0])
        name = str(src.get("stock_name") or "").strip()
        code = str(src.get("stock_id") or "").strip()
        who = f"{name}{code}" if (name or code) else ""
        parts.append(f"{entry.get('label') or '该股'} {who} ".rstrip() + " " + "，".join(segs))
    return "监管风险：" + "；".join(parts) if parts else None


def _gene_num(v: Any) -> str:
    """基因数值渲染：整数去小数点（100 → 100），小数保留 1 位（66.6667 → 66.7）。

    只做显示截断，不改写上游数值语义（原样值仍在 gene_items.raw 留档）；None → 不可考。
    """
    if v is None:
        return "不可考"
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "不可考"
    if abs(f - round(f)) < 1e-9:
        return str(int(round(f)))
    return f"{f:.1f}"


# (字段, 标签, 单位)：单位随值写出，避免「涨停5」这类缺单位读法（数值仍原样不改写）
GENE_CN = (
    ("zt_count", "涨停", "次"),
    ("premium5_count", "溢价5%", "次"),
    ("next_day_red_pct", "次日红盘", "%"),
    ("first_seal_pct", "首板封板", "%"),
    ("first_broken_pct", "首板炸板", "%"),   # v17 错字修复（原「首板被板」，光洋 11-11 案例）
    ("lianban_pct", "连板", "%"),
)


_THEME_HEAT_TOP_N = 6   # 个股题材库条目可能 10+，叙事行只取热度前 6（余量披露总数）
def _heat_num_fmt(v: Any) -> str:
    """题材热度数值格式化：整数值去小数点（96.0→96），带小数一位（96.5）；其余原样。

    非有限 float（NaN/Inf，HTTP JSON 层可产）原样 str，防 round OverflowError
    （评审 2026-11-08 P2）。"""
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return str(v)
    r = round(v)
    return str(int(r)) if abs(v - r) < 1e-6 else f"{v:.1f}"


def theme_heat_line(entries: list[dict]) -> str | None:
    """题材热度行（2026-11-08d 纯语料补行，题面 hash 不动）：待判龙一 KPL 题材库画像。

    `entries` = [{"label", "themes": [{id,name,number}] | None, "poolMissing": 原因|None}]；
    themes 取自 `kpl_daban_pool.theme_items`（走 load_day(lane="theme")，operations 层取数），
    number = 2013 推送的题材热度（float）。

    口径纪律：
    - 只列热度前 6 个题材（余量「共 X 个」披露），number 降序；number 缺失/非数值的
      条目按原序排后并「原样」带出，不丢不猜；
    - themes 缺失（不在池/语料缺该股/题材库为空）→ 该股**整段缺席**（AGENTS §1.2-8：
      缺数据不投喂占位）；全部缺席 → None（整行不出）；
    - 板块级叙事不消费本行（单股画像，与基因/封板质量同口径）。
    entries 空 → None（调用方不出行）。
    """
    if not entries:
        return None
    parts: list[str] = []
    for entry in entries:
        label = str(entry.get("label") or "").strip() or "该股"
        themes = entry.get("themes")
        # 信息量门槛：无题材条目（缺语料/不在池/题材库为空）→ 该股缺席，不占行
        if not isinstance(themes, list) or not themes:
            continue

        def _key(t: Any) -> float:
            n = t.get("number") if isinstance(t, dict) else None
            return n if isinstance(n, (int, float)) and not isinstance(n, bool) \
                else float("-inf")

        ordered = sorted(themes, key=_key, reverse=True)
        shown = ordered[:_THEME_HEAT_TOP_N]
        segs: list[str] = []
        for t in shown:
            name = (str((t or {}).get("name") or "").strip()
                    or str((t or {}).get("id") or "").strip() or "?")
            n = (t or {}).get("number")
            num = _heat_num_fmt(n) if isinstance(n, (int, float)) and not isinstance(n, bool) \
                else f"原始值 {n}"
            segs.append(f"{name} {num}")
        txt = "；".join(segs) if segs else "题材库为空"
        if len(ordered) > _THEME_HEAT_TOP_N:
            txt += f"（前 {_THEME_HEAT_TOP_N} 按热度，共 {len(ordered)} 个）"
        parts.append(f"{label}：{txt}")
    if not parts:
        # 全员无题材条目 → 整行缺席，不留空头（AGENTS §1.2-8）
        return None
    return "题材热度：" + "；".join(parts)


def notice_count_line(entries: list[dict]) -> str | None:
    """公告计数行（2026-11-08e 纯语料补行，题面 hash 不动）：待判龙一公告/新闻/研报密度。

    `entries` = [{"label", "item": notice_item | None, "poolMissing": 原因|None}]；
    item 取自 `kpl_daban_pool.notice_items`（走 load_day(lane="notice")，operations 层取数），
    counts = {announcement, report, news}（GetCompanyCount 三计数）。

    口径纪律：
    - **信息量门槛**：公告或研报任一 ≥1 才有判读价值；后端取不到、全 0、或仅有新闻
      计数（上游噪声）→ **整行缺席**（AGENTS §1.2-8：缺数据/无信息量不投喂，
      不留一个字）；
    - **公告标题/正文不进叙事**（只出计数与上游数据日期；内容消费另行裁决）；
    - 部分计数缺位 → 缺位项「不可考」逐项带出（partial，不补 0）；
    - 计数统计窗口上游未标注：口径注只留 notice_items.window_note 结构化字段。
    entries 空 → None（调用方不出行）。
    """
    if not entries:
        return None
    label_cn = {"announcement": "公告", "report": "研报", "news": "新闻"}
    parts: list[str] = []
    for entry in entries:
        label = str(entry.get("label") or "").strip() or "该股"
        item = entry.get("item")
        # 信息量门槛：取不到/公告与研报均 <1 → 该股缺席，不占行（AGENTS §1.2-8）
        if not isinstance(item, dict):
            continue
        counts = item.get("counts") or {}
        core = [counts.get(k) for k in ("announcement", "report")]
        if not any(isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 1
                   for v in core):
            continue
        counts = item.get("counts") or {}
        segs: list[str] = []
        for key in ("announcement", "report", "news"):
            v = counts.get(key)
            segs.append(f"{label_cn[key]} {_heat_num_fmt(v)}"
                        if isinstance(v, (int, float)) and not isinstance(v, bool)
                        else f"{label_cn[key]}不可考")
        date_txt = str(item.get("upstream_date") or "").strip()
        if date_txt:
            segs.append(f"数据日期 {date_txt}")
        parts.append(f"{label}：{'/'.join(segs)}")
    head = "公告计数"
    if not parts:
        # 全员缺数据/无信息量 → 整行缺席，不留空头（AGENTS §1.2-8）
        return None
    return head + "：" + "；".join(parts)


def zt_gene_line(entries: list[dict]) -> str | None:
    """涨停基因行（2026-11-08a，用户需求）：待判龙一自身历史打板确定性画像。

    `entries` = [{"label": "主板龙一 000525", "item": gene_item | None}, ...]；item 取自
    `kpl_daban_pool.gene_items`（`load_gene_corpus` 读口，单一事实源）：
    {stock_id, gene{六字段}, raw, window_note, fetched_date, same_day}。
    - 回填条目（same_day=False，取值日晚于日档交易日 → 值含此后信息）作为数据事实
      最简带出；
    - 缺位/无该股语料/六字段全缺 → 该股**整段缺席**（AGENTS §1.2-8：缺数据不投喂
      「不可考」占位）；全部缺 → None（整行不出）。缺席状态只留 gene_items 落库字段。
    entries 空 → None（调用方不出行）。
    """
    if not entries:
        return None
    parts: list[str] = []
    notes: list[str] = []
    backfill_dates: list[str] = []
    backfill_codes: list[str] = []
    for entry in entries:
        label = str(entry.get("label") or "").strip()
        item = entry.get("item") or {}
        gene = item.get("gene") or {}
        # 信息量门槛：六字段全缺/无该股语料 → 该股缺席，不占行（AGENTS §1.2-8）
        if not any(isinstance(v, (int, float)) and not isinstance(v, bool)
                   for v in gene.values()):
            continue
        seg = "、".join(f"{cn}{_gene_num(gene.get(k))}{unit}"
                        for k, cn, unit in GENE_CN)
        parts.append(f"{label}={seg}" if label else seg)
        # 语料卫生红线（AGENTS §1.2-8）：口径注（统计窗口上游未标注等）不进叙事，
        # 只留在 gene_items.window_note 结构化字段；回填时点作为数据事实最简带出。
        if item.get("same_day") is False and str(item.get("fetched_date") or "").strip():
            backfill_dates.append(str(item["fetched_date"]).strip())
            backfill_codes.append(str(item.get("stock_id") or "").strip() or "该股")
    # 回填披露（值晚于交易日）：同一日期聚合一条，多日逐股点名（防误当该日盘后已知）
    if len(set(backfill_dates)) == 1:
        notes.append(f"数据时点 {backfill_dates[0]}，晚于交易日")
    elif backfill_dates:
        notes.extend(f"{code} 数据时点 {d}" for d, code in zip(backfill_dates, backfill_codes))
    head = "涨停基因（" + "、".join(dict.fromkeys(notes)) + "）" if notes else "涨停基因"
    if not parts:
        # 全员缺语料/全缺 → 整行缺席，不留空头（AGENTS §1.2-8）
        return None
    return head + "：" + "；".join(parts)


# ── 封板质量行（AMMO 2026-11-08b / 题集 v16，用户裁决「同步改题面判据」） ──
# 单一事实源 = kpl_daban_pool.items 的 2103 quotas 具名字段（DABAN_QUOTA_NAMES，已落库
# 零新采集）：[14]封单 / [18]最大封单 / [17]实际流通 / [16]实际换手 / [15]主力净额 /
# [7]成交额 / pool_state（sealed=当前封住、broken=曾入池掉出=炸板未回封）。
# 封单单位（元 vs 手）未与 App 逐列对照，且两假设在同一观测下**数学上不可分**
# （元比率 r1 与手比率 r2=r1×100×价 在低价股区间可同时落带，评审 2026-11-08 P1）→
# GetStockPanKou 实弹复核钉死单位前，只按元假设做带校验（App 封单列以亿展示、quotas
# 数值元惯例均指向元）：带内出行，带外只原样透出并标「单位待校验」，**禁猜换算**。
_SEAL_RATIO_BAND = (0.0005, 0.5)   # 0.05%~50%：容纳极端封单，越界即单位假设不成立
_SEAL_CLOSE_FRAME = "14:57"
# Asia/Shanghai 无夏令时（固定 UTC+8）→ 固定偏移即可确定性转换，不依赖 tzdata
_TZ_CN = timezone(timedelta(hours=8))


def _hhmm_from_ts(ts: Any) -> str | None:
    """epoch 秒 → Asia/Shanghai "HH:MM"；非数值/非正/越界 → None（调用方出不可考）。

    评审 2026-11-08 P2：超范围正值（如上游漂移成毫秒形态 1.7e12）或 NaN/Inf 会让
    datetime.fromtimestamp 抛 OverflowError/OSError/ValueError——退化「首板时点不可考」
    （§4.0 结构化降级），不得打挂整轮投喂。"""
    n = _qnum(ts)
    if n is None or n <= 0 or not math.isfinite(n):
        return None
    try:
        return datetime.fromtimestamp(n, _TZ_CN).strftime("%H:%M")
    except (OverflowError, OSError, ValueError):
        return None


def _seal_time_seg(item: dict) -> str:
    """首板/回封时点段（2026-11-08c 纯语料补行）：zt_time=首次涨停、last_zt_time=最后涨停。

    App 常态给 epoch 秒（2026-11-06 实测 33/33 数值）；历史若给 "HH:MM" 字符串则原样带出；
    两值都缺 → 不可考；last 早于首板属数据异常，显式标注不猜。
    """
    first = _hhmm_from_ts(item.get("zt_time"))
    if first is None:
        raw = str(item.get("zt_time") or "").strip()
        if re.fullmatch(r"\d{1,2}:\d{2}", raw):
            first = raw
    last = _hhmm_from_ts(item.get("last_zt_time"))
    if last is None:
        raw = str(item.get("last_zt_time") or "").strip()
        if re.fullmatch(r"\d{1,2}:\d{2}", raw):
            last = raw
    if first is None:
        return "首板时点不可考"
    if last is None:
        return f"首板 {first}"
    if last < first:
        return f"首板 {first}（时点异常：最后涨停早于首板，原始值 {last}）"
    if last > first:
        return f"首板 {first}（回封 {last}）"
    return f"首板 {first}"        # 早于此刻的采集帧不是收盘帧，封单仍在变动
# 涨停池语料整体缺失的降级原因 code（评审 2026-11-08 P1：读不到 ≠ 不在池，禁止伪装）
# 只随结构化返回透出，中文化映射已随语料卫生红线撤出叙事。


def _fmt_amount_yuan(val: float) -> str:
    """亿元串；<0.01 亿退化万单位（两位小数会把 50 万渲染成 0.00亿，非零显 0 是误导）。
    绝对值判门（review 2026-11-13f finding-3）：负额（竞价净额/大单净流出）同样退化/升级，
    避免同一行内正额 X.XX亿、负额 -NNNNN.N万 量级呈现不一致。"""
    if abs(val) >= 1e6:
        return _fmt_yi(val)
    return f"{val / 1e4:.1f}万"


def _fmt_ratio_pct(pct: float) -> str:
    """占比百分串：<1% 用两位小数（0.05% 被 .1f 渲染成 0.0% 同样是「非零显零」）。"""
    return f"{pct:.1f}%" if pct >= 1 else f"{pct:.2f}%"


def _qnum(v: Any) -> float | None:
    """quota 字符串 → float；不可解析/布尔 → None（不做缺位补 0）。

    不解析带「万/亿」后缀的字符串（实测 2026-11-06 日档 33 成员该七列全为数值形态）；
    若上游改形态会整项退化为「不可考」，fail-visible，不猜换算（评审 2026-11-08 P2）。"""
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def _yi_signed(v: float) -> str:
    """带符号亿元串（主力净额方向可读；与 jev_lhb_ammo._fmt_yi 同口径仅加符号）。"""
    return f"{v / 1e8:+.2f}亿"


def _raw_num(v: float) -> str:
    """原样数值串（单位未定时只用它，不套亿元量级，避免错量级误导）。"""
    return f"{v:.0f}" if abs(v - round(v)) < 1e-9 else f"{v:.2f}"


def _seal_unit(item: dict) -> tuple[str, float | None]:
    """封单口径自证 → (basis, 每原始单位的元系数)。

    basis：missing（无封单值）/ yuan（元假设落在合理带）/ unknown（元假设越界）/
    unverified（缺实际流通，无法校验）。
    单位候选只有元/手，但同一 (封单, 流通, 价) 观测下**数学上不可分**：元比率 r1=zt/rf
    与手比率 r2=r1×100×price 在低价股区间可同时落带（评审 2026-11-08 P1——单选手假设
    会输出放大 100×价 的伪封单额，单选元假设会把手真值低估 100×价 倍）。故在
    GetStockPanKou 实弹复核钉死单位前（预登记 v16 §3），只按元假设做带校验：
    带内 → 元口径出行；带外 → 「单位待校验」，不出任何派生比。复核若证明单位=手，
    本函数改返回 ("yuan", 100.0 * price) 一处即可，行文与下游零改动。
    """
    zt = _qnum(item.get("zt_tur"))
    if zt is None or zt <= 0:
        return ("missing", None)
    rf = _qnum(item.get("real_float"))
    if rf is None or rf <= 0:
        return ("unverified", None)
    if _SEAL_RATIO_BAND[0] <= zt / rf <= _SEAL_RATIO_BAND[1]:
        return ("yuan", 1.0)
    return ("unknown", None)


def seal_quality_line(entries: list[dict]) -> str | None:
    """封板质量行（2026-11-08b，题集 v16 判据引用源）：待判龙一当日封板量级。

    `entries` = [{"label": "主板龙一 名称", "item": pool_item | None,
                  "frameAt": "HH:MM" | None, "unsealed": bool}, ...]；item 取自
    `kpl_daban_pool` 日档 items（走 `load_day(lane="pool")`，由 operations 层取数）。

    口径纪律：
    - 封单单位（元/手）未与 App 逐列对照且两假设数学上不可分（评审 P1）→ 只按元假设
      带校验，越界只原样透出并标「单位待校验」，不出任何派生比；
    - 峰值为当日最大封单，「现为峰值 X%」直接可读衰减；峰值缺失不出；
    - 实际换手/主力净额/成交额各自独立缺失即不出该项（不补 0、不猜）；
    - pool_state=broken（曾入池后炸板未回封）→ 显式标注「最后封住帧」，防当下值误读；
    - 未封板龙一（断板反包候选，题面规则⑤）→ 明示本行不适用；
    - 采集帧早于收盘 → 标「非收盘帧」；各股帧不同 → 逐股标帧；
    - 首板/回封时点（2026-11-08c 纯语料补行，题面不动）：zt_time/last_zt_time epoch 秒
      → Asia/Shanghai HH:MM；回封时点仅在晚于首板时带出（=当日曾炸板回封的直读证据）；
    - poolMissing（涨停池日档整体缺失/读口异常）→ 「涨停池语料不可考（原因）」，
      **不**伪装成「今日不在涨停池」（后者仅用于档案存在且查无此股，评审 2026-11-08 P1）；
    - 峰值封单占实际流通超出 (0, 100%] → 视为口径自证未过，不出读数（评审 P2）。
    entries 空 → None（调用方不出行）。
    """
    if not entries:
        return None
    frames = list(dict.fromkeys(str(e.get("frameAt") or "").strip()
                                for e in entries if str(e.get("frameAt") or "").strip()))
    if not frames:
        head = "封板质量（时点不可考"
    elif len(frames) == 1:
        head = f"封板质量（{frames[0]}"
        if frames[0] < _SEAL_CLOSE_FRAME:
            head += "，非收盘帧"
    else:
        head = "封板质量（各股时点不同"
    head += "）"

    parts: list[str] = []
    for entry in entries:
        label = str(entry.get("label") or "").strip() or "该股"
        item = entry.get("item")
        unsealed = bool(entry.get("unsealed"))
        frame = str(entry.get("frameAt") or "").strip()
        # poolMissing（缺档/不在池归因）只随结构化落库载荷透出，不进叙事（AGENTS §1.2-8）
        if not isinstance(item, dict):
            if unsealed:
                # 今日未封板是判读事实（题面续板⑤），保留；缺档/不在池 → 整段缺席
                parts.append(f"{label}=今日未封板（无当日封单）")
            continue
        broken = str(item.get("pool_state") or "").strip() == "broken"
        if unsealed and not broken:
            # 评审 P2：推导侧（leaderSealedToday=False）与池档 sealed 矛盾时显式披露，不静默吞
            conflict = str(item.get("pool_state") or "").strip() == "sealed"
            txt = ("今日未封板（无当日封单）" if not conflict
                   else "今日未封板（无当日封单；池档仍标封住）")
            parts.append(f"{label}={txt}")
            continue

        segs: list[str] = []
        basis, mult = _seal_unit(item)
        zt = _qnum(item.get("zt_tur"))
        rf = _qnum(item.get("real_float"))
        # 信息量门槛（AGENTS §1.2-8）：不可考占位段不投喂，缺位项直接缺席
        if basis in ("yuan", "hand"):
            val = zt * mult
            seg = f"封单 {_fmt_amount_yuan(val)}"
            if rf is not None and rf > 0:
                seg += f"=实际流通 {_fmt_ratio_pct(val / rf * 100)}"
            segs.append(seg)
            mx = _qnum(item.get("max_zt_tur"))
            if mx is not None and mx > 0:
                mxv = mx * mult
                # 峰值复用同一 mult（同属封单族 quotas 列）；占实际流通超出 (0, 100%]
                # 物理不可能 → 口径自证未过，该段缺席不出读数
                if rf is None or rf <= 0 or (0 < mxv / rf <= 1.0):
                    segs.append(f"峰值封单 {_fmt_amount_yuan(mxv)}"
                                f"（现为峰值 {val / mxv * 100:.0f}%）")
        elif basis == "unknown" or basis == "unverified":
            # 「单位待校验」为题面 v16 判据引用的固定字样，不改写；缺实际流通为数据事实
            tag = "单位待校验" if basis == "unknown" else "单位待校验（缺实际流通）"
            segs.append(f"封单 {_raw_num(zt)}（{tag}）")
        time_seg = _seal_time_seg(item)
        if not str(time_seg).startswith("首板时点不可考"):
            segs.append(time_seg)
        rt = _qnum(item.get("real_turnover"))
        if rt is not None:
            segs.append(f"实际换手 {rt:.1f}%")
        mn = _qnum(item.get("main_net"))
        amt = _qnum(item.get("amount"))
        if mn is not None:
            seg = f"主力净额 {_yi_signed(mn)}"
            if amt is not None and amt > 0:
                seg += f"=成交额 {mn / amt * 100:+.1f}%"
            segs.append(seg)

        body = "；".join(segs)
        if unsealed and broken:
            frame_txt = f"（最后封住 {frame}）" if frame else ""
            parts.append(f"{label}=今日曾封后炸板未回封{frame_txt}"
                         + (f"：{body}" if body else ""))
            continue
        if not segs:
            # 无任何可读量价 → 该股缺席，不占行（AGENTS §1.2-8）
            continue
        if broken:
            frame_txt = f"最后封住 {frame}，" if frame else ""
            body = f"〔{frame_txt}其后炸板未回封〕{body}"
        if len(frames) > 1 and frame:
            body += f"〔{frame}〕"
        parts.append(f"{label}：{body}" if label else body)
    if not parts:
        # 全员无信息量 → 整行缺席，不留空头（AGENTS §1.2-8）
        return None
    return head + "：" + "；".join(parts)


def plate_strength_line(match: dict) -> str | None:
    """板块强度行（v12 G2）：KPL 层1 RealRankingInfo（`get_sector_ranking`，按日查史口径）。

    `match` 由调用方组装（取数/匹配一次，全板块共用）：
    - {ok: True, rank, total, name, strength, pct} → 当日排名/强度/涨幅；
    - {ok: False, ...} → **整行缺席**（AGENTS §1.2-8：缺数据不投喂占位，未匹配/异常
      状态只留结构化落库字段）。v1 为当日单点（序列扩展另行立项，预登记 §9）。
    """
    if not isinstance(match, dict) or not match.get("ok"):
        return None
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

    结构化状态（§4.0，不伪装、不插值、不给方向结论；2026-11-11 修复丢数据缺陷 +
    C 席位/机构兜底，用户裁决）：
    - 取数失败/双端点均不可用/当日分组榜单未生成且席位机构榜也无命中 → **整行缺席**
      （AGENTS §1.2-8：缺数据不投喂占位；缺席状态留 collect_lhb_facts 结构化降级载荷
      + doc.lhbState 落库留痕，A 2026-11-11）；
    - 主榜缺席但席位/机构榜相关个股命中 → 兜底事实行（C：只列席位买入/机构净买，
      主力资金/偏离/上榜额/上榜原因属主榜端点字段，缺位不伪装不出；不带全市场计数）；
    - 双端点均成功且 groups/stocks/席位/机构三源全空 → 「当日全市场无上榜个股」
      （验证后的缺席，一行事实）；注意：个股行端点失败但分组榜单在手**不是**无上榜，
      不得出本行（2026-11-11 前 ok=True+stocks 空会误称无上榜，把已取得的龙虎榜数据丢弃）；
    - 榜单已生成但相关个股 0 只上榜（含席位/机构榜也无命中）→ 显式披露 0 只（事实陈述）；
    - 有相关上榜 → 按传入 codes 顺序（龙一优先）列主力净额/买/卖（元→亿）与上榜原因。
    个股行缺位时分组榜单兜底（2026-11-11）：相关代码不在 stocks 时从 groups join
    （偏离/上榜额/分组原因，纯事实；主力资金字段个股行端点缺位，段内不伪装不出）。
    席位/机构扩维（2026-10-30c）：相关个股若在 GetStockList 营业部个股榜/GetAgencyListV2
    机构榜（同 facts 归一层，逐端点 fail-visible），追加「席位买入 X亿」「机构净买 X亿
    （N 家）」；不在榜/端点失败时该段缺席不伪装。机构净买可负（负=净卖出，如实呈现）。
    资金字段非数值一律「--」不伪装 0（复用 jev_lhb_ammo._fmt_yi 单一口径）；主力净额=
    盘中主力大单资金流，非交易所龙虎榜席位额（§13.3 task-3 裁决），行内标注防误消费。
    """
    from backend.analysis.hotlist.jev_lhb_ammo import _fmt_yi

    head = "龙虎榜："
    f = facts or {}
    stocks = [s for s in f.get("stocks") or [] if isinstance(s, dict)]
    # 分组榜单兜底（2026-11-11）：个股行端点失败/行被上游丢弃时，已取得的分组榜单
    # 不得丢弃——相关代码可从 groups join；主力资金字段该端缺位，段内只列已有事实
    groups_by_code: dict[str, dict] = {}
    for g in f.get("groups") or []:
        if not isinstance(g, dict):
            continue
        g_reason = str(g.get("reason") or "").strip()
        for s in g.get("stocks") or []:
            if not isinstance(s, dict):
                continue
            k = str(s.get("code") or "")[-6:]
            if k and k not in groups_by_code:
                groups_by_code[k] = {**s, "group_reason": g_reason}
    # 席位/机构兜底（C，2026-11-11 用户裁决）：主榜未生成/相关代码只在席位榜时，
    # 已取得的 GetStockList/GetAgencyListV2 事实不得丢弃——按 code join 出兜底段；
    # buy_in 缺位 = 无可读事实，不算命中（不伪装 0）
    sb = f.get("stock_board") or {}
    ag = f.get("agency") or {}

    def _seat_facts(k: str) -> tuple[dict | None, dict | None]:
        s, a = sb.get(k), ag.get(k)
        return (s if isinstance(s, dict) and s.get("buy_in") is not None else None,
                a if isinstance(a, dict) and a.get("buy_in") is not None else None)

    by_code = {str(s.get("code") or "")[-6:]: s for s in stocks if str(s.get("code") or "")[-6:]}
    ordered: list[str] = []
    for c in (codes or []):
        k = str(c or "")[-6:]
        if k and k not in ordered and (k in by_code or k in groups_by_code
                                       or any(_seat_facts(k))):
            ordered.append(k)

    def _seg(k: str) -> str:
        s = by_code.get(k)
        role = (roles or {}).get(k, "相关个股")
        sb_e, ag_e = _seat_facts(k)
        if s is None:
            g = groups_by_code.get(k)
            if g is None:
                # 席位/机构兜底段（C）：只列已取得的席位事实；主力资金/偏离/上榜额/
                # 上榜原因属主榜端点字段，缺位不伪装不出（§4.0）
                name = str(((sb_e or ag_e) or {}).get("name") or "") or k
                segs: list[str] = []
                if sb_e is not None:
                    segs.append(f"席位买入 {_fmt_yi(sb_e.get('buy_in'))}")
                if ag_e is not None:
                    jn = ag_e.get("join_num")
                    segs.append(f"机构净买 {_fmt_yi(ag_e.get('buy_in'))}"
                                + (f"（{jn} 家）" if jn else ""))
                return f"{role} {name}（{k}）：" + "；".join(segs)
            # 分组榜单兜底段：只有已取得的事实，主力资金段不出（§4.0 不伪装）
            name = str(g.get("name") or "") or k
            dev = g.get("deviation")
            seg = (f"{role} {name}（{k}）："
                   f"偏离 {dev if dev not in (None, '') else '--'}，"
                   f"上榜额 {_fmt_yi(g.get('amount_yuan'))}")
            reason = str(g.get("group_reason") or "").strip()
            if reason:
                seg += f"，上榜原因 {reason}"
        else:
            name = str(s.get("name") or "") or k
            buy, sell = s.get("main_buy_yuan"), s.get("main_sell_yuan")
            seg = f"{role} {name}（{k}）：主力净额 {_fmt_yi(s.get('main_net_yuan'))}"
            if buy is not None or sell is not None:
                seg += f"（买 {_fmt_yi(buy)} / 卖 {_fmt_yi(sell)}）"
            seg += f"，上榜原因 {str(s.get('reason') or '').strip() or '--'}"
        # 席位/机构扩维（2026-10-30c）：不在榜/端点失败时缺席，不伪装零（§4.0）
        if sb_e is not None:
            seg += f"；席位买入 {_fmt_yi(sb_e.get('buy_in'))}"
        if ag_e is not None:
            jn = ag_e.get("join_num")
            seg += f"；机构净买 {_fmt_yi(ag_e.get('buy_in'))}" + (f"（{jn} 家）" if jn else "")
        return seg

    if not stocks and not groups_by_code:
        if ordered:
            # 主榜缺席但席位/机构榜命中 → 兜底事实行（C，不带全市场计数断言）
            return head + "；".join(_seg(k) for k in ordered[:max_items])
        # 榜单未生成/取数失败 → 整行缺席（缺席状态留 collect_lhb_facts 结构化降级
        # 载荷 + doc.lhbState 落库留痕，A 2026-11-11）；
        # 「全市场无上榜」须三源全空（分组/个股/席位机构，C）
        if f.get("empty_structured"):
            return None
        if f.get("list_ok") and f.get("stock_ok") and not sb and not ag:
            return head + "当日全市场无上榜个股"
        return None
    if not ordered:
        total = len(set(by_code) | set(groups_by_code))
        return (head + f"当日全市场上榜 {total} 只，"
                "本叙事相关个股 0 只上榜")
    parts = [_seg(k) for k in ordered[:max_items]]
    return head + "；".join(parts)


# ── 上榜预测 / 实时龙虎榜行（2026-11-11 ③，2112/3004/3101 落库语料）──

def lhb_forecast_line(entries: list[dict], *, lane_ok: bool) -> str | None:
    """上榜预测行（2026-11-11 ③纯语料补行，题面 hash 不动）：2112 落库 fc_items 命中。

    `entries` = [{"label", "item"}]，item 取自 `kpl_daban_pool.fc_items`
    （fetch_lhb_forecast_corpus 归一产物）；口径纪律：
    - hot_val = **人气值**（2112 hotVal 列），与热度排名行 rank（排名）是不同口径，
      行文命名严格区分，不混用；
    - fc 无档/读口异常（lane_ok=False）→ 整行缺席；
    - 采集成功但相关个股 0 只命中 → 「0 只在预测榜」（验证后的缺席，一行事实）；
    - hot_val/hot_change/main_net_amount 逐项缺位不出该段，不补 0。
    """
    if not lane_ok:
        return None
    parts: list[str] = []
    for entry in entries:
        item = (entry or {}).get("item")
        if not isinstance(item, dict):
            continue    # 不在预测榜 → 该股缺席
        base_label = str(entry.get("label") or "该股").strip() or "该股"
        name = str((item.get("stock_name") or "").strip())
        seg = f"{base_label} {name}".strip() if name else base_label
        hot = item.get("hot_val")
        if isinstance(hot, (int, float)) and not isinstance(hot, bool):
            hc = item.get("hot_change")
            if isinstance(hc, (int, float)) and not isinstance(hc, bool) and hc != 0:
                seg += f" 热度 {hot:g}（{hc:+g}）"
            else:
                seg += f" 热度 {hot:g}"
        mn = item.get("main_net_amount")
        if isinstance(mn, (int, float)) and not isinstance(mn, bool) and mn != 0:
            seg += f" 主力净额 {_yi_signed(mn)}"
        parts.append(seg)
    if not parts:
        return "上榜预测：本叙事相关个股 0 只在预测榜"
    return "上榜预测：" + "；".join(parts)


def lhb_realtime_line(entries: list[dict], *, lane_ok: bool) -> str | None:
    """实时龙虎榜行（2026-11-11 ③纯语料补行）：3004/3101 落库 rt_items 命中板内成员。

    缺席语义（§4.0）：rt lane 采集成功且板内无命中 → 「无实时上榜记录」（验证后
    缺席，一行事实）；rt lane 无档（lane_ok=False）→ 整行缺席。rt_items 为 quotas
    原样数组（未破译缩放，单一事实源同 3001 约定）→ 命中段只列身位+股名，不渲染
    quotas 数值（不猜语义）。
    """
    if not lane_ok:
        return None
    parts: list[str] = []
    for entry in entries:
        item = (entry or {}).get("item")
        if not isinstance(item, dict):
            continue
        name = str((item.get("name") or "").strip())
        label = str(entry.get("label") or "").strip()
        parts.append(f"{label} {name}".strip() if name else (label or "成员"))
    if not parts:
        return "实时龙虎榜：无实时上榜记录"
    return "实时龙虎榜：" + "；".join(parts)


# ── 个股详情四通道叙事行（2026-11-11 ④，2014/2202/2030/2010 落库语料；mock 全绿，
#    实弹开火另走预登记 + 预算确认）──

def _bdo_stock_amounts(item: dict) -> tuple[float | None, float | None, float | None]:
    """2014 日档条目 → (封单额, 累计封板大单买, 累计封板大单卖) 元口径。

    消费次序：①采集侧尾条派生聚合 *_yuan（新日档）；②历史日档无派生字段 →
    items 尾条 raw 经 bdo_item_yuan 回退（与协议层同一换算出口/常量源，不造第二套）。
    raw sum 聚合（zt_tur/buy_tur/sell_tur）是级值/累计求和、语义无效，禁止消费。
    全缺 → (None, None, None)（fail-visible，不补 0）。
    """
    zt = _qnum(item.get("zt_tur_yuan"))
    buy = _qnum(item.get("buy_tur_yuan"))
    sell = _qnum(item.get("sell_tur_yuan"))
    if zt is None and buy is None and sell is None:
        for it in reversed(item.get("items") or []):
            if not isinstance(it, dict):
                continue
            y = bdo_item_yuan(it)
            if (y["zt_tur_yuan"] is None and y["buy_tur_yuan"] is None
                    and y["sell_tur_yuan"] is None):
                continue
            return y["zt_tur_yuan"], y["buy_tur_yuan"], y["sell_tur_yuan"]
        return None, None, None
    return zt, buy, sell


def zt_big_order_line(entries: list[dict]) -> str | None:
    """封板大单行（2014 封板大单明细聚合，补封板质量行静态快照之不足）。

    `entries` = [{"label", "item"}]，item 取自 kpl_daban_pool bdo_items（单股聚合，
    fetch_stock_detail_corpus 归一产物）。口径纪律（2026-11-11 实弹值校准裁决，
    证据链见 docs/kpl-socket/detail-scaling-verification.md）：
    - 封单/买卖拆分为**元口径**（2014 金额族=元×1，16/16 股尾条与池封单精确互证），
      亿/万自适应格式化（_fmt_amount_yuan）；
    - 值取**尾条最新态**（zt_tur=封单额级值、buy/sell_tur=当日累计封板大单买/卖，
      sum 无意义），换算单一出口=_bdo_stock_amounts；
    - 封单非正/不可读 → 该股缺席（不伪装有封单）；
    - buy/sell 缺位项「不可考」，不补 0；
    - 不渲染时间（time_text 已落库备审计，叙事禁开发注释 §1.2-8）。
    """
    if not entries:
        return None
    parts: list[str] = []
    for entry in entries:
        item = (entry or {}).get("item")
        if not isinstance(item, dict):
            continue
        zt, buy, sell = _bdo_stock_amounts(item)
        if zt is None or zt <= 0:
            continue
        seg = (f"{entry.get('label') or '该股'} 封单 {_fmt_amount_yuan(zt)}")
        if buy is not None or sell is not None:
            seg += f"（买 {_fmt_amount_yuan(buy) if buy is not None else '不可考'}"
            seg += f"/卖 {_fmt_amount_yuan(sell) if sell is not None else '不可考'}）"
        parts.append(seg)
    return "封板大单：" + "；".join(parts) if parts else None


def bf_reason_line(entries: list[dict]) -> str | None:
    """爆发原因行（2026-11-11 ④）：2202 BFReasonResp 爆发解析全文，与涨停原因行互补。

    desc 非空才出该股段；全部缺 → None（整行不出，涨停原因行已承载主因）。
    """
    if not entries:
        return None
    parts: list[str] = []
    for entry in entries:
        item = (entry or {}).get("item") or {}
        desc = re.sub(r"\s+", " ", str(item.get("desc") or "")).strip()
        if desc:
            parts.append(f"{entry.get('label') or '该股'}={desc}")
    return "爆发原因：" + "；".join(parts) if parts else None


def abnormal_price_line(entries: list[dict]) -> str | None:
    """异动提醒行（2030）：**next_day_zf 口径未钉死，整行暂停渲染**（2026-11-11 实弹值
    校准阴性）。

    2026-11-11 收盘日档 16/16 样本 price/nextDayPrice/nextDayZf 全缺位（当日异动
    事件推送只带 stockId+date），比率/百分比与 price 族缩放无对照样本可裁决。旧实现
    把 raw next_day_zf 直接按百分数渲染（`+X.XX%`）——若上游是比率即伪精度误导
    （fail-visible：不渲染未裁决口径；AGENTS §1.2-5 展示与结论同步）。恢复条件：
    下一交易日日档出现 price/next_day_zf 非空样本 → 被动复验钉死口径 → 按钉死口径
    切派生字段消费（复验路径见 docs/kpl-socket/detail-scaling-verification.md §二）。
    缺席纪律：raw 仍随 abn_items 落库，本行缺席 = 口径未裁决而非无数据。
    """
    return None


def related_plate_line(entries: list[dict]) -> str | None:
    """板块归属行（2026-11-11 ④）：2010 所属板块实时增量，题材热度行之外的新增板块。

    `entries` = [{"label", "item"（2010 解析产物，含 plates 列表）, "knownThemes":
    [题材库已投喂板块名], "board": 待判板块名}]。口径纪律：
    - 仅列主题板块之外的新增板块（plateName 与已知题材/待判板块去重，避免与
      题材热度行重复）；全部被剔/无条目 → None（不出行）；
    - plateIncRate/stockIncRate 可读才带百分比；涨幅贡献=个股涨幅（qzType 原样
      落库不渲染，语义未定不猜）。百分比口径 2026-11-11 被动交叉校准钉死
      （35/35 封板成分股与板别涨停幅吻合、266 板块值合理百分比带，见
      detail-scaling-verification.md §四），单一常量源 RPLATE_INC_IS_PERCENT；
      推翻时百分比段集体缺席（只列板块名，不伪精度）。
    """
    if not entries:
        return None
    parts: list[str] = []
    for entry in entries:
        item = (entry or {}).get("item") or {}
        plates = item.get("plates") or []
        known = {str(x).strip() for x in (entry.get("knownThemes") or []) if str(x).strip()}
        board = str(entry.get("board") or "").strip()
        if board:
            known.add(board)
        segs: list[str] = []
        for p in plates:
            if not isinstance(p, dict):
                continue
            pname = str(p.get("plate_name") or "").strip()
            if not pname or pname in known:
                continue
            inc = p.get("plate_inc_rate")
            sinc = p.get("stock_inc_rate")
            seg = pname + (f" {inc:+.2f}%" if RPLATE_INC_IS_PERCENT
                           and isinstance(inc, (int, float))
                           and not isinstance(inc, bool) else "")
            if (RPLATE_INC_IS_PERCENT and isinstance(sinc, (int, float))
                    and not isinstance(sinc, bool)):
                seg += f"（个股 {sinc:+.2f}%）"
            segs.append(seg)
        if segs:
            parts.append(f"{entry.get('label') or '该股'} " + "、".join(segs))
    return "板块归属：" + "；".join(parts) if parts else None


def market_summary_line(entry: dict | None) -> str | None:
    """15:00 收盘总结行（AMMO 2026-10-30e，用户指示）：当日盘面全市场介绍。

    `entry` = operations 层 `market_summary_entry(live_payload, date)` 产物（一次取数
    全板块共用）；本函数零 IO 零模型。None（无归档/非当日/无该条目）→ None 不出行
    （补充行缺席不伪装；直播可用性由 live_line 披露）。"""
    if not entry or not str(entry.get("comment") or "").strip():
        return None
    comment = str(entry.get("comment") or "").strip()
    if len(comment) > 600:
        comment = comment[:600] + "…"
    return f"盘面总结：{comment}"


def rebound_popularity_line(event: dict | None, pool_row: dict | None,
                            board_n: Any = None,
                            cycle: dict | None = None) -> str | None:
    """v14 人气证据链行组（AMMO 2026-11-02a，事件股专属，纯函数零 DB）。

    入参（全部已落地数据，零新采集；B3:A）：
      event     弱转强事件行（hotlist_jev_leader_wzs.events）；None → 非事件日
                不出行（调用方同时不判答本题，事件门同源）
      pool_row  观察池行（poolRows 按 code 匹配，含 windowChanges 窗内逐日 pct）
      board_n   当日板内上板家数（含龙头自身；None=不可考）
      cycle     周期背景（hotlist_jev_theme_cycle 当日行：state/cycleRound）
                只披露不进判档硬判据（预登记 §三）

    fail-visible：窗内序列/跟随数/周期背景缺位如实标注，不伪 0；缺位不自动
    insufficient（题面 ④：窗内序列与板块结构同时缺失才够档）。
    """
    if not event:
        return None
    form_cn = {"leaderRebound": "形式①人气股反包",
               "benchmarkAdvance": "形式②标杆晋级"}.get(str(event.get("type")),
                                                        str(event.get("type")))
    lines = [f"人气证据链（弱转强事件：{form_cn}，事件股=当日分轨空间龙一，"
             f"收盘封板确认）"]
    ev_bits = []
    if event.get("windowK") is not None:
        ev_bits.append(f"窗位 k={event['windowK']}")
    if event.get("height") is not None:
        ev_bits.append(f"断板日高度 {event['height']} 板")
    if event.get("streak") is not None:
        ev_bits.append(f"今日连板 {event['streak']} 板")
    if event.get("prevStreak") is not None:
        ev_bits.append(f"昨日 {event['prevStreak']} 板")
    if event.get("gain10") is not None:
        ev_bits.append(f"10日涨幅 +{event['gain10']}%")
    lines.append("事件事实：" + ("；".join(ev_bits) if ev_bits else "不可考"))
    wc = (pool_row or {}).get("windowChanges") or []
    if wc:
        seg = " → ".join(
            (f"{d.get('date')} {d.get('pct'):+.2f}%"
             if isinstance(d.get('pct'), (int, float))
             else f"{d.get('date')} 不可考")
            for d in wc)
        lines.append(f"窗内逐日表现（逆势观察，断板日起）：{seg}")
    else:
        lines.append("窗内逐日表现：缺失")
    if isinstance(board_n, int):
        lines.append(f"板内跟随：当日板内上板 {board_n} 家（含龙头自身）")
    else:
        lines.append("板内跟随：当日板内上板家数不可考")
    if cycle:
        st_cn = {"mainrise": "主升", "weakening": "转弱", "wzs": "弱转强",
                 "terminal": "终结"}.get(str(cycle.get("state")),
                                          str(cycle.get("state")))
        rnd = cycle.get("cycleRound")
        lines.append("周期背景：" + (st_cn or "不可考")
                     + (f"·第{int(rnd) + 1}轮" if isinstance(rnd, int) and rnd >= 1 else ""))
    else:
        lines.append("周期背景：不可考")
    return "\n".join(lines)


# v15 P1：题材周期状态机四态中文名——单一事实源导入 theme_cycle.STATE_LABELS_CN
# （review 2026-11-05 P2：状态机加新态时此处静默漏更会把已回填周期误标「不可考」）
from backend.analysis.hotlist.theme_cycle import STATE_LABELS_CN as CYCLE_STATE_CN


def structure_facts_line(row: dict, cycle: dict | None = None) -> str:
    """v15 P1（预登记 theme-leader-v15-seal-calibration-preregistration-20261104）：
    结构事实行——程序直读的强校准变量并列披露，随龙头叙事投喂。

    Q8:A 边界：行首「供校准参考 · 不作判据」标注已随语料卫生红线（AGENTS §1.2-8）
    撤出叙事。**v17 D5（用户批准）**：周期状态解禁为续板题调档佐证之一（转弱=降档
    佐证、主升=升档佐证，不得单独定档，仍须对锚）；其余三字段题面判据仍不引用、
    不仲裁档位，约束由题面与结构化记录承载。
    （原行首标注进语料属开发注释，浪费 token 且每次构建叙事都会重新堆积。）
    四字段（归因文档 §2 分判度排序头部）：周期状态（theme_cycle 当态，join 于 operations 层）/
    当日封板（False=断板反包候选，v12/v13 语义）/ 真连板高度 / 板内梯队家数。
    缺失字段显式「不可考」，不伪造不缺行（§4.0：fail-visible，行恒在）。
    """
    cycle = cycle or {}
    st_cn = cycle.get("stateCn") or CYCLE_STATE_CN.get(cycle.get("state"))
    parts = ["周期状态=" + (str(st_cn) if st_cn else "不可考")]
    sealed = row.get("leaderSealedToday")
    if sealed is True:
        parts.append("今日已封板=是")
    elif sealed is False:
        parts.append("今日已封板=否（断板反包候选）")
    else:
        parts.append("今日封板状态=不可考")
    streak = row.get("streak")
    parts.append("真连板高度=" + (f"{streak} 板" if streak is not None else "不可考"))
    ladder = row.get("ladderFollowers")
    parts.append("板内梯队=" + (f"{ladder} 家" if ladder is not None else "不可考"))
    # 全字段不可考 → 整行缺席（AGENTS §1.2-8：缺数据不投喂占位）；行恒在仅对
    # 「有任一字段在场」成立，全缺时不留一行字
    if all("不可考" in p for p in parts):
        return None
    return "结构事实：" + "｜".join(parts)


# ── v17 板块判定行 / 续板基础率锚行（AMMO 2026-11-12a，预登记 v17 §2.4）──
DEPTH_CHOICE_CN = {"igniting": "启动期", "fermenting": "发酵期",
                   "climax": "高潮期", "ebbing": "退潮期"}
CONTINUATION_CHOICE_CN = {"strong_extend": "强延续", "weak_extend": "弱延续",
                          "ending": "临近结束"}


def _conf_seg(conf: Any) -> str:
    """置信度段（数据括号，非开发注释）；非数/缺位不出段。"""
    if isinstance(conf, (int, float)) and not isinstance(conf, bool):
        return f"（置信{conf:.2f}）"
    return ""


def sector_judgment_line(sector_answers: dict | None) -> str | None:
    """v17：板块判定行——板块级 doc 深度/延续判答注入个股叙事（纯 join 零调用）。

    修复 v12 A2 拆题跨题引用悬空：空间题「综合前三题」与跨题一致性规则此前引用的
    判答在个股级调用中不可见；现由 operations 层 join 板块 doc answers（同轮缓存+
    库读兜底）随叙事投喂。纯数据事实，无开发注释（AGENTS §1.2-8）；insufficient/
    缺失判答不出该段，两段均缺 → 整行缺席（结构化 sectorJudgmentState 留痕）。
    板块级叙事自身不注入（不循环）。
    """
    if not isinstance(sector_answers, dict):
        return None
    parts = []
    depth = sector_answers.get("theme_speculation_depth") or {}
    if depth.get("choice") in DEPTH_CHOICE_CN:
        parts.append("炒作深度=" + DEPTH_CHOICE_CN[depth["choice"]]
                     + _conf_seg(depth.get("confidence")))
    contn = sector_answers.get("theme_continuation") or {}
    if contn.get("choice") in CONTINUATION_CHOICE_CN:
        parts.append("延续性=" + CONTINUATION_CHOICE_CN[contn["choice"]]
                     + _conf_seg(contn.get("confidence")))
    if not parts:
        return None
    return "板块判定：" + "；".join(parts)


def base_rate_line(stats: dict | None) -> str | None:
    """v17：续板基础率锚行——程序直算滚动注入（theme_leader_seal_stats.live_base_rate）。

    续板题先验底不再在题面写死率值（v15 锚 21.4% 窗口漂移教训）：数字单一事实源=
    本行，窗口随每日结算滚动。stats=None/无已结算样本 → 整行缺席（§1.2-8）；
    封板行/断板行子率仅在该组有样本时出段（缺数据不投喂占位）。
    """
    if not isinstance(stats, dict) or not stats.get("n"):
        return None
    seg = (f"续板基础率（live已结算{stats['n']}行，{stats.get('start')}~{stats.get('end')}）："
           f"总体{stats['ratePct']:.1f}%")
    subs = []
    for key, label in (("sealed", "封板行"), ("broken", "断板行")):
        grp = stats.get(key) or {}
        if grp.get("n"):
            subs.append(f"{label}{grp['ratePct']:.1f}%")
    if subs:
        seg += "；" + "／".join(subs)
    return seg


def build_leader_narrative(*, date: str, market_line: str, structure: str, baseline: str,
                           evidence_block: str, leader_name: str,
                           leader_code: str, headroom: str | None = None,
                           forward_axis: str | None = None,
                           market_summary: str | None = None,
                           ladder_line: str | None = None,
                           zhaban_line: str | None = None,
                           dt_line: str | None = None,
                           bid_line: str | None = None,
                           seal_quality_line: str | None = None,
                           zt_big_order_line: str | None = None,
                           driver_cross: str | None = None,
                           theme_heat_line: str | None = None,
                           related_plate_line: str | None = None,
                           reason_line: str | None = None,
                           bf_reason_line: str | None = None,
                           popularity_rank_line: str | None = None,
                           risk_line: str | None = None,
                           regulatory_line: str | None = None,
                           abnormal_price_line: str | None = None,
                           gene_line: str | None = None,
                           notice_count_line: str | None = None,
                           forecast_line: str | None = None,
                           lhb_facts_line: str | None = None,
                           realtime_lhb_line: str | None = None,
                           rebound_line: str | None = None,
                           plate_strength: str | None = None,
                           series_line: str | None = None,
                           live_line: str | None = None,
                           segment: str | None = None,
                           facts_line: str | None = None,
                           base_rate_line: str | None = None,
                           sector_judgment_line: str | None = None) -> str:
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
    排在打标交叉行后、证据块前；None 不出行。`notice_count_line`（2026-11-08e）= 公告计数行
    （notice_count_line 产出，取数单一源 kpl_daban_pool.notice_items），排涨停原因行后、
    龙虎榜行前；None 不出行。`lhb_facts_line`（AMMO 2026-10-30a）= 龙虎榜
    事实行（lhb_line 产出，取数单一源 jev_lhb_ammo.collect_lhb_facts），排在涨停原因行后、
    证据块前；None 不出行（未传入时旧行为不变）。
    `theme_heat_line`（2026-11-08d）= 题材热度行（theme_heat_line 产出，取数单一源
    kpl_daban_pool.theme_items），排打标交叉行后、基因行前；None 不出行。
    `gene_line`（2026-11-08a）= 涨停基因行（zt_gene_line 产出，取数单一源
    kpl_daban_pool.gene_items），排涨停原因行前、龙虎榜行前；None 不出行。
    `seal_quality_line`（2026-11-08b / 题集 v16）= 封板质量行（seal_quality_line 产出，
    取数单一源 kpl_daban_pool.items 的 2103 quotas 字段），属该股当日盘面量级事实，
    排板内炸板面行后、板块强度行前；None 不出行（旧调用形状不变）。题面续板⑦/空间⑥
    以本行为封板质量的唯一可量化判据源（v16 换代）。
    2026-11-11 语料缺口补全（题面 hash 零改动）：`dt_line`（板内跌停行，紧炸板面后）、
    `bid_line`（竞价承接行，紧炸板面后、封板质量前）、`zt_big_order_line`（封板大单行，
    紧封板质量后）、`related_plate_line`（板块归属行，题材热度后）、`bf_reason_line`
    （爆发原因行，紧涨停原因后）、`popularity_rank_line`（热度排名行）、`risk_line`
    （风险画像行）、`abnormal_price_line`（异动提醒行）、`forecast_line`（上榜预测行，
    公告计数后、龙虎榜前）、`realtime_lhb_line`（实时龙虎榜行，龙虎榜行后）；均 None
    不出行（缺数据整行缺席，AGENTS §1.2-8）。
    `facts_line`（v15 P1）= 结构事实行（structure_facts_line 产出：周期/封板/高度/梯队），
    校准参考行与锚行相邻：排在基线后、空间锚前；None 不出行（旧行为不变，板块级叙事不消费）。
    `base_rate_line`（v17）= 续板基础率锚行（base_rate_line 产出，取数单一源
    theme_leader_seal_stats.live_base_rate），排基线后、结构事实行前；None 不出行。
    `sector_judgment_line`（v17）= 板块判定行（sector_judgment_line 产出，板块级 doc
    判答 join），排结构事实行后、空间锚前；None 不出行（degraded/insufficient 整行缺席，
    结构化 sectorJudgmentState 留痕）。两新行均旧调用形状不变（不传=不出行）。
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
    if dt_line:
        # 2026-11-11 ②：板内跌停行（含「板内无跌停」验证缺席），紧炸板面后
        lines.append(dt_line)
    if bid_line:
        # 2026-11-11 ②：竞价承接行（「次日续板」题的前瞻承接证据），封板质量前
        lines.append(bid_line)
    if seal_quality_line:
        # 2026-11-08b（题集 v16）：封板质量行（该股封单量级/峰值衰减/换手/主力净额）；
        # 板面事实（结构/梯队/炸板面）之后给个股量级，None 不出行（旧行为不变）
        lines.append(seal_quality_line)
    if zt_big_order_line:
        # 2026-11-11 ④：封板大单行（2014，补封板质量静态快照之不足）
        lines.append(zt_big_order_line)
    if plate_strength:
        lines.append(plate_strength)
    if series_line:
        lines.append(series_line)
    if live_line:
        lines.append(live_line)
    lines.append(baseline)
    if base_rate_line:
        # v17：续板基础率锚行（先验底，程序直算随窗滚动；题面不再写死率值）
        lines.append(base_rate_line)
    if facts_line:
        lines.append(facts_line)   # v15 P1：结构事实行（程序直读；v17 D5 周期可作佐证、不得单独定档）
    if sector_judgment_line:
        # v17：板块判定行（板块 doc 深度/延续判答 join，修复 A2 跨题引用悬空）
        lines.append(sector_judgment_line)
    if headroom:
        lines.append(headroom)
    if driver_cross:
        lines.append(driver_cross)
    if theme_heat_line:
        # 2026-11-08d：题材热度行（KPL 题材库 2013 订阅），题材族聚拢——先摆当日题材
        # 归属与热度，再看历史基因与当日原因；None 不出行（旧行为不变）
        lines.append(theme_heat_line)
    if related_plate_line:
        # 2026-11-11 ④：板块归属行（2010，题材热度之外的新增板块）
        lines.append(related_plate_line)
    if gene_line:
        # 2026-11-08a：涨停基因行（历史打板画像），排涨停原因行前——先摆「这只股的
        # 历史打板确定性」，再看当日原因；None 不出行（旧行为不变）
        lines.append(gene_line)
    if reason_line:
        lines.append(reason_line)
    if bf_reason_line:
        # 2026-11-11 ④：爆发原因行（2202，与涨停原因行互补）
        lines.append(bf_reason_line)
    if popularity_rank_line:
        # 2026-11-11 ①：热度排名行（2203 rank 族，全市场排名口径）
        lines.append(popularity_rank_line)
    if risk_line:
        # 2026-11-11 ①：风险画像行（减持/解禁/质押/风险提示）
        lines.append(risk_line)
    if regulatory_line:
        # 2026-11-15：监管风险行（KPL 严重异动/重点监控，交易所级监管事实）
        lines.append(regulatory_line)
    if abnormal_price_line:
        # 2026-11-11 ④：异动提醒行（2030，次日涨幅偏离实况）
        lines.append(abnormal_price_line)
    if notice_count_line:
        # 2026-11-08e：公告计数行（公告/研报/新闻密度，事件/风险画像），排涨停原因行后、
        # 龙虎榜行前；None 不出行（旧行为不变）
        lines.append(notice_count_line)
    if forecast_line:
        # 2026-11-11 ③：上榜预测行（2112 fc_items，人气值口径）
        lines.append(forecast_line)
    if lhb_facts_line:
        lines.append(lhb_facts_line)
    if realtime_lhb_line:
        # 2026-11-11 ③：实时龙虎榜行（3004/3101 rt_items）
        lines.append(realtime_lhb_line)
    if rebound_line:
        # v14（P3 工作流 B）：人气证据链行组，事件股专属；仅事件日出行，
        # 与本题判答条件（事件门）同源。None（非事件日）不出行，旧行为不变
        lines.append(rebound_line)
    lines.append(evidence_block)
    return "\n".join(lines)


def build_sector_narrative(*, date: str, market_line: str, structure: str, baseline: str,
                           evidence_block: str, board: str,
                           forward_axis: str | None = None,
                           market_summary: str | None = None,
                           ladder_line: str | None = None,
                           zhaban_line: str | None = None,
                           dt_line: str | None = None,
                           popularity_rank_line: str | None = None,
                           risk_line: str | None = None,
                           regulatory_line: str | None = None,
                           forecast_line: str | None = None,
                           lhb_facts_line: str | None = None,
                           realtime_lhb_line: str | None = None,
                           plate_strength: str | None = None,
                           series_line: str | None = None,
                           live_line: str | None = None,
                           reason_line: str | None = None) -> str:
    """板块级叙事（v12 A2 拆题：深度/延续题每板块一次，预登记 §2.3）。

    与个股级叙事差异：头部「待判板块」，结构行=双龙一并列（structure_line_dual）；
    基线行以第一轨（main 优先）龙一为参照行（分轨锚缺位如实，历史窗人群不随规则换代）；
    **不含**空间锚行（空间题不在板块级子集）与个股打标交叉行（个股轴归各自龙头叙事，
    板块级以涨停原因行提供带动证据关键词）。`lhb_facts_line`（AMMO 2026-10-30a）= 龙虎榜
    事实行（双龙一 + 板内封板成员代码过滤），排在涨停原因行后、证据块前；None 不出行。
    2026-11-11 语料缺口补全（题面 hash 零改动）：`dt_line`（板内跌停行，板级事实）/
    `popularity_rank_line`/`risk_line`（双龙一并一行）/`forecast_line`/`realtime_lhb_line`；
    None 不出行。顺序固定，便于逐字复现与回归比对。
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
    if dt_line:
        # 2026-11-11 ②：板内跌停行（板级事实，与炸板面同族）
        lines.append(dt_line)
    if plate_strength:
        lines.append(plate_strength)
    if series_line:
        lines.append(series_line)
    if live_line:
        lines.append(live_line)
    lines.append(baseline)
    if reason_line:
        lines.append(reason_line)
    if popularity_rank_line:
        # 2026-11-11 ①：热度排名行（双龙一并一行）
        lines.append(popularity_rank_line)
    if risk_line:
        # 2026-11-11 ①：风险画像行（双龙一并一行）
        lines.append(risk_line)
    if regulatory_line:
        # 2026-11-15：监管风险行（双龙一+板内成员 scope）
        lines.append(regulatory_line)
    if forecast_line:
        # 2026-11-11 ③：上榜预测行
        lines.append(forecast_line)
    if lhb_facts_line:
        lines.append(lhb_facts_line)
    if realtime_lhb_line:
        # 2026-11-11 ③：实时龙虎榜行
        lines.append(realtime_lhb_line)
    lines.append(evidence_block)
    return "\n".join(lines)
