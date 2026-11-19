# 竞价三零字段（净额/成交额/换手）彻底修复计划（2026-11-19）

> 状态：**已实施**（2026-11-19 午间休市实施轮；全量 pytest 5502 passed, 6 skipped；
> 实施偏差与实证修正见 §11——census 净额缺位 36→218 被原料证伪后按状态门语义忠实实施）。
> 关联：`auction-trial-direct-probe-preregistration-20261116.md`（增补一/二/五）、
> `auction-leader-ammo-20261114b-preregistration.md`（六件套行）、AGENTS §1.2-1/5/8、§4.0、红线 9/10。
> 本文是实施单一依据；实施轮按 §8 文件清单逐件落地，同轮同步展示/测试/文档（§1.2-5）。

## 0. 结论先行

- **问题**：daban 集合竞价页签与竞价龙头语料中，36/299 只股「竞价净额/竞价成交额/竞价换手」
  显示 0（600410 华胜天成截图实证），板块聚合被零值拉低，语料叙事出现「竞价净额 0」假事实。
- **原因**（三层叠加，非解析丢字段）：
  1. **服务端公布时点**：净额/换手率全市场、成交额沪市（60/68），只于 09:25 撮合后公布；
     深市成交额窗内有虚拟值。socket 2103 pid8 quotas pos20/21/22 与 HTTP MBL col6/7/8
     双通道逐值同源（600410 原始帧即 `'0','0.00','0'`）。
  2. **成员制**：09:25 前掉池股（600410 末帧 09:23:23）在 socket pid8 与 HTTP MBL 两通道
     都收不到撮合后公布 → 永久 0（自然实验：留池沪股 603030 窗内七帧全 0、09:26:20 帧一次性公布）。
  3. **消费层把未公布当事实 0**：`bid_items` 终态覆盖保留掉池零帧（早退值）；页面
     `kfmtAmt(0)='0'`、板块聚合 sumN 计 0；语料 `auction_bid_line` 以 `is not None` 门控 → 0.0 进叙事。
- **改法**：新建**单一投影层** `backend/operations/auction_bidding_facts.py`（纯库读、零外呼），
  对三字段做「状态机 + 来源分级 + 派生换手 + 净额状态门缺位」；全部消费方改接投影；
  raw 存档（bid_items/MBL raw/series/mbl_series）**零写入零改写**（fail-visible 原料保全）。
- **不接 3001 f200**：BidQuotos 字段集 = pLine/incRate/price/volRatio/tur，**无净额无换手率**；
  掉池股 tur 撮合后公布未验证；3001 面=浏览器面同款覆盖缺陷；新订阅面需另立频控登记。留作残留探针（§10）。

## 1. 根因证据链（2026-11-19 实档，实施轮测试回放同数据）

| 股 | 池命运 | MBL col6/7/8（≡socket pos20/21/22） | col10 | 结论 |
|---|---|---|---|---|
| 603030 全筑股份（沪，留池） | 09:26 在榜 | 09:15:35→09:24:51 七帧全 0 → **09:26:20 公布** 11109148/1.07/26669214 | 3.9M→23.5M→26669214（撮合帧 col10=col8） | 沪三字段撮合后公布 |
| 600410 华胜天成（沪，09:23:23 掉池） | 09:24:51 起双通道缺席 | 在世 57 帧全 0，永无公布 | 掉池前末帧 **124381050** 在档 | 掉池=永久 0 |
| 002685 华东重机（深，留池） | 冻结在榜 | 窗内 col8=19641609（虚拟），col6/7 撮合后公布 | 恒等于 col8 | 深成交额窗内有虚拟值 |
| 002799/002571（深，09:16 早退） | 早退 | 全 0（委买仅 44.9 万、无虚拟撮合） | 0 | 早退+无虚拟撮合 |

- 普查：`bid_items` 299 只中零成交额 36 = **60×29 + 68×5 + 00×2**；非零 263（00×192+30×70+60×1）。
  唯一非零 60 = 603030（留池到撮合后）。
- 通道交叉：MBL 冻结 002685 = socket bid_items 逐值吻合（-8183651/5.86/420443307）→ 映射无误，零是服务端发的。
- `kpl_mbl_series` 在档日：2026-11-17/18/19；窗 09:15–09:26、≤15 帧/日，**含撮合后帧**（09:26:20）。
- 消费污染面：daban 页右表三列 + 左板块聚合（净额/成交额合计）+ 竞昨比（前端由成交额派生，
  `kplDabanEnrichBidRatio` ~L8423）+ `/auction-trial` jj_amount/jj_turnover + 龙头/板块语料六件套行
  （`auction_leader_label` L384/470 → `hotlist_jev_auction_leader_labels.narrative`）。

## 2. 语义裁决记录（本轮用户裁决 + 实证锚）

1. **col10 = 竞价成交额（虚拟累计→撮合收敛）**：09:15 起全市场有值；撮合帧 col10=col8
   （603030：26669214=26669214；002685 冻结：420443307=420443307）。掉池股取**窗内末帧 col10**
   = 掉池前虚拟观测值（口径披露，非匹配终值）。此前「col9/col10 未破译保原名」裁决由本轮取代；
   **col9 仍不采用**（09:20 起累计、语义未破译，留勘察）。
2. **派生换手% = 成交额 ÷ 流通市值 × 100**（col12/real_float，元口径；价格约掉=股数换手）：
   锚 002685：420443307/7172168867×100=5.8622→公布 5.86 ✓；603030：26669214/2499813743×100=1.0668→1.07 ✓。
   600410 派生=124381050/20285151636×100≈**0.61%**（src=derived_cap，口径披露）。
3. **净额 = col14+col15**（买/卖额代数和）：002685：329907346−338090997=−8183651 ✓；
   603030：26127965−15018817=11109148 ✓。**掉池股 col14/15 窗内全 0 → 净额无任何现存源 → 缺位（None），不伪造**。
4. **状态门而非值门**：留池撮合后真 0（买卖平衡）是事实，保留；「掉池/未公布」的 0 是缺位。
   窗内（09:15–09:25）净额/换手对**所有股**都未公布 → 实时态也显缺位，不显 0。
5. 叙事禁口径/来源注（红线 8）：src/state/派生口径**只进结构化字段与页面 tooltip**，不进语料行。

## 3. 目标架构：单一投影层（§1.2-1 单一事实源）

新模块 `backend/operations/auction_bidding_facts.py`（operations 层，与 auction_trial_derive 同族）：

```python
def resolve_bidding_trio(db, date, codes=None) -> dict:
    """纯库读投影：{code: TrioFact} + 日普查 census。零外呼、零写入。
    原料：kpl_mbl_series（帧时序）、kpl_morning_bidding_raw（冻结）、
    kpl_daban_pool.bid_items（终态+last_seen_ts）、kpl_bidding_series（成员时序佐证）。"""
def apply_trio(items: dict|list, facts: dict) -> ...:
    """消费方合并助手：三字段覆写为投影值 + 附 *_src/*_state/trio_state 结构化字段。"""
def rebuild_auction_bid_lines(db, date, *, authorize_frozen_bypass=False) -> dict:
    """语料外科重建入口（§4.8）：零 jev、零外呼；单写者=本入口（文档化）。"""
```

TrioFact 合同（每 code）：
`bidding_amount / bidding_amount_src / bidding_turnover / bidding_turnover_src /
bidding_net / bidding_net_state / trio_state / amount_ts / float_cap / census 贡献`。

### 3.1 状态机（trio_state）与字段可用性矩阵

| state | 判定证据 | amount | turnover | net |
|---|---|---|---|---|
| `in_pool_matched` | 存在 ts≥09:25 帧且 col8/col6 非零（或 bid_items last_seen≥09:25 且额>0） | 撮合帧 col8（src=mbl_postmatch；与 bid_frozen 对拍不一致→fail-visible 披露取 mbl） | 公布 col7（src=mbl_postmatch） | 公布 col6（**真 0 保留**） |
| `in_pool_pre_match`（实时窗内） | 在池、ts<09:25 | col10 末帧（src=mbl_col10_virtual） | 派生（src=derived_cap） | **None**（未公布） |
| `dropped_pre_match` | 窗内有帧、09:25 前缺席（mbl 帧/series tick/bid last_seen 三证） | 掉池前末帧 col10（src=mbl_col10_preexit，口径=虚拟观测） | 派生（src=derived_cap） | **None** |
| `dropped_post_match` | 09:25 后缺席但已收到公布帧 | 公布值 | 公布值 | 公布值 |
| `not_in_auction_pool` | 三通道皆无（试盘宇宙股可经 3006 lane 在宇宙但不在 pid8） | None（live 窗内腾讯补源可填，src=tencent_auction） | 同左 | 同左 |
| `no_mbl_series_day`（≤11-16 历史日） | 无 mbl_series 档 | 回退 bid_frozen/MBL 冻结 + 状态门：>0 保留；==0 且掉池证据→None | 同左回退+派生兜底 | 同左状态门 |
| 附加 reason（可叠加） | `no_float_cap`（换手派生缺市值→None）、`read_failed:<exc>`、`sup_live_only`（腾讯补源仅 live 内存缓存未落库，离线重建不可恢复） | | | |

- 派生换手一律保留两位小数原值（不预 rounding 到公布精度）；`float_cap` 取 MBL col12，
  缺则 bid_items.real_float（600410 两源同值 20285151636 实证）。
-  census（日级，进 API state 与页头）：`matched_n / virtual_n / preexit_n / derived_tur_n /
  net_missing_n / not_in_pool_n / no_cap_n / total_n`。
- 读失败 fail-visible：单集合读异常 → 该源降级 + reason 留痕，不阻断其余源（§4.0）。
- 性能：mbl_series ≤15 帧×~300 行/日，纯内存聚合；按请求计算，不加跨请求缓存（避免双事实源）。

## 4. 消费方接入清单（彻底版，七处 + 重建入口）

### 4.1 `backend/api/kpl_proxy_routes.py`
- `GET /daban-list`（L146，proxy :8002 内存快照）：**proxy 返回后合并投影**（pid_type=8 分支；
  其余 pid 不碰）。live 行=当前推送（掉池股零帧）→ 投影覆写三字段+src/state。
- `GET /daban-list-history`（L429，:8000 读档）：同构合并（历史日走 §3.1 历史回退态）。
- 响应 state 增 `trioCensus`；items 每股增结构化 src/state 字段（前端 tooltip 消费）。

### 4.2 `backend/operations/auction_trial_derive.py`
- `jj_amount/jj_turnover` 现链（MBL 冻结→bid 冻结→序列末帧，L225-232）**改接投影**
  （投影内部即更优分级链）；`jj_percent` 链（s0925→tdx→成员制冻结）**不动**。
- state 增 `trioCensus` 引用；`jjSource` 语义扩展 amount/turnover 的 src 披露（现有字段名保留兼容）。
- 序列 first/max/last（过程观测）**保持 raw**（观测值口径已披露），不被投影覆写。

### 4.3 `backend/operations/auction_leader_label.py`（runner）
- `lanes["bid"]` 合并腾讯补源后（L705-717）、构造 `bid_entries`/`peers` 前（L352-360、L465-470）
  调 `apply_trio` → 龙头与板块两条叙事链同修。
- 腾讯补源优先级：`source=tencent_auction` 的 net/turnover 为实测值 → **优于派生**（src 保留 tencent_auction）。
- doc 增结构化字段 `bidLine`（原串）+ `bidLineState`（census/src 摘要），供 §4.8 外科重建定位。

### 4.4 `backend/analysis/hotlist/auction_leader_ammo.py::auction_bid_line`
- 门控改状态门：`net` 投影为 None → 字段缺席（现有 `is not None` 自然生效）；
  **投影保留的真 0 照出**（「竞价净额 0」仅当 in_pool_matched 真 0）。
- 信息量门槛「六字段任一非 0」重裁：amount 经 col10 可读后，掉池股行出
  「竞价涨幅/竞价成交额/竞价换手/涨停委买额」、**净额段缺席**（缺位字段不出现，无占位符）。
- peers 对比段 amount 用投影值（同板对比不再被零拉偏）。
- 叙事零 src/口径注（红线 8）；结构化 `corpusState.bidTrio` 留痕（runner 注入）。

### 4.5 `backend/analysis/hotlist/theme_leader_ammo.py` 负额判门复核
- `_fmt_amount_yuan` 绝对值判门消费净额处：缺位 None 不得触发「负额退化/升级」误判（复核+测试）。

### 4.6 `backend/relay_page/index.html`（daban 竞价页签 kplBidRender ~L9357-9470）
- 右表三列：null→`kfmtAmt/kfmtNum` 现有 '--' 自然生效；**0 不再可能出现于未公布态**（投影保证）；
  单元格 title 增 `src/state/amount_ts/派生口径`（如「掉池前虚拟观测 09:23:23」「换手=额/流通市值 派生」）。
- 竞昨比：前端由 amount 派生（~L8423）自动随修；amount 缺 → ratio None → '--'（守卫测试）。
- 左板块聚合 + 「全部」行：sumN 门现有，但**增覆盖率 tooltip**（`sumN/n`，如「净额合计 263/299 覆盖，
  36 只未公布缺位」）；聚合值本身不含缺位股（不烘 0，评审 P2-4 延续）。
- 页头 census 行：`撮合公布 N/虚拟 N/掉池前观测 N/净额缺位 N`（trioCensus 消费）。
- 历史档模式（history）同款披露（历史回退态 reason 进 tooltip）。

### 4.7 `backend/services/kpl_ranking_service.py`
- 腾讯补源 `get_auction_snapshot_tencent`（L916-985）**不动**（live 窗内补源合同保留）；
  仅确认其字段进投影优先级（§4.3）。`derive_bid_ratio_prev_vol` 不动（消费投影后 amount 自动随修）。

### 4.8 语料重建入口 `rebuild_auction_bid_lines`（新，同模块）
- 目标集合 `hotlist_jev_auction_leader_labels`（leader+sector 两 docKind）。
- 路径 A（新档有 `bidLine` 字段）：新串精确 `narrative.replace(old, new, 1)`；new=None → 删行。
- 路径 B（今日存量档无 bidLine）：按「label 前缀 + 含『竞价涨幅』行」定位 fallback（启发式，
  重建报告逐 doc 列出 old/new 供人工读）；**禁止整篇 narrative 重生成**（保其余行与冻结输入不漂移）。
- 冻结复用守卫（runner L864-890 frozen_doc narrative）：重建入口显式 `authorize_frozen_bypass=True`
  才绕过（用户授权留痕 rebuildReason/rebuiltAt）；默认拒绝。
- 零 jev（§1.2-7）、零外呼（basis/腾讯补源离线不可恢复 → 竞昨比段保持原串不动，只换六件套行；
  `sup_live_only` 留痕）。单写者=本入口（replace_one 整 doc 与 runner 同合同，字段级更新 narrative/bidLine/bidLineState/rebuiltAt）。
- 返回重建报告：{docs_n, replaced_n, removed_n, fallback_n, skipped_frozen_n, per_doc diff 摘要}。

### 4.9 文档同轮同步（§1.2-5）
- 本计划文档状态改「已实施」+ 实施偏差记录。
- `auction-trial-direct-probe-preregistration-20261116.md` 增补三：三零根因定案 + col10/派生换手/净额状态门裁决 + 投影层合同。
- `docs/README.md`（若索引 hotlist-jev）加链接；`auction-leader-ammo-20261114b-preregistration.md` 六件套门控重裁注记。

## 5. 历史兼容与原料保全

- raw 四存档（bid_items/MBL raw/kpl_bidding_series/kpl_mbl_series）**零写入零改写零 drop**；
  投影纯读，回退=git revert 投影接入即恢复旧展示（原料无损）。
- ≤2026-11-16 无 mbl_series：走 `no_mbl_series_day` 回退 + 状态门（零且掉池→缺位），census 披露降级。
- 不做历史日语料批量重建（默认只重建用户指定日；今日 11-19 为实施轮指定日）。

## 6. 红线合规矩阵

| 红线 | 合规点 |
|---|---|
| §4.0 禁硬门禁/不伪 0 | raw 全量保全；缺位=None+state，不烘 0；读失败降级留痕不阻断 |
| §1.2-1 单一事实源 | 三字段语义唯一权威=投影层；raw 各司其职（过程/终态/冻结/帧时序） |
| §1.2-5 结论展示同轮 | 代码+页面+语料+测试+docs 同轮 |
| §1.2-8 叙事卫生 | 缺位字段整段缺席；src/口径只进结构化与 tooltip；过 test_narrative_hygiene |
| §1.2-7 测试禁真 jev | 重建入口零 jev；测试全 fixture/实档回放 |
| 红线 9 先读源码 | 根因双通道实证+自然实验；col10/换手/净额三锚精确吻合；不盲猜 |
| 红线 10 频控 | **零新增外呼**（投影纯库读；重建零外呼）；无新订阅面 |
| 单写者 | collector/archiver 写合同不动；重建入口为语料 doc  documented 单写者 |

## 7. 测试计划

新增 `tests/operations/test_auction_bidding_facts.py`（≥12 例，fixture 回放今日实档切片）：
1. in_pool_matched：603030 三字段=公布值、真 0 净额保留例；
2. dropped_pre_match：600410 amount=124381050/src=mbl_col10_preexit/amount_ts=09:23:23、
   turnover≈0.6132/src=derived_cap、net=None/state=dropped_pre_match；
3. in_pool_pre_match（窗内实时态）：net=None 不伪 0；
4. SZ 虚拟：002685 窗内 amount=col10=col8、net 未公布 None；
5. 派生换手锚：002685=5.8622、603030=1.0668（与公布值两位小数一致）；
6. no_float_cap → turnover None + reason；
7. no_mbl_series_day 回退 + 零且掉池→None、留池真 0 保留；
8. not_in_auction_pool → 三 None；腾讯补源优先级例；
9. 读失败单源降级不阻断 + reason；
10. census 计数=今日普查（36 缺位净额/263 公布或虚拟…按投影口径断言）；
11. apply_trio 不碰非三字段（raw quotas/price/pct 保全）；
12. rebuild：路径 A 精确替换/删行、路径 B fallback 报告、冻结守卫默认拒绝/授权绕过、零 jev 断言。

更新既有：
- `tests/operations/test_auction_trial_derive.py`：jj_amount/jj_turnover 接投影后语义（600410 行额=1.24 亿观测、换手派生）。
- `tests/hotlist/test_auction_trial_line.py` / `test_theme_leader_ammo.py` / `test_narrative_hygiene.py`：
  掉池股六件套行「有额/换手、无净额段」；留池真 0 净额照出；黑名单不变。
- `tests/hotlist/test_relay_page_auction_leaders.py` + daban 页守卫：tooltip/coverage/census 子串守卫、
  竞昨比缺 '--' 守卫。
- proxy routes 测试（live merge/history merge/非 pid8 不碰）。
- 全量 `pytest`（上轮基线 5447 passed, 6 skipped）。

## 8. 影响文件清单

新增：`backend/operations/auction_bidding_facts.py`、`tests/operations/test_auction_bidding_facts.py`、本文档。
修改：`backend/api/kpl_proxy_routes.py`、`backend/operations/auction_trial_derive.py`、
`backend/operations/auction_leader_label.py`、`backend/analysis/hotlist/auction_leader_ammo.py`、
`backend/analysis/hotlist/theme_leader_ammo.py`（复核门）、`backend/relay_page/index.html`、
`tests/operations/test_auction_trial_derive.py`、`tests/hotlist/test_auction_trial_line.py`、
`tests/hotlist/test_theme_leader_ammo.py`、`tests/hotlist/test_narrative_hygiene.py`、
`tests/hotlist/test_relay_page_auction_leaders.py`、proxy routes 对应测试、
`docs/hotlist-jev/auction-trial-direct-probe-preregistration-20261116.md`、`docs/README.md`（索引）。
**不动**：collector/archiver/protocol（写侧零改动）、kpl_ranking_service 补源合同、3001/3006 订阅面。

## 9. 上线与验证

1. 实施轮全量 pytest 绿 → **仅重启 :8000**（午间休市或盘后；:8002/:8008 零重启零推送损失）。
2. 今日实档回放验证（读口直断）：600410 三字段=§7-2 期望；603030/002685 不变；census 净额缺位=36；
   板块聚合覆盖率 tooltip 263/299；竞昨比 600410 由 0.00% → 派生值或缺 '--'。
3. 语料重建今日（授权 frozen bypass）：重建报告人工读；600410 行无「竞价净额 0」、有「竞价成交额 1.24亿」观测串。
4. 明日 11-20 竞价窗 live checklist：09:15–09:25 净额列全 '--'（未公布态）；09:26 起留池股公布值、
   掉池股 preexit 观测+派生换手；页头 census 与 auct lane 观测同屏核对。
5. 回退：git revert 投影接入（raw 无损）；语料重建反向=再跑 rebuild 回旧串（报告留 old 串）。

## 10. 残留与后续预登记（不在本轮）

- 掉池股**匹配终值**（非虚拟观测）：TDX 09:25 分钟棒量×开盘价（python-bridge 通道另立频控登记）
  或 3001 面含掉池股探针验证 BidQuotos.tur 撮合后公布（预登记探针，红线 9 先读源码已有锚）。
- col9 语义仍「未破译保原名」，通道留勘察。
- 002799/002571 类「早退+无虚拟撮合」真 0 vs 缺位：当前按 dropped_pre_match 缺位处理（保守），
  若后续探针证实无撮合=真 0 再重裁（值门恢复需新证据）。
- 腾讯补源落库（sup_live_only 消解）需另裁（写侧单写者变更）。

## 11. 实施偏差记录（2026-11-19 实施轮，红线 6 先查原料与题目）

实施轮只读勘察今日实档（12:55–13:08 多次快照）发现计划 §1 普查口径与原料不符，
按 §7-10「按投影口径断言」授权忠实实施状态门语义，修正如下（raw 零改写不变）：

### D1 census 实证修正（净额缺位 36 → 218）

计划预期「净额缺位=36」把「零成交额 36」等同于「净额缺位」，原料证伪：
`bid_items` 299 只中 `bidding_net==0` 实为 **216** 只，其中——

| 类别 | 只数 | 投影裁决 |
|---|---|---|
| 留池到公布后帧（last_seen 11:29:42 ≫ 公布锚 09:25:13），净额非 0 | 88 | 公布值保留 |
| 留池真 0（39 只买卖平衡 577 帧恒 0 + 600671/600615 一字全日 (0,0,0)，其中 1 只冻结 col14/15=0 交叉印证） | 40 | **真 0 保留**（状态门） |
| 深市掉池股：虚拟额非零但净额未公布（ev=0000/0001） | 137 | 缺位 None |
| 沪市掉池/早退零额（含 002799/002571 无虚拟撮合） | 34 | 缺位 None |
| series-only 股（socket 序列有、bid 存档无，47 只） | 47 | 掉池缺位 None |

投影 census（fixture 回放钉死）：`total_n=346`（bid 299 ∪ series 342 ∪ mbl/frozen）、
`matched_n=128 / preexit_n=218 / virtual_n=0 / net_missing_n=218 / true_zero_net_n=40 /
derived_tur_n=191 / no_cap_n=16`。页面「全部」行覆盖率 tooltip 随 sumN 动态
（净额 128/299 显示口径，非计划示例 263/299）。600410/603030/002685 三锚逐值吻合计划 §7。

### D2 公布分阶段 + socket 陈旧页（计划 §3.1「ts≥09:25 即公布」精化）

- 公布分两阶段：额/换手先（09:25:13 首根沪市额非零帧），净额逐股随后
  （09:25:13–09:26:20 到齐；300857 净额 09:25:50 才到）。
- socket pid8 流含**陈旧页**（同推送周期多页新鲜度不一）：300857 终帧回放
  09:19:05 虚拟值 8086800/net0，公布值 101707289/27741379 被覆盖（12:55 快照实证；
  生产库持续自愈，13:08 帧已覆写回公布值——投影对两种终态均正确）。
- 公布证据精化为：mbl 完整公布帧（沪额非零+任意净额非零，HTTP 全量新鲜）成员 →
  MBL 冻结（fetchedAt 晚于额锚；缺时戳按采集合同信任）→ 留池持久证据
  （bid last_seen **严格晚于**额锚）+ series 公布后帧对拍（首个净额非零帧 /
  首个脱离窗内虚拟态帧优先，陈旧回放剔除，`bid_frozen_stale_diff` 留痕）→
  公布帧正值证据抢救（dropped_post_match）。
- 002729 恰在公布帧掉池（该帧仍携带早退值，与 09:24:36 逐值相同）→
  dropped_pre_match + `exit_at_pub_frame` 留痕，不判公布。
- 深市虚拟额撮合前**收敛**=公布额（002123 案 512502）：真 0 与陈旧回放不可值门
  区分 → 留池持久+公布完成锚判公布态，`pub_values_equal_virtual` 仅披露。
  （实施中曾试「公布后观测==窗内虚拟态→缺位」值门，误伤 34 只收敛真 0，已撤。）

### D3 读口第三路 /daban-bidding（计划 §4.1 双路 → 三路）

竞价页历史模式实际读 `/daban-bidding`（kplDabanArchiveHistory，本地 bid_ 通道），
非 `/daban-list-history`（HisDaBanList 默认集合）。不合并则历史模式仍显零 →
`_load_daban_lane_day` lane=bid 同款合并（历史日 no_mbl_series_day 回退态）。

### D4 虚拟观测兜底源扩展（§4.0 可计算部分保全）

mbl col10 缺席时（榜单截断，131/170 掉池股有 mbl 帧、39 只无）：bid_items 窗内
虚拟额（`bid_preexit_virtual`/`bid_virtual`）→ series 末帧虚拟额
（`series_preexit_virtual`/`series_virtual`）同语义兜底，src/时点披露。
col10==0 早退无虚拟撮合 → 额 None（保守缺位，§10 残留不变）。

### D5 rebuild 竞昨比伪 0 剔除（计划 §4.8「原串保留」收窄）

旧 ratio==0 且旧额缺/0 → 该 ratio 由缺位额派生 = 伪事实（600410 旧「竞昨比 0.00%」），
整段缺席（§4.0 禁伪 0）；旧额>0 或 ratio>0 → 原值保留（basis 离线不可恢复，零外呼）。

### D6 代际与杂项

- AMMO_VERSION_AUCTION_LEADER → `2026-11-19a`（投喂文本语义变更；题集 vA6 hash 不变）；
  test_jev_version_stamps 同轮更新。
- no_mbl_series_day 回退仅在 mbl 帧与 series 双缺席时启用；series 在场走主路径
  （可剔陈旧）；`noMblSeriesDay` 披露 flag 独立。
- 页面守卫落 `test_relay_page_kplstock.py`（kplBidRender 守卫族所在）；
  docs/README.md 未索引 hotlist-jev（计划 §4.9 条件不成立，不加链接）。
- 投影层新增 reason：`bid_frozen_stale_diff / pub_values_equal_virtual /
  net_pub_pending / exit_at_pub_frame`（计划 reason 集扩展，结构化留痕）。

### D7 协作并发写入（AGENTS §1 纪律留痕）

实施轮期间协作者向 `auction_leader_label.py` 写入「并行取数相（裁决 1+2）」与
调度器 A+B+C 修复（增补三/四），`auction_trial_derive.py` 含 TDX 开盘棒修复
（未提交）。本轮编辑均为增量合并（edit 精确匹配当前文件），**未覆盖/未回滚**
协作者改动；投影块置于 MBL 审计线程 join 之后（消费新冻结档）。jj_percent 链
（含 TDX 兜底）零改动。汇报时 git status 含双方改动，提交需人工分辨归属。

### D8 测试与验证

新增 `tests/operations/test_auction_bidding_facts.py` 22 例（实档回放 fixture
`fixtures/auction_trio_20261119.json` 464KB：bid 299 + mbl 8 帧 + 冻结 89 +
series 关键帧压缩 + 15 labels doc；fixture 回放与实档 facts diff=0）+
proxy 路由 7 例 + runner 2 例 + 叙事/卫生/页面守卫 8 例；既有 derive/stamp 更新。
全量 pytest：**5502 passed, 6 skipped**（基线 5447 → +55，零回归）。
