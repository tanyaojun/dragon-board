# 板块节点 V4-E 预登记：日内量能锚（30 分钟帧级，提示层）— 2026-11-01

> 状态：**已批准实施**（用户 2026-11-01 从 A/B/C 三案中拍板 **A**）。
> 本代际为**提示层扩展**：不进节点判定、不改收盘档、无改档面——与 V2c §六
> 「提示列不进节点判定」冻结延续一致。

## 一、背景与动机

V4 条款 2（量能注记透出）落地时已确认：**日线级量能对隔日弱转强人群无判别性
分离**（合计量比 wzs 1.03 vs 对照 1.00；成员级量比中位 wzs 0.96 vs 对照 0.89；
mainline 1.14 低于发酵·冒头 1.25），两个改档候选全部数据否决（见
sector-nodes-v4-criteria-preregistration.md 否决记录表）。

用户 2026-11-01 重定位：目标是**日内弱转强**（盘中发现翻红），日线量能天然测
不到「盘中翻红瞬间是否放量」。改用 **30 分钟帧级数据**检验量能的增量判别力。

## 二、回放实测（数据先行，本地 lc5 零网络）

原料：本地 vipdoc `fzline/lc5`（5 分钟线，numpy 直读，覆盖 2026-05-06~10-30 全
回放窗口）；候选层=昨日节点∈{转弱,退潮}；成员=昨日封窗 N10 冻结（与 V2c 同口
径）；量比=成员级「今日帧末累计 amount / 昨日同帧末累计 amount」配对中位（V4-D
口径：合计比混成员漂移噪声不用）；结果目标=当日收盘 16:20 正式链 `rows.node=='wzs'`。

样本：102 交易日、586 候选板块日、5820 帧（脚本 `.tmp_review/pulse_vol_replay.py`，
明细 `pulse_vol_replay_rows.json`，均为仓库外研究工件）。

### 命中率阶梯（核心证据）

| 口径 | n | P(收盘wzs) | 对比基线 |
|---|---|---|---|
| 翻红帧（V2c 现有提示） | 1899 | 38% | — |
| **翻红 & 量比≥1.0** | 562 | **47%** | **+9pp** |
| 翻红 & 量比≥1.1 | 283 | 44% | +6pp |
| 翻红 & 量比≥1.2 | 155 | 41% | +3pp |
| 翻红 & 量比≥1.5 | 36 | 25% | 样本塌陷（n=36） |
| 最早翻红帧（实盘发现时点） | 372 | 32% | — |
| 最早翻红 & 量比≥1.1 | 41 | 49% | +17pp（n 小慎读） |
| 日级：日内存在翻红&≥1.0 帧 | 135 | 41% | — |
| 日级：翻红但全程缩量 <1.0 | 237 | 27% | **-14pp 分离** |

结论：**日内帧级量能有真增量判别力，分离集中在 1.0~1.1 界**；候选翻红帧量比
中位仅 0.91——弱转强本质是缩量换血日的翻红信号，量比≥1.0 已是前 30% 样本。

### 收盘档收紧门误伤实测（C 案否决依据）

日内 max 量比≥1.0 作为收盘 wzs 进门条件 → **裁掉 63/119 真收盘 wzs（47%）**；
≥1.1 裁 85/119。与日线口径同一结论：量能是**辅助确认**不是**必要条件**，硬进
门误伤不可接受 → C 案（硬进门）数据反对，弃。

## 三、条款（A 案：日内提示层量能标注）

### A1 报价采集扩展
`_fetch_quotes` 增抓 quotes 现成 `amount`（当日累计成交额，元）：缺列/NaN →
None（fail-visible 不铸 0）；0 是真读数（冷门股盘中零成交）保留，量比配对的
>0 要求自然剔除。`_pulse_stats` 增 `amountSum/amountQuotedN/amountMissingN`
（amountQuotedN+amountMissingN=quotedN 对账）。

### A2 30 分钟机会式帧序列
- 帧键 `_FRAME_KEYS = 10:00/10:30/11:00/11:30/13:30/14:00/14:30/15:00`；
- **捕获窗 = 帧末 ~ +5 分钟**（闭区间）：窗内请求幂等落该帧，读数≈帧末累计；
  窗外请求不落帧（frameSkip 披露，不污染帧末语义）；15:00 帧沿用 V2c ≥15:05
  条款；午休（11:35~13:30）与尾盘空档（14:35~15:05）天然无窗；
- 存储：`hotlist_jev_sector_pulse` doc.frames[frameKey]（update_one $set upsert，
  **不覆盖**盘中其他帧与回填帧；顶层字段仅 15:00 帧更新——顶层语义=收盘读数）；
- 帧数据（与回填帧同构）：`{at, src: "live"|"lc5_backfill", volBasis,
  boards: {board: {memberN, quotedN, missingN, pctMean, pctMedian, redRatio,
  amountSum, amountQuotedN, amountMissingN, amounts: {code: 元},
  volRatioMedian, volRatioQuotedN}}}`；
- 非交易日不落帧（交易日判定优先于钟表捕获窗）。

### A3 量比口径（成员级同帧自比中位，V4-D 教训）
- `volRatioMedian = median(今日帧 amount / 昨日同帧 amount)`，**配对样本**：
  两侧均存在且 >0 才进样本（昨日缺帧/缺成员/零成交 → 该成员整体剔除，不铸 0
  不偏估）；配对空 → (None, 0)；
- 基线可考性 `volBasis`: `"prev_frame"` / `"prev_frame_missing"`（昨日 doc 无
  frames 同帧键）如实披露。

### A4 候选层 volTag 提示（本代际唯一新展示）
- 规则：当日最近已落帧（live/回填均可）**帧内翻红**（pctMean>0 且
  redRatio≥0.5）且量比可考 → 量比中位 **≥1.0 → `vol_confirm`「量能确认」**、
  **<1.0 → `vol_thin`「缩量翻红」**；缺帧/帧内不红/量比不可考 → 无 volTag
  （不注记，fail-visible）；
- 附带透出：`volTagFrame`（基准帧键）、`volRatioMedian`；
- **不进节点判定、不改收盘档**：候选板快的 `hint`（红盘提示）保持原语义，
  volTag 是并列提示 chip；16:20 正式判档链不读 volTag。

### A5 历史回填（量比基线立即可用）
`scripts/backfill_pulse_frames.py`（默认 dry-run，--apply 实写）：对有
sector-nodes 文档的全部交易日（05-07~10-30），本地 lc5 重建 8 帧 × 板块
（伪 quotes_map 复用 `_pulse_stats/_board_vol_ratio`，与 live 帧同口径），
量比按日期旧→新递推；**live 帧优先不覆盖**（幂等补缺失帧键）；无 pulse doc 的
历史日建 `backfillOnly: true` 档（顶层实时读数不伪造）。
实测落库：新建 113 档 + 补帧 5 档（2026-10-27 起的 live doc）、944 帧、
量比递推 0 缺失、全缺 lc5 板块 8。

## 四、不做什么

- 不把量能做进任何收盘档判据（wzs/weakening/collapse 判定文本零改动）；
- 不做 1.1/1.2/1.5 等更紧阈值（样本塌陷不稳定）；
- 不改 V2c hint chip 语义；不新增对 16:20 判档链的任何输入；
- 测试全 mock（禁真实 jev/TDX 外呼，AGENTS §1.2-7）；回填纯本地 lc5 零网络。

## 五、验收

1. `pytest tests/hotlist/test_sector_pulse.py tests/hotlist/test_sector_pulse_vol.py`
   全绿（帧窗边界/amount fail-visible/量比配对手算/volTag 三向/帧共存幂等/
   非交易日不落帧/回填帧消费）；
2. 浏览器：rv-nodes 盘中提示表候选行出现量能 chip（回填历史可作样例：
   2026-10-30 帧序列全齐，量比可考 27/27 板块）；
3. 版本：`PULSE_VERSION="2026-11-01a"`（v4e=amount 采集+帧序列+量比 volTag）。

## 六、后续待裁（登记不实施）

- 量能确认对**次日**接力收益的预测力（日级 41% vs 27% 分离的持续期验证）；
- 分钟级盘中量能更优原料（逐笔/绝对成交额分位）再评估是否值得立项进档；
- 帧序列积累 ≥20 个交易日后回看 live 帧 vs 回放口径的偏差（取数时刻漂移噪声）。
