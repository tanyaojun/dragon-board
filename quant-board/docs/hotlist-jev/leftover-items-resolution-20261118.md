# 遗留待办项裁决与实施（2026-11-18）

> 状态：已实施（平台 reason feature request 经官网查证**关闭 won't-do**，架构性排除，见 §3.3）。
> 裁决：用户 2026-11-18「采纳全部建议，请实施」+「待办项从官网找资料再定方案」→「采纳」。
> 前序：西陇/广百两案审计 → v18/vA5 修复（`theme-leader-v18-questionset-corpus-fix-20261118.md`、
> `auction-leader-vA5-questionset-corpus-fix-20261118.md`，commit c83c6d23）→ 本轮六项遗留处置。
> 代际：**题面 hash 不变**（v18 `8f7f97a4680a` / vA5 `fb671c8f0223`，本轮全部为原料层/观测层，
> 非判据层）；AMMO 两链 `2026-11-18a` → **`2026-11-18b`**（题材证据块渲染变化）。

## 1. 处置总表

| 项 | 处置 | 类 |
|---|---|---|
| B9 产业树节点错配（「大消费-酒」↔百货零售） | Fix-1/2/3/4 实施 | 原料层修复 |
| C1 平台 reason schema | 协议层查实 + 零调用质量观测 + **官网查证关闭 feature request（架构性排除）** + 官方公式增强 | 观测层 |
| 题材 B7 直播缺席行 | **保留关闭** | 裁决保护 |
| 题材 B8 单维桶 | **保留关闭**（设计消费非闲置） | 设计消费 |
| 竞价 B7 推送行 | **保留关闭** | 三重消费 |
| 竞价 A2 路线① derive 补时点 | **关闭（被 vA5 路线②取代）** | 语义诚实 |

## 2. B9 产业树节点错配（theme_event_digest.py）

### 2.1 库内实锤（只读核对，2026-11-17 广百案）

- 树有真催化：`零售百货`（level 1，正文 69 字，2026-10-20 发改委发布会新闻，hot -2.28）；
  `大消费-零售百货`（level 2）及全部子节点为残桩（正文 4-7 字自复述，`_is_stub_content` 门内）。
- 广百 ∈ `大消费` 成分快照（84 成员，batchDate 2026-10-25）；`零售百货` L1 **无成分快照**。
- 错配三层根因：
  1. 首通道 contains 命中全部 `大消费-*` 子节点（level=2/hot=0.0 全同）→ 旧版按名字最短取
     「大消费-酒」（5 字）——**纯排序伪影**，与个股业务无关；
  2. `_TAG_SPLIT_RE` 不含 `；;。：:` → expound 首行「零售；据2026年半年报」粘成不可匹配整块，
     「零售」永远切不出来（KPL expound 通用格式）；
  3. S3 只试 `pool[0]`：即使切出「零售」，level 优先取 L1 `零售百货` → 无快照 →
     `skipped_unverifiable` → 换词，**同词其他候选永不尝试**。

### 2.2 四项修复（确定性，无语义别名）

- **Fix-1**：`_TAG_SPLIT_RE` 增 `；;。：:`（字符级分隔，非语义分词）。
- **Fix-2**：`match_industry` 增返 `candidate_nodes`（pool[:5] 全量）；S3 改**候选级迭代门**——
  同词全部候选独立过门（残桩/成分，不连坐），首个过门即注入停止（只补最优先一个，旧语义）。
- **Fix-3（门语义拆分，用户裁决）**：`not_member`（验明不在，蹭标签）**维持阻断**
  （2026-11-14 大东方裁决不动）；`unverifiable`（快照缺席）改**披露式注入**（§4.0 暴露不阻断）：
  叙事行带「成分未核验」数据事实标注（与「未证实」来源可靠性标注同类，非开发注），
  `s3State="injected_unverifiable"` 结构化留痕，模型自行降权。广百案效果：L1 `零售百货`
  真催化（发改委新闻）披露式注入，硬度题从贫料变有料。
- **Fix-4（首通道同档 tie-break tag-aware，用户裁决）**：仅当 (level, hot) 同档多候选 tie 时，
  优先龙头驱动标签词子串命中的候选（`_tag_aware_pick`，与 S3 同确定性匹配哲学）；
  **level/hot 有差异时排序有意义不覆写**（睿能宽父节点案，2026-10-30d「并列披露不替换首通道」
  设计不变）。广百案首通道改渲染「大消费-零售百货」无催化正文（诚实残桩缺席行），
  「酒」误导名消除；`tagPreferredTerm` 结构化留痕。
- **残桩缺席行违禁词修复（review P2 闭环，并入本代）**：2026-11-14 既有行
  「板块级催化：产业树**节点**「X」无催化正文」含「节点」（hygiene FORBIDDEN 表内，
  当时漏网无测试覆盖）→ 删词保义改「产业树「X」无催化正文」（缺席事实不变，
  §1.2-8 强制合规非语义重设计）；趁 2026-11-18b 未首烧并入，零额外代际成本。

### 2.3 边界与登记

- 残桩门（`_STUB_CONTENT_CHARS=10`）不变；`hasContent`/三层缺失门口径不变。
- `零售百货` L1 无成分快照属上游周频 batch 覆盖缺口（fail-visible 由 s3State 暴露）；
  若未来快照补齐，广百类案自动升级 `injected`（验明）无需改码。
- 披露式注入的权衡如实登记：unverifiable 节点内容可能与龙头业务弱关联（大东方无快照案
  会注入商业航天叙事+「成分未核验」标注）——裁决取 §4.0「暴露不阻断」，模型按标注降权，
  人工抽检走 C1 投影；若后续实证误判率上升，回退路径=恢复 unverifiable 阻断（git 回退，
  不建平行开关）。
- 前端同步核对（§1.2-5）：`s3State`/`成分未核验` 于 quant-board/frontend 与根 src 零命中
  （叙事原文展示，结构化字段无前端消费），新枚举值 fail-visible 透传不阻断。

## 3. C1 平台 reason schema（协议层查实 + 替代审计）

### 3.1 协议层归因（§1.2-6 ③，先查原料与题目再查协议）

- 请求体 `{"model":"typesafe/jev","input":{"state","questions"}}`（`jev_client._call_primary`）——
  **answer schema 由平台决定，无客户端 schema 参数**，不能自行加 reason 字段。
- 解析层 `answers = inner["answers"]` **整体透传零丢弃**（`parse_jev_response`）；
  ops 层 `answerReasons` 接收位已就绪（「平台放开零改动接住」注释属实）。
- 结论：解析层无辜，平台侧 schema 限制。

### 3.2 实施：零调用判答质量观测（`backend/operations/jev_answer_quality.py`）

- `low_confidence_report(db, date_start, date_end, threshold)`：读两 label collection
  status=ok 档，用**已落库** probabilities 重算 max_prob/top2 margin（不信任存储 confidence），
  `max_prob < 0.6` 入观察桶；按 `questionSetHash` 代际分段（跨代不可比），同 hash 跨 AMMO 代
  `ammoVersions` 聚合；degraded 档不进统计（其本身已 fail-visible）。
- 阈值 0.6 校准起点：西陇 hard_fact 0.57、广百封板 mid 0.50 均捕获（审计实证）；
  阈值仅人工抽检分流**非判据**，调整不需要换代。
- CLI：`python -m backend.cli jev-low-confidence [--start --end --threshold]`（on-demand
  全扫描，千级 doc，非盘中链路）；零 jev 调用（§1.2-7）、不写库、不进叙事（§1.2-8）。
- 判答质量不可审计 ≠ 不可观测：三分撕裂/低置信概率分布本身暴露失效。

### 3.3 官网查证：feature request 关闭（won't-do，架构性排除）

2026-11-18 用户裁决「从官网找相关资料再定方案」→ 查证 docs.typesafe.ai 后关闭原
「向平台提 reason 字段 feature request」待办——**不是缺失功能，是产品核心架构排除**：

| 证据 | 原文 |
|---|---|
| [System One 概念页](https://docs.typesafe.ai/concepts/system-one) | 「System One models **do not write replies, produce code, or generate explanations of their reasoning**.」 |
| [API Reference](https://docs.typesafe.ai/api)（完整封闭 schema） | 请求仅 `{model, state, questions{type,instructions,criteria}, assets}` + 2 个 danger-zone header；响应仅 `{model, answers{choice/probabilities/confidence…}, usage}`——无 reason 字段、无输出 schema 参数、无解释性开关 |
| [Model jaggedness #9](https://docs.typesafe.ai/model-jaggedness) | 「Jev is not trained to generate text. While you can force it to by chaining choices, **this will not work well and will be very slow**… If you really need to generate text… there are other models for that.」 |
| [Changelog](https://docs.typesafe.ai/changelog)（jev-1.14.0, 2026-10-14） | Box/图像/长上下文/多语言——无解释性特性、无路线图信号 |

官方可解释性路径＝**题目分解 × 概率分布形状 × 代码侧组合**（非模型生成文本）。
提 reason 字段请求等于要求厂商违背核心架构，关闭。原「不做」三项维持（二次解释
调用 2x 成本/换模型断代际/删引用义务降判定质量）。

### 3.4 C1 增强：官方公式对齐（2026-11-18 采纳，零调用零代际）

[Confidence 页](https://docs.typesafe.ai/confidence)验证现有设计并给增强点：

- ✅ max_prob 主阈值＝官方推荐「For a Choice, [threshold on] the probability of the
  option your code will act on」；margin＝官方 top-to-second「Many real decisions
  come down to the top two candidates」；低置信→人工抽检＝官方三档路由
  「Low confidence: Do not act. Route to a human」。
- 🔧 行级补 `nOptions` + 官方 Choice confidence `(p_max−1/n)/(1−1/n)`（均匀=0、
  单峰=1、n=1 定义=1、畸形 p_max<1/n 钳 0、回退档 None 不编造）。官方明示：
  定 n 下 confidence 是 p_max 单调变换**无独立证据**，只作跨题可比报告量
  （n 无关同尺度）；主阈值仍 max_prob。
- 🔧 代际补 `questionOptions` 每题选项数披露（同题跨 doc n 不一致 → sorted list
  fail-visible），为**按题校准阈值**铺路（官方「set its threshold per question」；
  实测披露 2026-11-17 两链选项数 4/5/6（trial_settlement_pattern 6 档），共用 0.6
  是粗粒度观察起点——官方：0.5 在 2 档是弱答在 10 档是强答）。调阈值非判据变更不需换代。
- 测试冻结官方 worked examples：3 档 (0.6,0.3,0.1)→0.4；2 档 0.75→0.5；
  10 档 0.55→0.5（跨题同尺度）；均匀→0；n=1→1。
- 纯报告层：题面 hash/AMMO/落库载荷/前端不动。CLI 透传全报告 JSON 零改动。

### 3.5 登记：两个官方背书审计工具（可选，需预登记+预算，不自动执行）

1. **选项顺序敏感性探针**（[jaggedness #8](https://docs.typesafe.ai/model-jaggedness)：
   「Jev leans toward the option that comes first… Reorder the options and check the
   answer is consistent」）：同 state + criteria 重排 → 答案一致性核对，专捕顺序
   伪影判答（我们 criteria 是 dict 插入序，硬度题 hard_fact 恒首位——潜在偏置可
   实证）。2× 调用/探针 → 只走预登记+预算确认开火路径（§1.2-7）。
2. **Companion Noul 证据在场题**（[patterns/companion-noul](https://docs.typesafe.ai/patterns)
   + jaggedness #5）：审计关键题旁挂 Noul「state 是否含支持 X 的证据」→ 无文本的
   证据在场信号。改题集 → 换代+预登记+预算；登记为未来设计选项不实施。

### 3.6 现有设计的官方验证清单（加固既有裁决）

| 我们的纪律/设计 | 官方依据 |
|---|---|
| 原子四题分解、代码侧组合 | 核心哲学「Atomic questions, composed in code」 |
| 程序直读计数/日期/算术（排名/封单/桶/时点） | jaggedness #2「count in code」/ #3「arithmetic in code」 |
| 档位用 Choice 不用 Score 插值 | #2「do not use score outputs to compute exact magnitude between levels」 |
| 语料精简（西陇 −9.3%/广百 −15.1%） | #5「Accuracy falls as the state grows with content unrelated to the decision」——精简是精度手段不只是省钱 |
| 叙事禁判据指引/开发注释（§1.2-8） | #6 adversarial content：「text that argues for its own classification can move the answer」——判据指引入语料＝官方定义的 steer 污染 |
| v18 硬度①字面精确化 + ①×⑤正交 | #1「that explanation is the missing half of the instruction」/ #7「criteria as extension of instruction, align」 |
| degraded 不入库、低置信观察桶 | 「"I don't know" is a useful signal」+ 三档路由 |

## 4. 关闭项（保留现状，理由登记）

- **题材 B7 直播缺席行**（「当日无X相关播报」）：~15 字符；2026-11-10 用户裁决保护的
  验证缺席例外行（缺席是事实）；G1 接入覆盖审计痕。删需新裁决，负 ROI，关闭。
- **题材 B8 单维桶**：`baseline_line` docstring 明载 2026-10-24c 补单维桶就是给 verylow
  判据「家数少+封板晚+无梯队」三维度量化依据；组合桶是联合率，判据点名单维——**不冗余**。
  7 段 ~220 字符是量化锚代价。微优化（combo 在场删连板高度单维）省 ~30 字但动锚人群
  → AMMO 换代+评估分段，低 ROI 不做。关闭（设计消费非闲置）。
- **竞价 B7 推送行**：三重消费——vA1 入选源合法性证据 + 身位题证据清单点名「09:15 推送
  概念/涨幅」+ 推送 +9.91%（实时芯片）与序列首帧 +10.04%（竞价快照）是**不同观测**，
  差值是封板 ramp 信息（与形态③试盘/09:25 背离同哲学）。压缩抹掉被消费字段，关闭。
- **竞价 A2 路线① derive 补时点**：**被 vA5 路线②取代关闭**。路线②已诚实覆盖观测需求
  （末帧代理 conf≤0.6 + hard_oneword 零量共证）。补 start/end 会把观测帧伪装成 canonical
  试盘语义（代码警示：观测≠委托簿试盘）：序列末帧 09:24:53 不是结算，canon=True 会让模型
  按「09:25:00 全匹配」主锚档判 hard_oneword 而无结算实据 → 系统性过度自信。真 canonical
  唯一路径 = direct-probe 预登记（`auction-trial-direct-probe-preregistration-20261116.md`，
  App 同屏核对，§4.3 L2 能力边界），保持登记。

## 5. 验证

- 新增/更新回归：B9 四测试（unverifiable 披露注入/候选级迭代/广百端到端/tie-break 边界）
  + 切词 ；案 + 大东方 not_member 阻断回归保持绿 + 睿能首通道不替换保持绿；
  C1 三测试（代际分段/阈值边界/日期过滤/confidence 回退/空库）。
- `tests/hotlist + tests/operations + tests/api`：见提交说明（域内全绿）。
- 全量 pytest：用户裁决「不用跑全量，专项测试通过就可以」，以域内套件为准。
  工作区含所有者并行 relay v11 WIP（非本轮改动，不触碰不混入提交）；提交态
  relay 保持 v10 自洽（stamp 测试仅暂存本轮 AMMO hunk，relay v11 断言留工作区）。
- 零 jev 真调；hygiene 黑名单绿（「成分未核验」为数据事实标注，非开发注）。
- AMMO 冻结断言两链同步 2026-11-18b；题面 hash 冻结断言不动。
- **独立 review 闭环**（reviewer fresh-context 只读，run 902acdf6）：无 blocker；
  major-1（S3 行族 hygiene 零覆盖）已补 member/unverifiable 两变体全块黑名单测试；
  minor-1（s3Term/s3Node 审计错配）赋值与 state 记录同步（state 归因候选）+回归；
  minor-2（CLI 阈值双源）parser default 改引模块常量；nit（docstring）已补；
  既有 P2（残桩行「节点」违禁词）并入本代修复（见 §2.2）；补测暴露 NaN 漏洞已修
  （math.isfinite 守卫，bool/非数/NaN 全跳过不编造）。
- **待核闭环（Fix-1 垃圾成词误匹配边界）**：父会话只读全表扫描 jiuyan_ai_industry
  1004 节点，广百案垃圾片段（「据2026年半年报」「公司从事百货零售」等）双向 contains
  **零命中**；含数字节点名（3D打印/12英寸/GLP-1 等）均为合法技术词，与垃圾片段无交集。
  风险有界（残桩门+成分门+披露标注+单注入 break+limit=3）；「含数字长片段」确定性
  过滤登记为未来裁决项（仅实证误判时启用，本轮不加）。
- **官网查证轮（2026-11-18 采纳）**：C1 行级 nOptions/官方 confidence + 代际
  questionOptions 披露；官方 worked examples 冻结测试 + 跨题同尺度/畸形钳 0/回退档
  None/不一致 fail-visible 断言；题面 hash/AMMO/落库载荷/前端零改动（纯报告层）。

## 6. 可比性

题面 hash 不变 → v18/vA5 判据代际延续；AMMO 2026-11-18a → 2026-11-18b 分段（原料供给变化：
S3 注入面扩大+首通道节点选择变化），Brier/验收按 AMMO 代际各自累计。B9 修复预期硬度题
贫料场景 sector_story/insufficient 分布漂移（真催化注入），按代际观察不跨代合并。
