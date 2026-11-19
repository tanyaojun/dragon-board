# 竞价龙头链原料层增量1 预登记（2026-11-14b）

> 性质：**纯语料供给修复，题面 hash 不动**（`QUESTION_SET_HASH_AUCTION_LEADER` 不变，
> 仅 `AMMO_VERSION_AUCTION_LEADER` 2026-11-14a → **2026-11-14b**）。
> 依据：天普股份（605255）11-13 案例复盘（用户裁决「原料层优先」，AGENTS §1.2-6 归因
> 主因=原料缺陷）+ 竞价试盘源勘察（`auction-trial-source-survey-20261114.md`）。
> 零新增外部调用；一切自动化测试 mock jev / 零网络（AGENTS §1.2-7）。

## 1. 改动清单与动机（对位复盘编号）

| 复盘编号 | 改动 | 文件 |
|---|---|---|
| P1 | `sealedPrev` 池单源 → **池 ∪ 韭研+THS 交叉**（`sealed_and_info` 单一实现复用，纯 DB 读）：池漏档不得事实化成「昨日未封板」；冲突不伪造；来源留痕 `corpusState.prevPoolCross`；交叉证封板时首封时点取韭研补全（缺位省略） | `auction_leader_label.py` |
| P4 | 板内解析 T−1 回退（晨间当日 final 未生成是常态 → 回退 `l2_fallback_date`，行内显式标注「{date} 榜单」，返回 `l2Date/l2FallbackUsed` 留痕）；待判龙头解析摘录 `leader_expound_chars=1200` 全文进窗（260 字截断丢控制权变更句） | `theme_event_digest.py`（可选参数，题材链零变化）+ `auction_leader_label.py` |
| P1' | 结构行 `streak` 由 `jiuyan_streak_map` 兜底（非龙头入选股此前恒缺连板高度） | `auction_leader_label.py` |
| 〇 | **单只重跑语料冻结**（codes+force）：复用晨间原件 `narrative`/`corpusState`（`corpusFrozen=true` 落库），判答仍重烧；杜绝盘后重跑用当日 final 重建注入 look-ahead（11-13 21:10 重跑教训）。全日 force 不受影响（有意重建） | `auction_leader_label.py` |

复盘其余项顺延：P3（gene/notice/reason 键集与池 roster 解耦，需新预算登记）、
P6（「当日题材事件」节名事实化，牵动题材链 ammo 换代）、P7（市场行跨源口径）、
试盘源接入（合同待窗内定案）→ 增量2/vA3。

## 2. sealedPrev 交叉判定矩阵（冻结）

```
池降级                    → None（不判，不变）
池命中 sealed             → True（pool）
池命中 broken + 交叉证封板 → None（conflict_pool_broken_cross_sealed，不伪造）
池命中 broken 其余        → False（pool）
池缺席 + 交叉不可用        → False（pool_only，旧口径 + 留痕）
池缺席 + 交叉证封板        → True（jiuyan_ths ← 天普 11-12 形态）
池缺席 + 交叉证炸板        → False（jiuyan_ths_zhaban）
池缺席 + 全源无触板记录    → False（pool）
```

真库只读实证（2026-11-14）：`605255 @ 2026-11-12` → `(True, "jiuyan_ths")`
（池漏档、交叉证封板）。旧入口 `_sealed_prev` 保持兼容（无交叉=旧行为，测试锁定）。

## 3. 语料卫生

- 新增叙事内容仅两类数据事实：板内解析行尾「，{l2_date} 榜单」；
  「昨日封板（首封 {jiuyan时点}）」时点补全。无口径/判据/开发注释（AGENTS §1.2-8），
  `test_narrative_hygiene` 全绿。
- 缺席纪律不变：交叉源失败 → `prevPoolCross=fetch_failed:*` 留痕、叙事按在场事实出；
  THS 缺 → `pool_only` 旧口径（宁缺毋猜不升级）。

## 4. 验收

- `pytest tests/operations/test_auction_leader_label.py tests/hotlist/test_theme_event_digest.py
  tests/hotlist/test_jev_version_stamps.py tests/hotlist/test_narrative_hygiene.py
  tests/api/test_auction_leader_route.py tests/hotlist/test_relay_page_auction_leaders.py
  backend/analysis/hotlist/__tests__` 全绿（84+64 用例，2026-11-14 实测）。
- 新增用例：交叉矩阵 7 态、build_one 交叉结构行、冻结重跑（叙事逐字一致 + 判答重烧）。
- 已知 HEAD 既有失败（与本增量无关，待另案）：`test_relay_page_theme_leaders.py`
  3 例 + `test_relay_page_window.py::test_review_unlabeled_rows_render_clean_node`
  （relay_page/index.html 缺 `evidenceBoardResolved` 徽章，JS 内容断言）。

## 5. 下一步（增量2 候选，需各自预算/裁决）

1. **试盘源定案**（周一 09:15–09:25 窗内 ≤2 发预登记探针 + MITM 对照）→
   `auction_trial_line` + `corpusState.trialState`（勘察文档 §5）。
2. P3：gene/notice/reason 补拉键集解耦（入选股 roster），晨间新增 ≤3×roster 次既有端点。
3. P6/P7：digest 节名事实化 + 市场行口径标注（牵动题材链 ammo 换代）。
4. vA3（题目层）：一字板判据分支、硬度×方向解耦、判据引用对齐、三层门质量化。
## 6. 六件套门控重裁注记（2026-11-19 竞价三字段投影层）

`auction_bid_line` 信息量门槛「六字段任一非 0」经投影层重裁（计划
auction-bidding-zero-trio-fix-plan-20261119.md §4.4，已实施）：
- 净额改**状态门**：投影 None（掉池/未公布）→ 净额段整段缺席（无占位符）；
  留池撮合后真 0（买卖平衡/一字无对手盘）是事实照出——「竞价净额 0」仅当
  in_pool_matched 真 0。原 `is not None` 门控自然生效，函数零代码改动。
- 掉池股行经 col10 虚拟观测额可读后自然出行（竞价涨幅/成交额/换手/涨停委买额），
  不再被零额门吞掉；peers 对比段 amount 同用投影值（同板对比不被零拉偏）。
- src/时点/派生口径只进结构化字段（item.*_src/*_state、doc.bidLine/bidLineState、
  corpusState.bidTrio）与页面 tooltip，不进叙事（红线 8，test_narrative_hygiene
  掉池缺位/留池真 0 双例守卫）。AMMO 换代 2026-11-19a（题集 vA6 不变）。
