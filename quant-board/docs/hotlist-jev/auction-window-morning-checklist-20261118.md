# 竞价窗晨间体检清单（2026-11-18，09:10 唤醒）

> 一键体检命令（纯只读：本地状态口 + 库读，零外呼零写库，窗内可跑）：
> ```powershell
> .\.venv\Scripts\python.exe scripts\auction_window_check.py            # 当日
> ```

## 时间轴与动作

| 时点 | 动作 | 纪律 |
|---|---|---|
| 09:10 | 跑一次体检（盘前静态面）：A 进程 + B flags 必须全 ✅ | 只读 |
| 09:15–09:27 | **纯观察，零干预**：不改代码 / 不翻 flag / 不重启 / 不跑探针 / 不手动补数据 | 窗内纪律（11-17 承诺） |
| 09:27 | 冻结后跑体检 → 记录 ①③④ 判定 + tick 时间轴 | 只读 |
| 09:26 挂链后 | 核对 D 节：trialState 源头 / mblState / roster / bidSupplement | 只读 |
| 09:35 | 终态核对 E 节（日档页完整）；09:41 可再做一次全量体检 | 只读 |

## 判定表（验收口径 = prereg §7.13，2026-11-17 定案）

| 项 | 判定 | 今日(11-17)基线 | 明早达标线 |
|---|---|---|---|
| ① 首 tick | ≤ **09:15:30** | 09:15:57（❌，旧时序） | 前插修复生效 → 提前 |
| ② max/first 值层 | 无 Wzs 真值参照（退役），作**时序健康度代理**：趋近 1 = 首 tick 抓在拉升段前 | 见体检输出 | 趋近 1，逐股值层留用户裁决 |
| ③ posture 首末帧翻转率 | ≤ 涨停开盘 **3/4** 基线（§7.9 首末帧语义） | 36%（24 dec/42 mnt） | ≤36% 或维持 |
| ④ 窗内 tickN | ≥ **20** | 4（❌，7.5 分钟空窗） | 前插 + 轮转 → 10+ |
| 源头 | trialState.source == `kpl_bidding_series_derived`（Wzs/HTTP 零参与） | ✅ | ✅ |
| 日档 | bid 通道 pages_missing==[]，页 4/4 | ✅（220 成员） | ✅ |

## 重点观察项（区别于基线日）

1. **前插修复首战**：pid=8 页订阅前插（~2-5s 落地 vs 旧 15-40s）→ 首 tick 应显著早于 09:15:57、空窗应消失
2. **rst 是否复发**：A 节 sessions/errors/断连/死因——收敛面（~29 帧）窗内首次过高峰负载
3. **tick 密度 vs 会话寿命交互**：若 tickN 仍低但 rst=0，剩余变量=服务端初始推送延迟 → 窗后做「订阅落地时刻 vs 首帧到达」逐会话对账
4. **roster pushState**：昨日为 None（股数 7 来自 stocks 投影）——确认 09:26 job 正常写 pushState

## 应急预案（只在窗后执行，窗内零动手）

- 若 A 节出现 rst/断连：**先记录死因+err_code+时间轴，不重启**；窗后跑
  `probe_kpl_burst_surface.py --staged` 按帧类定位触发源（探针预算：≤14 会话/冷却 ≥180s）
- 若 trialState 缺席：确认 D 节 trialState 具体缺席态（source/fetch_failed/absent）——
  MBL(mblState) + 腾讯补源 + 日档是独立旁路，roster 链不因 socket 死而断
- 全部判定完成后才考虑任何干预；干预前列出：路径、文件清单、回滚方式、验证命令

## 关联文档

- prereg：`auction-trial-direct-probe-preregistration-20261116.md` §7.13（Wzs 出链 + 主链正名）
- 订阅风暴定案：`docs/kpl-socket/README.md` §3.6
- 体检脚本：`scripts/auction_window_check.py`（本清单判定全部由此脚本输出）
