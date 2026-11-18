# 跨源口径核查与修复：天普停牌案 + 阳光照明末封案（2026-11-18）

> 状态：**已实施**（用户裁决「1/2/3 项确认请修复；4 项请给出方案」）。
> 范围：theme_leader / sector_nodes / driver / relay 四链共享口径层；零 jev 真调、零业务库写入（核查全程只读）。
> 归因顺序遵 AGENTS §1.2-6：①原料/源供给 → ②题目 → ③协议/解析 → ④方案。两案均归因①原料层，非模型错误。

## 1. 核查对象与结论速览

| # | 现象 | 归因 | 处置 |
|---|---|---|---|
| F1 | 天普股份 605255「断板反包·今日未封 ?」（11-16/17） | **停牌日线上伪棒**致 `day_status_of` 误判 broken；theme 叙事/relay 回退把停牌伪装断板反包候选 | 已修复（单源链） |
| F2 | 阳光照明 600261「炸板 0 次 · 末封 15:00」同行自相矛盾 | `board_shape_line_from_bars` 末封=末根收盘封住棒（封板至收盘恒 15:00），非末次封板事件 | 已修复 |
| F3 | 阳光「封板 10:38:19」vs「首触 10:40」 | **非 bug**：TDX 5 分钟棒末时刻标记（当日首棒 09:35 实证）+ 分钟粒度；10:38:19 ∈ (10:35,10:40] 棒 | 「棒」字自明口径（随 F2 同代） |
| F4 | 阳光 ∈ THS 名单（37/51）但 ∉ KPL daban 池（77，pages 完整） | 两源人口口径差（THS 涨停 vs KPL daban）；theme sealed←THS、封板质量←KPL，既有冲突分支+poolMissing 覆盖 | 登记观察，不动 |

## 2. F1 证据链与根因（天普 605255）

**库内只读实证**（`dragon_board_quant`）：
- `hotlist_jev_theme_leader_labels` 11-16/11-17 档**同档自相矛盾**：
  - 监管风险行：「严重异动2026-11-16 **停牌** 预计复牌2026-11-19 重点监控」（jiuyan 监管语料源）
  - 结构行：「今日未封板（**断板反包候选**，10 日涨幅 +54.0%）」＋封板质量「无当日封单」
- 节点档 `2026-11-16/17:SECTOR_NODES` 半导体 leader：`poolDay=2026-11-13, days=4, boards=4, dayStatus=broken`（**dayStatus 本身错**）。
- TDX 日线：11-10~11-13 四连板（收盘=涨停价逐日核验），**11-16/17 本地无棒**。

**根因（单源层下沉）**：`bars_need_upto(date)` 线上补尾对停牌日注入**伪棒**——
实测 11-17 棒 `close=73.82（平收=前收）, amount=5.877e-39（≈0 垃圾值）, volume/open/high/low=null`。
`_bar_verdict` 见「有棒未封」→ broken → `day_status_of` broken → 节点台账 broken →
theme 叙事「断板反包候选」＋ relay 断徽章。**v4「停牌不算断板」裁决在单源层被伪棒击穿**，
下游各链（streaks/relay/node/theme）同受污染。

** '?' 与徽章机制**：relay `ldState` 旧回退 `leaderSealedToday===false → 'broken'`
（旧档分辨不了停牌/数据洞与断板）→ 断徽章＋「断板反包候选」tooltip；高度位 poolDay
台账在场（11-13）但旧回退口径整体复活废弃语义。

**jev 影响**：v18 规则⑤键控「今日未封板（断板反包候选）」短语 → 停牌股被按重新上板
分支判答（今日无交易、个股下一交易日＝复牌日 11-19 ≠ 市场轴 11-18）——错误前提。
gain10 +54% 为 11-13 陈旧值无截至披露。

## 3. 修复链（单源，禁双实现）

1. **`jev_label_jiuyan._bar_verdict`**：成交额 `amount < 1.0` 元（含 ≈0 垃圾值）＝无连续
   竞价交易 → 按无棒判 suspended（A 股真实成交额恒 ≥ 千元级；amount=None 不在此列，
   维持宁缺毋猜）。`day_status_of` 全消费方（真连板回溯/relay 晋级链/节点/theme）同受益。
2. **`operations/sector_nodes.settle_day`**：`leaderSealedToday` 改由 `dayStatus` 三态映射
   `{sealed:True, broken:False, suspended/unknown:None}`（旧池二分 bool 退役）；
   `reanchor_dragons` 披露条件 `is False` → `is not True`（三态同款）。
3. **`theme_leader_label.leaders_for`**：节点档带 dayStatus（新代）→ 续断/区间高度
   （dayStatus/leaderSealedToday/poolDay/days/boards）以**节点单源**覆盖 day_leader_rows
   池二分 bool；旧代节点档无 dayStatus → 不覆盖（历史口径不变）。
4. **`theme_leader_label.run`**：复牌日单源＝监管语料（`load_regulatory_corpus`，与监管
   风险行同源），仅 suspended 行携带 `resumeDate`（缺则不可考，不伪造）；选取按
   abnormal_date 最大（≤date）的最近停牌记录，不依赖上游列表顺序（review M2）；
   结算锚日解析对非 ISO 日期串按不可考 pending，不击穿整日结算（review M3）。
5. **叙事四分支**（`theme_leader_ammo`）：`_leader_brief` / `structure_line` /
   `seal_quality_line` / `structure_facts_line` 增 suspended/unknown 分支——
   「今日停牌（预计复牌 X）」「今日续断不可考」＋gain10 事实日期截至披露「（截至 {poolDay}）」
   （红线清洁后口径：不带口径注/数据洞注，见 v19 预登记 §3）；**不进入「断板反包候选」措辞**（规则⑤天然不触发）。
6. **`leader_wzs`**：龙一行合并保留三态 None（不 coerce False）；事件流 truthy 门天然排除；
   反包窗只对确判断板（is False）开，停牌/数据洞龙一行不开窗不算窗内序列（review M1，与成员分支同口径）。
7. **relay `renderNodes`**：旧档无 dayStatus 回退**仅 sealed 可推**（true/streak 在场），
   其余一律 unknown（? 徽章 fail-visible）——不得从 false 推 broken 复活废弃口径；
   高度位 tooltip 状态感知（停牌/数据洞/未封三分）。
8. **doc 结构化载荷**：structure 增 `dayStatus/poolDay/days/boards/resumeDate`（审计/前端，
   不进叙事，§1.2-8）。

## 4. F2/F3 修复（driver 板型）

- `last_seal`＝**末段连续封住 run 起始棒**（末次封板/回封事件）：waves0→首封棒；
  waves≥1→末次回封棒；收盘未封→末段 run 起始棒。旧口径封板至收盘恒 15:00（零信息量＋
  误导尾盘封板弱读法），waves≥1 同样吞掉回封时点。
- 首触/末封加「棒」字自明口径（TDX 5 分钟棒**末时刻标记**，当日首棒 09:35 实证；
  与 THS/KPL 事件时间表观差 ≤5 分钟属粒度约定非数据错）。「棒」是数据事实非开发注（§1.2-8）。
- 首触（high 触板口径）/炸板波次/板型分类阈值零改动。

**实数据复算验证**（只读，零 jev 调用）：
- 天普 11-16/17 `day_status_of` → **suspended** ×2 ✓
- 阳光 11-17：`当日板型：首触棒 10:40 · 炸板 0 次 · 末封棒 10:40 · 封板至收盘 · 板型=一波封住（首触偏晚）` ✓ 自洽
- 天普叙事分支：`主板龙一 天普股份（605255）今日停牌（预计复牌 2026-11-19），10 日涨幅 +54.0%（截至 2026-11-13）`；
  结构事实「今日已封板=停牌（无交易）」；封板质量「今日停牌（无交易）」✓

## 5. 代际影响与验证

| 链 | AMMO | 题集/hash | 说明 |
|---|---|---|---|
| 题材 | 2026-11-18b → **2026-11-18d** | **v19 / `96949f5a00fd`**（v18 `8f7f97a4680a` 留档） | 叙事三态分支＋事实日期截至披露；v19 停牌分支＋投喂文本红线清洁（预登记 theme-leader-v19-suspension-branch-preregistration-20261118） |
| 涨停 driver | 2026-10-22b → **2026-11-18a** | v4.0 / hash **不变** | 末封语义+棒字口径（原料层） |
| 竞价 | 2026-11-18b → **2026-11-18c**（jj_percent 换源 AMMO 补记，见 vA5 文档补记/review M4） | **vA6 / `f945412269fd`**（vA5 `fb671c8f0223` 留档） | 共享题源随题材 v19 清洁被动换代（未首烧零代际成本） |
| 节点 | 确定性零 token | v5（不变） | dayStatus 三态映射；历史档回填=另裁决（见 §7） |

- 域内测试：**2335 passed / 7 skipped / 0 failed**（tests/hotlist + operations + api，含 v19 与红线清洁回归）。
- 新增回归 24 项（`test_seal_caliber_fix_20261118.py` 14＋`test_theme_v19_suspension_branch.py` 10）：伪棒三态/触板名单数据洞/amount=None
  旧口径/真棒 broken、末封事件棒三场景、叙事三态+复牌日缺省不伪造+hygiene 全块黑名单、
  节点单源合并+旧档不覆盖、wzs None 保留；节点 settle 参数化扩 suspended/unknown 三态断言。
- 跨代/跨 AMMO 分段评估；历史档不 force 重跑。

## 6. 第 4 项：v19 停牌分支（用户裁决 A，**已实施**，首烧待预算）

**问题**：原料层修复后停牌股不再被标反包候选，但续板/硬度题目前提仍失效——停牌股
「下一交易日」＝复牌日（个股轴）≠ 市场下一交易日；v18 题面无停牌分支，模型按一般前提
判答（市场轴），语义错位仍在。

| 方案 | 内容 | 代价 | 评估 |
|---|---|---|---|
| **A（推荐）** | v19 题面增停牌分支：叙事标「今日停牌」时，续板类题＝**复牌日**重新上板概率（锚=复牌日，判据引用叙事复牌日披露）；硬度/空间题按停牌前口径+复牌不确定性起判；options 不变 | 换代 v19（hash 重算）+预登记+预算确认；跨代 Brier 分段 | 语义正解；与 v4「停牌不算断板」裁决同轴 |
| B | 停牌股当日跳过打标＋结构化留痕（suspendSkipped） | 零题面改动；样本损失（停牌股观察缺席，fail-visible 披露） | 保守兜底；丢失复牌前观察窗 |
| C | 维持现状＋观察层低置信桶标记 | 零改动 | 误判风险留存，不推荐 |

**推荐 A 的执行路径**：
1. **零调用取证**（随时可跑）：`python -m backend.cli jev-low-confidence --start 2026-11-16 --end 2026-11-17`
   观察 v18 历史档停牌股（天普）答位置信分布，作 v19 预登记的题面层误判证据。
2. v19 预登记文档（题面逐字+判据引用+options 不变声明+hash 重算）→ **协作者会签**
   （题集属协作者 v18 域）→ 用户预算确认 → 首烧。
3. 预算：首烧＝当日全量龙头（~40 股×6 题）一次；历史档不重跑；跨代分段 Brier。
4. 触发条件：本轮天普案已构成原料层误判实证；题面层误判以步骤 1 观察+首烧对照确证。

## 7. 遗留登记（观察/后续裁决）

- **wzs 观察池成员分支**：✅ 已闭环（2026-11-18 续）——ops `collect_materials` 以
  `day_status_of` 单源取齐 `member_states`（仅池权威日计算，adj=None 零外呼；池缺失日
  保持旧二分＋degraded）；analysis 成员三态行（None/dayStatus/不开反包窗/窗内序列缺席）；
  首板高度门/跌停门顺序不变；旧调用无 member_states 保持旧口径。叙事零变更（成员不进
  叙事，事件流 truthy 门天然排除）→ AMMO/题面 hash 不动。
- **limitup 链消费面**：✅ 已闭环——limitup 读口透传 `dayStatus`；relay 涨停表连板列
  三态留空＋披露 tooltip；情绪周期锚徽章 停/? 显式（`cycleAnchorCell`）；梯队表旧档
  无 dayStatus 中性口径「续断不可考（旧档无 dayStatus）」（不得误标今日未封板）；
  读口投影守卫测试（tests/api/test_three_state_projection.py）。
- **market_cycle 锚三态**（同源扩展）：`compute_anchor` 改 `day_status_of` 单源
  （≤2 只锚股取 bars，节制；dict→list 转换 `_bars_list_of`）；锚 dayStatus 落库＋
  cycle series 投影透传。
- **实数据探针**（只读节制 13 只成员股）：11-16/11-13 池成员于 11-17 三态判定
  broken/sealed 全正确（实棒 amount=None 属正常喂数形状，不误判停牌）；本窗成员停牌
  稀有，停牌路径由伪棒夹具＋天普龙一实案同决策表证明。
- **节点/wzs 历史档回填**：day_status_of 伪棒修复影响全历史停牌股 streaks/节点
  dayStatus/wzs poolRows（确定性零 token 可回填）——是否回填=另裁决（历史 theme/driver
  档不重 firing）。
- **F4 两源人口差**：THS 涨停名单 vs KPL daban 池人口口径差登记观察（既有冲突分支+
  poolMissing 披露覆盖 theme leader 场景）。
- **pseudo-bar 哨兵扩展**：amount<1 元阈值仅治「平收伪棒」；若未来出现非平收伪棒
  （vendor 异常），按 §1.2-6 先抓帧再扩哨兵，不预设。

## 8. 协调与提交边界

- 修复跨 theme（v18 域）/driver（v4.0 域）/node/relay 四链——用户已裁决确认实施；
  题集 v19（§6）属协作者域，预登记需会签，本轮**不动题面**。
- 改动文件：`jev_label_jiuyan.py` / `sector_nodes.py`(ops) / `theme_leader_label.py` /
  `theme_leader_ammo.py` / `jev_driver_ammo.py` / `leader_wzs.py` / `relay_page/index.html` /
  `auction_leader_ammo.py`(vA6) / `schedule.py` / `scripts/theme_leader_pilot_eval.py`
  ＋测试 8 文件（新增 2＋更新 6）＋docs 4（新增 2＋补记 2）。
- 验证命令：`.\.venv\Scripts\python.exe -m pytest tests/hotlist tests/operations tests/api -q`。
