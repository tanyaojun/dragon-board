# 题材龙头链 v13 预登记：未封板场景 insufficient 误答修复（2026-10-29）

> **状态**：**正式预登记（2026-10-29 用户批准换代，同日落地）**。原草案门槛（攒样本
> ≥30 题次再立项）由用户指示提前 supersede——首批程序口径 16 题次 2 空档（12.5%）
> 与人工实证方向一致，批准直接换代；`scripts/theme_leader_unsealed_insufficient_audit.py`
> 保留为 v13 验收基线监视器（验收目标：empty_with_evidence 率 <5%，v12 基线 12.5%）。
> **换代戳**：`QUESTION_SET_VERSION_THEME_LEADER = "v13"`，hash `5d50645e5dc8`
> （v12 `4255eb9f5a46` 降历史参照，跨代不可比）；AMMO 原料代际不变（2026-10-28b）。
> 本批零 jev 调用；真实重跑走 16:20 定时槽挂链（新题面自动生效），三案定向复评按
> `jev-crowding-score-reevaluation.md` 流程另行预登记 + 预算确认。
> **触发实证（2026-10-28 首批）**：15 行中 3 行空档——上海九百续板 P39、大业/华阳空间
> P23/P29；三行证据实际在场（基线行按昨日承接 prev3+ 76.5%、空间锚总体 21.1%），
> 模型把题面「锚缺失如实对待」读成了 insufficient 许可。3 行为设计内诚实空档，不复跑。
> **上游**：`theme-leader-v12-dual-leader-preregistration-20261028.md`（§9.8、§3 题面 v12）。

## 1. 问题定义与归因

**问题**：未封板场景（`leaderSealedToday=False`，断板反包候选）下，模型在证据在场时仍答
insufficient——本批率 3/15（20%）。

**归因（按 §1.6 顺序，题目设计为主因）**：

1. **续板题规则⑤是正向句无反向禁令**：「未封板龙一通常没有同构历史锚，此时以证据为主，
   锚缺失如实对待、不得编造基准」——只说了「以证据为主」，没有说「证据在场时禁止
   insufficient」；模型把「无同构锚」套进 ③「关键证据缺失必须判 insufficient」的字面。
2. **空间题规则③对未封板股无默认档落点**：默认档按「当日连板高度」分（1-3 板→peak、
   4+→space_1），断板候选当日高度不可算 → 无默认档 → insufficient 成为最「安全」输出；
   「空间锚」行在场（总体 21.1%）但 ② 未被接线为未封板分支的起判锚。
3. **insufficient 判据全是缺失类条件、无对称禁令**：v12 刚给深度/延续题加了「贫料≠断流」，
   续板/空间两题没有同款（同构缺口，非新问题类型）。
4. 协议层（次因）：choice 型无 reason 落库，模型自述 insufficient 理由不可程序对账
   （v12 预登记 §5 同款），只能靠题面约束 + 事后锚行核对兜底。

## 2. 修法（v13 题面，已落地，hash `5d50645e5dc8`）

### 2.1 续板题（leader_nextday_continue）规则⑤尾部补

> 「锚缺失如实对待**不等于**可判 insufficient：只要叙事中结构基线行（含任一出率桶）、
> 承接行、梯队行、题材证据任一在场，就必须按规则①对齐中枢给档；此时锚缺失仅要求
> **降低置信**（confidence ≤0.6），不得以『无同构历史锚』作为 insufficient 理由。」

`criteria.insufficient` 补对称禁令：「未封板场景：结构基线行有任一出率桶时不得选本档」。

### 2.2 空间题（leader_headroom）规则③补未封板分支

> 「连板高度不可算时（含待判龙头今日未封板的断板反包候选）默认档按「空间锚」最细
> 出率桶起判（无按高度细分则用总体行，如总体再走≥1板率不足三成 → peak 侧起判）；
> 锚行同样必须先对齐，偏离仍须按 ② 点名锚行数字并给锚外新证据；锚行整体缺席（叙事无
> 空间锚行）才允许按证据自判，且此时若为未封板场景 confidence ≤0.6」
>
> （review P2 措辞对齐 2026-10-29：落地措辞为「高度不可算」超集表述、「不足三成」
> 与 peak 判据锚行读数同源，替代草案期硬编码 21.1% 示例；引文=题面原文。）

`criteria.insufficient` 补：「叙事含空间锚行（有率值）时不得选本档」。

### 2.3 置信强制降档（两题通用）

未封板 + 无同构锚场景：题面显式要求 confidence ≤0.6（评估侧可对账 confidence 分布，
验证降档生效，不靠自觉）。

### 2.4 不扩范围

跨题一致性（v12 规则③）、板块级两题、AMMO、叙事、读口**零改动**——纯题面换代
（`QUESTION_SET_VERSION_THEME_LEADER = "v13"`，`_questions_hash` 随之变更）。

## 3. 攒样本协议（本批即生效，零 jev、纯库内）

- **可程序判定口径**（review P2 备注：仅统计 `status="ok"` doc——排除 degraded/证据门强制档，
  避免 gate 强制 insufficient 污染计数；此为对 §3 口径的显式增项）：leader doc（`docKind="leader"`、`questionSetVersion="v12"`、
  `structure.leaderSealedToday=False`）中 `answers.leader_nextday_continue.choice` 或
  `answers.leader_headroom.choice == "insufficient"`，且对应叙事行在场——
  续板题=narrative「结构基线」行含任一出率桶（`率 \d+(\.\d+)?%`）；
  空间题=narrative「空间锚」行含率值 → 记 `empty_with_evidence`。
- **审计脚本**：`scripts/theme_leader_unsealed_insufficient_audit.py`（只读零写入零 token），
  16:20 挂链跑批后或人工随时可跑。
- **立项门槛（三档）**：
  - 样本 ≥30 个「未封板-题次」且 `empty_with_evidence` 率 **≥10%** → v13 正式立项开火；
  - 率 **<5%** → 不立项（首批 20% 属小样本噪声），本草案归档；
  - 5%~10% 或样本 <30 → 再攒一周复核。
- 首批 3/15（20%）在样本 ≥30 前不单独定论。
- **库内程序复核（2026-10-29，审计脚本首批产出）**：v12 未封板 leader doc 共 8 条；
  `empty_with_evidence` = 2 题次（均为 2026-10-28:600838 上海九百，续板+空间双题，
  结构基线行/空间锚行率值均在场）→ 题次率 12.5%；§9.8 的「3/15（含大业/华阳空间
  P23/P29）」为人工盘点口径，库内核对大业 head=peak（非 insufficient）——两口径差异
  如实记录，转正式预登记时以程序口径为准重新核数。当前判：**样本不足（16 题次 <30），
  继续攒**。

## 4. 预算与验收（生效）

- 本批落地零 jev 调用；真实重跑走 16:20 定时槽挂链（新题面自动生效），
  或按 `jev-crowding-score-reevaluation.md` 流程预登记 + 预算确认后定向复评三案
  （上海九百/大业/华阳同型场景）。
- **验收窗**：v13 上线 ≥60 个股级样本（未封板场景单列），按代际分组：
  ①`empty_with_evidence` 率 <5%（对照 v12 基线由审计脚本产出）；②未封板行 confidence
  中位数 ≤0.6 且显著低于封板行（降档生效）；③对账：insufficient 行全部满足
  「基线+锚行均无率值」的结构化条件。

## 5. 影响文件（已落地 2026-10-29）

| 文件 | 内容 |
|---|---|
| `backend/analysis/hotlist/theme_leader_ammo.py` | 题集 v12→v13（§2.1/§2.2/§2.3 三处措辞）、版本常量、代际注释 ✅ |
| `tests/hotlist/test_theme_leader_ammo.py` | v13 hash 冻结回归 + 新措辞判据文本回归 ✅ |
| `tests/operations/test_theme_leader_label.py` | 落库 version/hash 断言同步 v13 ✅ |
| `scripts/theme_leader_unsealed_insufficient_audit.py` | 已就绪（v12/v13 通用，验收监视器）✅ |
| 读口/前端 | 无改动（choice 枚举不变） |
