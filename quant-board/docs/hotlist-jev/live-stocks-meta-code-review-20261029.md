# live-stocks-meta code review（2026-10-29）

- 对象：commit 9c963ee0（main HEAD，已核实 refs/heads/main）。直播个股表补齐 地位/换手/连板/概念 四列。
- 审查人：reviewer 子代理（fresh context，只读审查，未改动仓库）。
- 结论：**OK with notes**。后端并发/状态机/fail-visible 结构扎实，无 P0；P1×2（均为前端呈现与重试退避层）修复后提交。

## 一、验证命令实测

本审查会话无 shell 执行工具，pytest 未实际运行（not-run），由父会话代跑：

```
cd d:/dragon-board/quant-board
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -m pytest backend/services/__tests__/test_kpl_ranking_service.py tests/api/test_kpl_proxy_routes.py tests/hotlist/test_relay_page_theme_leaders.py -q
```

静态审读结论：三处测试均经 monkeypatch mock（`_post_form` / `get_sector_ranking` / `get_sector_stocks`），零真实 KPL 上游调用，符合红线 §1.2.7。

## 二、逐项审查

### 2.1 并发正确性 —— 通过
- entry 替换仅发生在 `state ∈ (None, error)` 或 done 过期（kpl_ranking_service.py:661-666）；error/done 均为线程 return 前最后写入（:632-641），故 building 期间不可能二次起线程，同日期无双构建。
- 线程锁外 start（:676-679），与注释一致（锁内 start 在同步/重入执行下会死锁——2026-10-29 测试死锁实录）。
- 增量合并与读口快照同锁（:628-629 / :657-671），无撕裂读；rebuild 复制旧 index（:662-663），旧线程已终结。
- 多日期并发：各自 entry/线程，`_post_form` 全局 2s 纪律串行化，正确。

### 2.2 fail-visible —— 后端彻底，前端有缺口
- 后端：盘前空排行→error（:607-612）、线程崩溃→build_crash（:635-638）、missed 如实分账（:671）、failed_plates 计数，均有测试。
- 前端缺口（P1-1）：`error`/`failedPlates` 未消费，fetch 失败静默。

### 2.3 与既有 _cache/限频交互 —— 通过
- 构建复用 get_sector_stocks (plate,date,page) 30s TTL，循环内每页只调一次，无退化重扫；重建轮全量重扫 ~80 发符合预算。

## 三、问题清单

### P1-1 前端未消费 error/failedPlates，失败态与「不在宇宙」UI 不可区分
- 位置：backend/relay_page/index.html:5604-5612（.then 只读 hits/building，.catch 静默）；:5585（failed-plate 个股 tooltip 误标「未入宇宙」）。
- 证据：后端 payload 带 error/failedPlates（kpl_ranking_service.py:670-672）但前端不读；jget 抛错仅 `m.failedAt=now`。表格静默回退全 "--" = 用户本次报告的表象复现，违反 AGENTS.md §4.0。
- 修法：r.error → kplLiveBanner 提示（自动重试中）；r.failedPlates.length → 提示「N 个板块构建失败」；.catch 同样 banner；tooltip 区分「未入宇宙 / 构建失败」。

### P1-2 error 态重建无退避，sig 变化放大为无上限重试
- 位置：kpl_ranking_service.py:662-667 + index.html:5601-5602。
- 证据：state=error 时任意调用即重起线程；雷达流新个股每 ~8s 换 sig 绕过前端节流 → 上游不可用/盘前时最坏每 ~8s 一轮排行请求。
- 修法：entry 记 last_attempt_at，error 态重建加最小间隔（60s），间隔内直接返回当前 error 态。

### P2（本次一并修复）
1. index.html:5602 `m.failedAt ? 45000 : 45000` 死三元，注释与实现不符 → 失败分支 90s 退避。
2. building setTimeout 链多条并存、kplLiveLeave 不清链、回调不校验视图激活 → 单 timer + clearTimeout + 视图激活检查。
3. 历史模式进直播页时 meta 按历史日构建、消息流为实时 → 直播页固定 KPL.today。
4. `_stocks_meta_cache` 无日期淘汰，长驻进程跨日累积 → 保留最近 5 日，淘汰非 building 项。
5. 测试缺口：failed_plates 记账、TTL 过期重建（stale 旧索引可用）、building 渐进 hits、error 重建退避。

## 四、绿灯条件

1. P1-1（前端失败态呈现）——必须 ✓
2. P1-2（error 重建退避）——必须 ✓
3. P2 全部可后续跟进（本次一并修复）

## 五、Praise（保持项）

- 锁外 start 线程附实测死锁注释；空排行不伪装 done 附判别探针证据链；构建注释写明上游成本预算推导——可审计性好。
