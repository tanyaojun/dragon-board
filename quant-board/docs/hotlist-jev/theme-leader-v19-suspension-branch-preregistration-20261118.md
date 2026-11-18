# 题材龙头 v19 预登记：停牌分支＋投喂文本红线清洁（2026-11-18）

> 状态：**已实施，首烧待预算确认**（本轮零 jev 真调，§1.2-7）。
> 裁决链：跨源口径核查 F1-F3 修复（用户「1/2/3 确认请修复」）→ 第 4 项方案 A（用户「A,请实施」）
> → 投喂文本红线清洁（用户「你违反了开发语义和版本号不能进叙事的红线」「搜停牌分支」）。
> 代际：题材 **v18 → v19**，hash `8f7f97a4680a` → **`96949f5a00fd`**；AMMO `2026-11-18c` → **`2026-11-18d`**。
> 竞价联动：**vA5 → vA6**，hash `fb671c8f0223` → **`f945412269fd`**（共享题源被动清洁，vA5 未首烧零代际成本）。
> driver / relay 题集零变动。跨代不可比，Brier/验收按代际分段。

## 1. 问题与取证

原料层修复后（见 `seal-caliber-cross-source-audit-fix-20261118.md`），停牌股叙事不再标
「断板反包候选」，但**题面层前提仍错位**：停牌股「下一交易日」＝复牌日（个股轴）≠ 市场
下一交易日；v18 题面无停牌分支，模型按市场轴判答续板/人气题。

**零调用取证**（`backend.cli jev-low-confidence --start 2026-11-16 --end 2026-11-17`）：
v17 代（`eb9cfae4139e` / AMMO 2026-11-17b）天普 605255 两题均低置信 flagged——
`leader_catalyst_hardness` sector_story maxProb 0.38 / confidence **0.1733**；
`leader_nextday_continue` low_25_45 maxProb 0.53 / confidence **0.4125**。
n=2 仅方向性信号；原料层误判（停牌被喂成断板反包候选）已实锤，题面层错位以首烧对照确证。
11-16/17 档为 v17 代（v18 尚未首烧），历史档不重跑。

## 2. 题面变更（六处，options 零改动）

判据锚变更，档位集合冻结（回归测试逐题断言 criteria keys）：

| 题 | 新增条款（清洁后原文摘要） |
|---|---|
| leader_nextday_continue | ⑤叙事标注待判龙头**今日停牌**时：本题=**复牌日**重新上板概率（复牌日以叙事「预计复牌 X」披露为准；市场轴次一交易日该股无交易，不得作判答锚）；封板质量/封板时间/竞价判据不适用，改按停牌前事实（10 日涨幅截至日披露/截至最近封板日的连板高度）、板内炸板面/昨日仍封数、板块判定行与题材证据；复牌日不可考按停牌前事实+复牌不确定性判并 confidence ≤0.6；基线/承接/梯队/题材证据任一在场必须按①给档，不得以「无同构历史锚」判 insufficient |
| leader_headroom | ⑥叙事标注今日停牌时：空间以**停牌前高度**（截至最近封板日连板高度）起判，锚行按①映射；复牌不确定性作降档佐证；不得仅因停牌判 peak，也不得仅凭停牌前连板高度判 space_2plus |
| leader_catalyst_hardness | ⑤叙事标注今日停牌时：判**最近一次涨停（停牌前）**驱动事实的催化硬度，证据窗以叙事披露的截至日为准，不得因当日无涨停判 insufficient |
| leader_seat_durability | ⑤叙事标注今日停牌时：身位按停牌前梯队/热度事实判；停牌本身既非被替代事实也非核心位巩固事实，复牌不确定性可作被挑战佐证 |
| leader_rebound_popularity | ⑥叙事标注今日停牌时：本题=**复牌日**反包的人气聚合成色（复牌日收盘封板确认；窗内逐日表现按停牌前事实）；不得以停牌日（无交易）封板事实判 dragon_confirm/one_day_pop；复牌日不可考 confidence ≤0.6 |
| theme_continuation | 个股停牌非板块断板事实：叙事标注龙一今日停牌时，不得将该股计为断板/反包信号或龙头分歧证据（停牌无交易，停牌不算断板） |

theme_speculation_depth（板块级）不动。键控措辞＝叙事「今日停牌」（原料层三态分支产出，
单一事实源 dayStatus）；非停牌叙事不触发任何新条款（v18 语义逐字保留于非停牌路径）。

## 3. 投喂文本红线清洁（用户 2026-11-18 裁决，同批零代际成本）

**红线**：开发语义与版本号禁入投喂文本（叙事＋题面 instructions＋criteria 全量）。

1. 题面/判据版本号全删：题材遗留 `（v6 收紧）/（v6 收窄）/（v12 修订）/（v12）/（v13）`
   与本轮新增 `（v19）`/「停牌分支」开发标签一律清除（语义保留，只删标签）。
2. 叙事口径注改**数据事实**：gain10 截至披露改事实日期 `（截至 {poolDay}）`（poolDay=
   最近封板日，缺则后缀缺席）；「今日续断不可考（日线数据洞）」→「今日续断不可考」；
   封板质量 unknown 分支「（无当日封单佐证）」→「（无当日封单）」（既判例外措辞同款）；
   结构事实「=不可考（日线数据洞）」→「=不可考」。停牌/预计复牌日期/无交易＝数据事实保留。
3. **程序性门禁**（`tests/hotlist/test_narrative_hygiene.py`）：`_assert_clean` 增版本号
   形态正则 `（v\d+…）` 与 `\d{4}-\d{2}-\d{2}[a-z]`（纯日期是数据事实不在禁列）；FORBIDDEN
   增「停牌分支/语料源/新增监管/零新增/日线数据洞/停牌前口径/截至最近可用日线」；
   v19 回归对七题 instructions+criteria 全量扫版本号/开发标签。
4. 四链投喂文本扫描全清洁（theme/auction/driver/relay；历史遗留仅存于代码注释/docstring，
   注释不进投喂）。relay/driver 题集零变动（若未来其投喂文本出现标签，门禁测试即红）。

## 4. 结算锚同步（零 token，确定性）

题面锚改复牌日，结算必须同锚（否则复牌日判答被市场轴结算误判未封）：

- `scripts/theme_leader_pilot_eval.py::evaluate`：`structure.dayStatus=suspended` 档
  锚＝`_resume_anchor_date`（resumeDate 起含首个交易日且 >date）；`outcomeMeta` 增
  `anchorKind`（resume/market_next）+`resumeDate` 留痕（结构化，不进叙事）；复牌日
  不可考/不在交易日轴/池缺失 → outcome=None pending（fail-visible，不猜市场轴）。
  旧档 structure 为字符串（历史形状）→ 市场轴口径不变。
- `settle_day2`：T+2 溢价按**逐档锚**（outcomeMeta.nextDate）推导；复牌轴 T+2 未到 →
  逐档 pending 自愈；市场轴口径不变。
- `backend/operations/schedule.py::_theme_settle_days`：结算目标日＝近 lookback 交易日
  ∪ 停牌 pending 日（长停牌复牌锚超 lookback 不丢自愈），上限 60 约束 subprocess 批量。
- 非停牌档全链路逐字不变（回归断言 market_next 口径）。

## 5. 预算与首烧（待用户确认）

- 首烧＝当日全量龙头个股 call（~40）＋板块级 call（~10-15），**≈50-55 calls 一次**；
  需用户显式预算确认后开火（§1.2-7 预登记+预算路径）。
- 历史档不重跑；v19 与 v18/v17 跨代分段 Brier；竞价 vA6 首烧另按竞价预登记预算。
- 观察层：`jev-low-confidence` 按 questionSetHash 分段观察停牌股答位置信分布；
  复牌日不可考分支 confidence ≤0.6 门由题面约束＋观察层核验。

## 6. 验证

- 域内 **2335 passed / 7 skipped / 0 failed**（tests/hotlist + operations + api）。
- 新增回归：`tests/operations/test_theme_v19_suspension_branch.py`（10 项：六题分支在场＋
  options 冻结＋投喂文本门禁＋复牌锚四场景＋day2 逐档锚＋长停牌自愈并入/上限）；
  `test_seal_caliber_fix_20261118.py` 19 项（原料层三态/末封事件棒/叙事事实日期/hygiene）。
- 实数据只读复算：天普 11-16/17 suspended ×2；阳光末封棒 10:40 自洽（前轮）。

## 7. 协调与遗留

- 题集属协作者 v18 域：用户裁决 A 授权实施；**协作者会签待补记**（首烧前完成）。
- 遗留继承审计 doc §7：~~wzs 非龙一停牌成员分支~~、~~limitup 表三态显示~~（均已闭环，
  含 market_cycle 锚三态同源扩展）；节点/wzs 历史档回填（另裁决）、F4 两源人口差观察。
- 截图监管行 changelog 头（「2026-11-18c 新增监管语料源…」）在当前工作区代码/git 全历史/
  库内叙事均不存在（rg -uu 全仓＋git log -S --all＋四集合 narrative 扫描）；当前
  `regulatory_risk_line` 只产数据事实。若该显示仍现于页面，来源为**陈旧运行进程内存态
  或他实例**——重启 backend/relay 进程后复核；门禁已防本仓再犯。
