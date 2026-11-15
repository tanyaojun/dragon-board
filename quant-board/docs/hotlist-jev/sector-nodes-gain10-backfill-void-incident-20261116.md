# 板块节点深历史回填被「TDX 日线不可用」静默清空事故（2026-11-16）

## 现象

JEV 叙事工作台「板块节点」页，2026-11-04 及更早日期只剩 0~2 个板块（如 11-04 仅「光伏」），
页面 status=ok、无降级注记；2026-11-05 起正常（15~23 板块）。用户初判为 11-14 新增
root 板块对照层（`jiuyan_industry_root_mapping`）引起——**排查否决**：

- 板块节点档板块名取自 `jiuyan_action :final` 原始分组名，不经 root 对照层；
- 坏档 `computedAt=2026-11-12 00:27~00:29`（root 上线前两天），此后无进程重写过。

## 根因

1. v5 空间龙一需 10 日涨幅（`gain10_from_bars` 需 ≥ window+1=11 根 ≤ end_date 收盘棒）；
2. gain 取数链 `fetch_gains10 → fetch_daily_bars(offset=15)` 固定只拉最近 15 根
   （与 `_daily_bars` 的 `JEV_BARS_OFFSET` 长窗默认 250 不同源）；
3. 2026-11-12 00:27 一次 `sector_nodes --backfill`（约 10-23..11-11）在深夜 TDX/长窗
   缺口下重算：end_date=11-05 恰好 11 根达标幸存，**≤11-04 只有 10 根以下 → 每板块
   gain10 全 None → 整板块被判「10日涨幅不可算（TDX 日线不可用），板块跳过」**
   （`meta.spaceErrors` 有逐板块留痕，但 status 仍 ok，页面无注记 → 静默清空两周）；
4. 连带污染：11-05..11-13 的 `prev_nodes`（昨日节点链）从刚写坏的 ≤11-04 档读出，
   全链 prevNode 缺失、弱转强判据失效；`_default_day_change_fetcher`（断板候选
   跌停剔除）同款固定 15 根，深历史日恒 None（伴生缺陷，一并修）。

数学分界验证：11-12 回填时最新棒 11-11，≤11-05 恰 11 根（=window+1 过线）、≤11-04
10 根（不足）——与好/坏档分界严丝合缝。同类坑 `leader_wzs.bars_covering`（阶梯
15→250 覆盖式）早已解决过，但 `fetch_gains10` 未接入。

## 修复（2026-11-16，用户批准）

- `operations/tdx_daily_bars.py`：`bars_covering`/`covering_day_change_fetcher`
  自 leader_wzs 下沉为单源；`fetch_gains10` 改覆盖式取数（min_dates=window+1，
  阶梯 15→40→80→160→250，首档即命中当日链零额外成本，深历史自动升档，各档位
  进 `_BARS_CACHE` 同进程多日回填首日后零网络）；
- `operations/leader_wzs.py`：删除本地第二套实现，改 re-export（消费方导入路径不变）；
- `operations/theme_leader_baseline.py`：`_default_day_change_fetcher` 改委托
  覆盖式单源；
- 数据恢复：`sector_nodes --backfill --from 2026-10-23 --to 2026-11-13`（升序成链、
  确定性幂等覆盖），16 个交易日全部恢复 11~23 板块、prevNode 链完整、gain10 有值、
  spaceErrors 归零（个别 1 条为单板块合法留痕）。

## 遗留（待用户裁决，未实施）

整日 spaceErrors 大面积板块跳过时 status 仍 `ok`，页面「数据源属正常」且无注记
——本次坏档静默躺两周的直接原因。是否把「板块全跳过」升为 degraded / 页面注记，
涉及预登记改档，另行裁决。

## 后续处置（2026-11-16 续，用户裁决 A+C）

1. **回填前置检查落码**：新增 `operations/backfill_preflight.py`（依赖链存档健康度
   逐日报告；烧 token 的 relay 重放在节点档坏账时默认阻断 `EXIT_BLOCKED=3`，
   `--allow-unhealthy` 显式越过；确定性重算链只报告+gain10 可达性抽检——抽检
   None 占比 >0.5 默认阻断，即 11-12 事故的直接信号）。接线三个 CLI：
   `sector_nodes --backfill`、`jev_relay_index --relay-day --force`、
   `market_cycle --backfill`（报告型）；schedule 盘后单日路径不接（零开销，
   健康度由档内 fail-visible 字段披露）。测试 `tests/operations/test_backfill_preflight.py`。
2. **事故范围修正**：前置检查发现 11-12 事故回填实际起点是 **2026-09-11 之后的
   10-12**（10-12~10-22 共 8 个 v5 空档；10-08/10-09 及更早仍是 v4 旧代档）。
   已用新 CLI 回填 2026-09-11..10-22（24 日，preflight gainSample noneRatio 0.0，
   10-24 周末无 final 合法保留 v4）——全部交易日节点档现为 v5 ok 且有行。
3. **relay 20 日重放（方案 A）**：10-08..11-04 共 20 档 `--force` 重放，preflight
   通过（ledgerBad=0），20 次 jev 调用 ≈18.8 万 tokens，全部 status=ok；重放后
   梯队表「龙一档缺失/回退」注记 0 残留（语料完整口径）。分数/相位前后对照：
   index 变动 ±10 以内为主（10-20 43.8→29.9、10-21 53.0→33.0 变动最大），相位
   翻转 3 例（10-13 bottoming→launch、10-14 divergence→collapse、10-21
   relay_heat→divergence，为语料修复后的重判，非异常）。daysInPhase 链升序重算一致。

## 防复发要点

- 任何对距今 >4 个交易日的 v5 回填/重算，必须走覆盖式日线入口（`bars_covering`
  / `fetch_gains10` / `covering_*_fetcher`），禁止直接消费 `fetch_daily_bars`
  默认 15 根档；
- 回填类操作的产物若出现「板块数骤降」应视为事故信号（对照 `meta.spaceErrors`）。
