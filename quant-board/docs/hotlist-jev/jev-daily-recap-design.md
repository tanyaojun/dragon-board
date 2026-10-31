# 复盘日报（jev daily recap）设计与预登记（2026-10-31，用户裁决）

## 0. 一句话

交易日盘后把【上涨复盘】【下跌复盘】两页结果 + 情绪链锚点拼成单 call 语料包投喂 jev，
产出**每日复盘结论 + 隔日交易计划**，落库并展示于 relay_page 新页签【复盘日报】。

链路复用三条成熟先例：`jev-daily-line`（模板×槽位、jev 只做归层、pilot 门判）、
`jev_relay_index`（单 call 多题）、`schedule.py` 盘后链 advisory 步模式。

**用户裁决（2026-10-31）**：
1. jev 自由度 = **choice 题 + 一段受约束短叙事**；
2. 开火路径 = **pilot 预登记 + 门判通过后再挂排程链**（本文档即预登记；排程链接线在门判通过后另行小步提交）；
3. 展示 = relay_page 新页签【复盘日报】。

## 1. 实现裁决：短叙事 = 预写文段库（版本化），jev 通过 choice 驱动选段

代码证据（`backend/analysis/hotlist/jev_relay_ammo.py`、`operations/jev_daily_line.py` 全仓 grep）：
jev 题型合同只见 `choice` / `score` 两型，**自由文本题型未在 production 验证**。
为不烧真调用去试探未知题型、且不让 jev 自由成文（2026-10-03 措辞漂移教训），短叙事实现为：

- `NARRATIVE_LIBRARY`（版本化 v1）：每档 `recap_shape` 一段预写短文（2 句内，含数值槽位插值）；
- 短叙事段 = 按最终 recap_shape 档位选段 + state 可数事实插值，**零 jev 措辞**；
- 展示附「AI 归层 · 模板成文」标识；jev 失败走机械判档位时同库选段 + `narrativeSource=rule`。

这是「受约束短叙事」的安全实现：语感由人工预写保障，归层由 jev（或规则兜底）驱动，
措辞漂移在结构上不可能发生。若未来验证 jev text 题型，可换代升级（升 QUESTION_SET_VERSION）。

## 2. 语料包三层

### 2.1 state 原料（全部可数锚点）

| 块 | 字段 | 来源 |
| --- | --- | --- |
| rise | poolUp/poolDown/ratio/riseCount/strong/bigFace/zhaBan/fade/highClose/tailDive/streak2/maxStreak/netInflowTotal/topBoards[5]/topStocks[5] | `collect_rise_review`（shape 形态计数由 stocks[].shape 聚合） |
| dieban | poolUp/poolDown/limitDownCount/deepDrop/oneWord/streak2/maxStreak/bigFace/zhaBan/tailDive/netOutflowTotal/topBoards[5]/topStocks[5] | `collect_dieban_review`（同上） |
| emotion | eod/prevEod/eod20dPercentile/bandTag/bandLabel/dailyLineSentence/dailyShape | `phase_pulse.load_eod_scores` + `execution.band_of_score` + `phase_monitor line:<date>` 文档（只读引用，不重算不建第二事实源） |
| degraded | degradedSources | 拼装层逐项登记（fail-visible） |

fail-visible：两页复盘 `noData` 均 true → **本日不出语料包、不烧 jev**（贫料不开火，同 daily-line），
返回 `errorCode=no_material`；部分缺 → 照常出包 + degradedSources 结构化标注。

### 2.2 questions（单 call 多题，5 choice；判据只引用 state 已有字段）

| 题 | choices | 机械判（一致率对照基线，与 criteria 同数） |
| --- | --- | --- |
| recap_shape | 强势延续/分歧加剧/退潮防守/冰点修复/混沌轮动/insufficient_evidence | 涨跌比≥2 且大面≤炸板 且连涨高度≥3→强势延续；两旺(≥10/≥10)且大面>0 且强势>0→分歧加剧；大面>强势 且跌停≥5→退潮防守；连跌高度≥3 且涨≥跌→冰点修复；其余→混沌轮动 |
| money_style | 接力为主/低吸为主/观望为主/insufficient_evidence | 涨跌比≥2 且大面=0→接力；大面≥5 或跌停≥10→观望；其余→低吸 |
| plan_bias | 进攻/均衡/防守/insufficient_evidence | 强势延续→进攻；退潮防守→防守；其余→均衡 |
| focus_direction | rise 正向板块 top8（动态）+ 空仓观望 | 机械判=板块 top1（空名单→空仓观望） |
| risk_flag | 高风险/中风险/低风险/insufficient_evidence | 大面≥5 或跌停≥10→高风险；大面=0 且跌停=0 且涨跌比≥2→低风险；其余→中风险 |

答案无效（不在 choices）→ degraded + 机械判兜底，不伪造 jev 来源；`insufficient_evidence` →
该槽「未判定」，成文照常（事实段不依赖归层档位）。

### 2.3 输出合同

`call_jev` + `parse_jev_response(expected_keys=5 题)`；非 Completed/缺题 → degraded，
按题机械判兜底，不伪造默认档。

## 3. 成文模板（单一事实源，版本化）

`RECAP_TEMPLATE_VERSION = 1`（改措辞必须升版本并在本文档登记）：

- **复盘结论段**：`【复盘结论】{recapShape}（{moneyStyle}）。全市场上涨{riseCount}家、跌停{limitDown}家，采集池涨跌比{ratio}；形态面：大面{n}·炸板{n}·冲高回落{n}·强势{n}·尾盘跳水{n}。情绪分{eod}（{bandLabel}，20日分位{pct}%）。`（槽缺失显式「暂缺」）
- **隔日交易计划段**：`【隔日交易计划】倾向{planBias}，主攻方向{focus}。风险档：{riskFlag}（锚点：大面{n}、跌停{n}、连跌高度{n}）。观察参考，非交易信号。`
- **短叙事段**：NARRATIVE_LIBRARY 选段 + 插值（§1）。
- 模板措辞不入 jev、不入前端；前端只渲染成文与结构化槽。

## 4. 存储 / 读口 / 展示

- Mongo 集合 `hotlist_jev_daily_recap`，`_id=<date>` 幂等 upsert；文档存：语料包摘要（state）、
  questionsRaw、answers（逐题含 source: jev|rule_fallback|rule_dry）、成文三段、
  templateVersion/questionSetVersion、degraded、usage、generatedAt。**零凭据入库**（§1.2#3）。
- 读口 `GET /api/hotlist-jev/daily-recap?date=`：纯读，缺文档 → `{ok:true, missing:true, missingReason}`
  （不空伪装，§4.0）；读库异常 502。
- relay_page 新页签【复盘日报】：结论卡 + 计划卡 + 短叙事卡 + 语料包折叠明细（details）+
  degraded 走底部状态栏 sbLog（页面横幅禁令）；页脚「观察参考，非交易信号」。

## 5. 排程与 pilot（§1.2#7 开火纪律）

- CLI：`python -m backend.operations.jev_daily_recap --date X [--apply] [--force]`；
  不带 `--apply` 零真调用零写库（skippedJev=true）；幂等：当日 ok 文档存在 → 跳过（`--force` 重算）。
- 排程链：**pilot 门判通过后**才在 `schedule.py` 盘后链注册 advisory 步 `jevDailyRecap`
  （子进程、门控=当日 EOD 情绪文档存在、步序排 daily_line 之后、失败不翻转整体 ok）——接线另行小步提交。
- 预算：每交易日 1 call（5 题一 call，估 ≈3-5k tokens/日，月 ≈22 次）。
- **pilot 门判（前 3 个交易日，CLI `--apply` 人工开火记账）**：

| 门 | 判据 | 性质 |
| --- | --- | --- |
| 门1 归层一致率 | 5 题 choice 与机械判一致率 ≥80%（分歧逐例按 原料→题目→解析→方案 归因，§1.2#6） | 硬门 |
| 门2 degraded 率 | degraded 天数占比 ≤1/3 | 硬门 |
| 门3 人工亲读 | ≥3 天 state-答案-成文对齐 + 短叙事逐日审（无预测/无编造） | 硬门 |

门判不过 → 停火回设计（不直接改判据迁就结果）；连过 → 注册排程链转常态。

## 6. 测试边界

pytest 全离线（§1.2#7）：mock `call_jev`、FakeDb、零网络零真库。覆盖：语料拼装 fail-visible
（部分缺料出包+degraded；全缺 no_material 不烧题）；逐题无效答案→兜底；机械判分支全路；
成文模板快照（含 jev 缺席机械版）；dry-run 零调用证明；guard 锁页面骨架与无横幅回归。

## 7. 已知边界

- 历史日回填走 CLI `--start/--end --apply`（真实调用，单独预算确认，不默认执行）。
- 隔日交易计划为 advisory 档位输出，不接实盘/策略执行链；前端不得当唯一交易结论（§4.2）。
- 归层档位 v1 的 choices/阈值为预登记版本，换代必须升 QUESTION_SET_VERSION 并在本文档登记。
