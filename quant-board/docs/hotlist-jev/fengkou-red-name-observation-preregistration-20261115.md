# 最强风口红名观察预登记（2026-11-15，用户裁决「先观察再定」）

> **已退役（2026-11-19 用户裁决）**：观察链整链淘汰——`kpl_fengkou_red_obs`
> 日档（5 篇，2026-11-13~11-19）mongodump 归档
> `quant-board/data/backups/kpl_fengkou_red_obs_retire_20261119/` 后单集合 drop；
> `fengkou_red_observer.py`、schedule/scheduler 挂链、`GET /api/kpl/fengkou/observation`
> 读口与对应测试同轮删除。下文为历史预登记存档（观察材料见归档）。

> 性质：**观察采集预登记**，非合同变更。不改 vA3 选龙合同（`auction-leader-vA3-preregistration-20261114.md`
> 双源并集原样）、不进锚人群、不烧 jev、不改打标链选样。采集器：
> `backend/operations/fengkou_red_observer.py`（15:10 挂链，`kpl_fengkou_red_obs` 日档）。

## 1. 背景与实证（2026-11-15）

KPL 最强风口个股强度榜 `name_red`（List[7] 位，H5 渲染 `t_red` 仅颜色 #e02d2d，无语义注释）
语义未确认。当日实证（11-13 各时点快照 + kpl_daban_pool 交叉）：

| 假说 | 证据 | 结论 |
|---|---|---|
| 涨停（当前/曾/收盘） | 思美传媒 -1.77% 红（09:35）；光线传媒 +5.31% 收盘红；中国电影 +10.00% 涨停不红 | ❌ |
| 昨日/近期涨停基因 | 儒意、光线 11-10~11-12 涨停池零记录；思美/欢瑞/浙文同样没有 | ❌ |
| 强度/资金排名 | 红名股强度 1208~2684，大量更高强度股不红 | ❌ |
| 当日最强风口板块成分 | 11-13 全天红名 100% 影视传媒系；集合日内变化（09:35 六只→10:00 三只→11:00 五只→收盘四只），与个股涨跌无关 | ⭕ 主假说，未坐实 |

**时点硬约束（第二个「先观察」原因）**：09:26~09:31 快照为空（强度榜 09:32 起才有首行），
竞价龙头链 09:26 挂链时点物理上拿不到红名股——即使语义坐实也不能按原需求直接入 09:26 选样。

## 2. 采集合同

- **时点**：交易日 15:10 挂链（scheduler `_FENGKOU_RED_OBS_AT`，限次退避 ≤2 次/间隔 15 分钟）；
  探针时点 0932/0935/1000/1100/1400 + 收盘终档（Time 空）。观察器模块内无重试循环；
  调度层退避下确定性降级日（login_expired 等，失败响应不进服务端缓存）第二次运行
  会重发探针，**最坏 12 发/日**（有界，仍合红线 9）。
- **日档** `kpl_fengkou_red_obs`（`_id`=交易日）：
  - `probes[]`：每时点 `{time, ok, nRows, redN, reds[]}` 或 `{time, ok:false, reason, error}`（fail-visible）；
  - `redUnion[]`：跨时点红名并集（code 键去重），`{stock_id, name, firstTime, lastTime, times,
    change_pct, strength, boards, inPrevPool}`——`inPrevPool`=T−1 涨停池成员（kpl_daban_pool），
    池缺席记 `null` + `quality.prevPoolAvailable=false`，不猜；
  - `nextDay`：T+1 收盘涨幅（腾讯行情，缺股记 `missing` 不伪造），`obsState: pending_next_day → settled`；
  - `quality`：probeOkN/probeTotalN、prevPoolAvailable。
- **fail-visible**：个别时点降级 doc 照写；全源无数据才不落 doc（`fengkou_red_obs_all_degraded`）；
  CLI `--date` 历史日探针载荷 day 与入参不一致时不落 doc（`fengkou_red_obs_day_mismatch`，
  防实时端点只保留最近交易日快照导致的静默错档）。
- **读口**：`GET /api/kpl/fengkou/observation?date=`（缺省最新一篇；无档结构化 degraded 返回）。

## 3. 观察判据（≥3 交易日，语义裁决材料）

1. **板块归一度**：红名并集的精选板块 top-1 集中度（若红名=风口成分，应持续高度集中于
   当日最强方向且随日切换；若散落多板块则主假说否决）。
2. **T+1 表现**：红名股次日收盘涨幅分布（vs 榜内非红股对照）；若红名=风口核心成分，
   次日应有可辨识的持续性或分化信号。
3. **与涨停池的关系**：inPrevPool 占比日内演变（若红名随封板事件出现/消失，说明服务端
   按涨停事件打标；若独立于封板，说明按板块归属打标）。
4. **红名集合稳定性**：`times` 分布（全天在场 vs 日内进出）。

## 4. 裁决出口（观察结束后另行裁决，不在本预登记内）

- 语义坐实 + 用户裁决入链方式（盘中补充挂链 / 盘后 T+1 / 仅语料行）→ 那时才走
  题目集换代预登记（vA4）+ `selectionSources` 扩展；
- 语义否决 → 观察采集停用（`FENGKOU_RED_OBS_ENABLED=0`），数据归档保留。

## 5. 测试

`tests/operations/test_fengkou_red_observer.py`（10 项全 mock）：完整落档 / 部分时点降级
照写 / 全源无数据不落 doc / T+1 缺股 missing 可见 / 次日未收盘保持 pending / 幂等 /
force 覆写 / pytest 护栏（真实腾讯调用拦截）/ dry-run 零写入。
