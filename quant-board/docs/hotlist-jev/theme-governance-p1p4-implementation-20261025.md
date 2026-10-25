# KPL 题材数据治理 P1-P4 实施登记（2026-10-25）

> 立项：用户裁定「KPL 题材数据治理」（题材周期方案无限期延后，待题材数据达到
> 题材情绪周期要求后再启动）。前史：题材周期 V1/V2 已全量回退（0f1539a4）。
> 用户批准：2026-10-25「P1-P4 全部批准，请执行」；同日追加三项指令：
> 「历史数据按新规则重算 / 逐一匹配达到最高值 / 正式挂靠」→ T1/T2/T3 全部执行。
> 关键裁定：KPL 题材名称尽量和 jiuyan 板块保持一致（大盘情绪与题材情绪综合考量）；
> 机器人家族仅官方背书对挂靠（宇树/优必选），智元/小米/AGV/外骨骼不挂。

## 〇、结论先行

| 层 | 内容 | 状态 |
|---|---|---|
| P1 | 名录治理：非题材剔除 3 条 / 官方背书家族挂靠 2 对 / 横切假父子禁挂 21 父 / 异名对=空结论 | ✅ 落库 `theme_dict_governance`（gov-v1→v2） |
| P2 | 主题材判定重造（跟强不跟弱）：`active_theme.resolve_active_theme` 纯函数 + projection 接线 | ✅ 大业基准通过 + 月度匹配率 2 倍提升 |
| P3 | HotNum（题材内个股人气）入 `theme_stock_mappings.stockHot` | ✅ 下次 08:30 刷新生效 |
| P4 | KPL题材名↔jiuyan产业库对照层 `theme_industry_mapping`（复用板块节点 V3 引擎） | ✅ **T2 逐一匹配后 202/248=81.5%**（exact 22+contains 29+manual 151；46 无对应节点留白） |
| T1 | 历史重算（用户指令 1）：760,991 行 mainTheme 全量按新规则重放 | ✅ 90.3% 判出（sector 44.8 万+行内跨代 heat 24.3 万）；原料断档 6.6 万如实 None+标记 |
| T2 | 逐一匹配（用户指令 2）：196 未收录题材逐一语义映射 | ✅ 150 对 manual 挂上，映射率 51→81.5% |
| T3 | 正式挂靠（用户指令 3）：100 候选×成分重叠率验证 | ✅ familyLinks 2→18 对（gov-v2），78 对拒绝 |

## 一、根因链（大业股份 603278 被判「轮胎」）

1. **采集侧顺序**：`mongo_theme_repository.get_stock_themes` 按 `themeId` **字符串升序**
   排（"223"轮胎 < "84"人形机器人）→ themes 列表轮胎在前；
2. **投影侧取首**：`snapshot_derivation/projection.py` 旧代码 `row_themes[0]` 直接作
   mainTheme/sectorLabel——顺序即判定，与当日炒作零关系；
3. **连带污染**：mainTheme 错 → themeHeat/themeRiskFlags 挂错题材的 sector 行。
4. **语义层缺陷**：即使有排序，排的也是题材自身热度，非「该股当日因哪个题材炒作」。

旧 mainTheme vs 当日 jiuyan 分组匹配率（治理前复测）：07 月 11.1% / 08 月 15.7% /
09 月 12.2% / 10 月 9.9%——远不达标。

## 二、P1 名录治理（`theme_dict_governance` 集合，`_id=THEME_GOV`）

**单一事实源分工**：`themes`/`theme_stock_mappings` = KPL 上游镜像（08:30 每日覆盖，
治理信息不落这两集合防被冲掉）；`theme_dict_governance` = 人工层，baseline 定义在
代码常量 `backend/services/theme/dict_governance.py`（git 管版本），apply 幂等整写。

- **excludeThemeNames（3 条）**：中证A50成分股（指数成分归类）/ 大基金持股 /
  汇金证金持股（持股归类）——非炒作题材，不作主题材候选。
- **familyLinks（2 对）**：宇树机器人→人形机器人（官方 Table L1[宇树相关]:
  参股17+合作商27）、优必选机器人→人形机器人（参股4+合作商8+供货商4）。
  挂靠语义=子题材成分股的候选扩展并入父题材（active_theme 判定消费）。
- **crossCutBoards（21 父）**：横切假父子禁挂登记。判定规则（冻结）=官方 Table
  分支 exact 匹配独立题材 ≥2。全清单：关税战概念/新质生产力/高股息/复苏消费概念/
  国企人工智能/中部崛起概念/反内卷概念/犒赏经济/出海/半导体存储器/设备更新/
  低空经济/涨价概念/比亚迪产业链/腾讯AI概念/端侧AI概念/新消费/谷歌概念/
  欧洲电力基建/词元概念/俄乌重建。人形机器人 exact=0 不在列（真产业父）。
- **aliasPairs（空）**：themes 251 内部近名扫描（双向包含）8 组全为细分关系
  （光伏⊃光伏辅材/光伏新技术等），无真异名对——空清单如实登记。
- **candidates（100 对 pending）**：分支×题材匹配对（泛词已滤），不消费，
  逐条批后升 familyLinks 或弃。全量证据
  `data/backups/theme-governance-20261025/`（full_tables.json 251/251 题材
  InfoGet Table + infoget 样本 6 份）。

## 三、P2 主题材判定（跟强不跟弱）

- 纯函数 `backend/snapshot_derivation/active_theme.py::resolve_active_theme`：
  候选=个股 themes 名单（两代格式兼容）∪ 治理层家族父题材扩展 − 非题材剔除；
  强度排序键 **ztCount 降序 → heatScore 降序 → rank 升序 → 名字稳定序**
  （涨停数是当日炒作最硬证据）；强度表由调用方注入（生产=market_context.sectors，
  回放=snapshot_sector_rows），纯函数零 IO 单一事实源。
- **fail-visible**：候选全部无当日强度行 → mainTheme=None + basis=sector_strength_missing
  （绝不回退 themes[0] 字典序伪装）；mainThemeBasis 新字段落行（判定依据可审计）。
- **接线**：projection.build_ingest_payload 加 `theme_governance` 参数 →
  derivation service 透传 → collector `_theme_governance()`（进程内缓存 10 分钟，
  repo.db 治理文档缺失=None 降级为纯强度判定，采集不阻断）。
- **验证读数**（2026-10-25 实测）：
  - 大业基准：9-24/9-29/10-19/10-20/10-22 全判**人形机器人**（旧口径全轮胎）；
    8-05 判商业航天（当日 zt=9 真实最强，合理）。
  - 月度匹配率（涨停股 mainTheme ∈ 当日 jiuyan 分组，新旧同口径对照）：
    07 月 25.1% vs 11.1% / 08 月 20.8% vs 15.7% / 09 月 18.4% vs 12.2% /
    10 月 17.2% vs 9.9%——约 2 倍提升；绝对值受 KPL名↔jiuyan名字面错位压制，
    P4 对照层承接。

## 四、P3 HotNum 入库

`_extract_mappings` 提取 `StockList[].HotNum`（个股在该题材的当日人气，此前被丢弃）
→ `replace_theme_mappings` 落 `stockHot` 字段（无键=旧代缺失不伪造）；
`get_stock_themes` 透传 `themes[].hot`。存量 13580 行待 08:30 每日刷新自然补齐。

## 五、P4 KPL↔jiuyan 对照层（`theme_industry_mapping`，_id=KPL 题材名）

- **定位**：对照桥非物理改名——KPL 侧保持官方名（08:30 刷新按官方名覆盖，
  物理改名必被冲掉），jiuyan 侧保持 jiuyan 名，本层衔接（用户「名称尽量一致」
  的落地形态=确定性映射可查）。
- **引擎**：照搬板块节点 V3 `sector_industry_map` 冻结规则（停用词/exact/
  contains 唯一/multi-union 并集/未收录 fail-visible），模块
  `backend/services/theme/industry_alias.py`，CLI `--rebuild/--set/--list`。
- **T2 逐一匹配（用户指令「逐一匹配，达到最高值」）**：196 未收录题材逐一
  语义映射 manual 150 对（脚本批固化，产业库校验零错误），auto 51 + manual 151
  = **202/248 = 81.5%**（与板块节点 V3 manual 补齐后 82% 同档）。
- **46 留白清单（无对应产业节点，fail-visible 不强凑）**：事件主题（俄乌重建/
  对日反制/小米发布会/人民币升值等）、区域主题（新疆/海南封关/西部大开发/
  中部崛起等）、横切视角（涨价概念/高股息/反内卷/新质生产力）、无对应品类
  （光伏/钙钛矿/BC电池/医美/消费电子/MR/折叠屏/量子科技/5G-A/轮胎外品类等，
  其中光伏系因产业库无光伏节点）、京东概念/华为甄选（无电商节点）。
- **家族继承**：宇树/优必选机器人无直接映射时继承父题材对照
  （matchType=family_inherit<人形机器人>，effective_mapping_of 消费治理层 familyLinks）。

## 五A、T3 正式挂靠（用户指令，gov-v1→gov-v2）

**判据（冻结）**：candidates 100 对 × 成分股重叠率（|child∩parent|/|child|，
theme_stock_mappings 实测）双峰分布——≥0.40 自动晋升（13 对）；0.30-0.40 仅
产业链/品牌真细分人工裁定（4 对）；<0.30 全拒（78 对：横切视图/兄弟大类/
事件关联，挂靠将稀释主题材判定）。familyLinks 语义=child 细分挂 parent 大类
（固态电池概念/光伏辅材 2 对候选方向修正；核电↔可控核聚变双向只保留细分→大类）。

晋升 18 对全清单（child→parent，重叠率）：宇树机器人→人形机器人 0.913 /
优必选机器人→人形机器人 0.704 / 卫星互联网→商业航天 0.808 / 锂矿→锂电池材料
0.690 / 华为液冷快充→充电桩 0.667 / 农机概念→农业种植 0.588 / 液冷服务器→AI硬件
0.564 / 可控核聚变→核电 0.564 / 钙钛矿电池→光伏新技术 0.471 / 旅游→服务消费概念
0.442 / 京东概念→外卖概念 0.417 / 硅→光伏 0.407 / 摩尔线程概念→国产芯片概念
0.405 / 固态电池概念→锂电池材料 0.406（方向修正）/ 超节点概念→华为昇腾 0.37
（人工）/ 光伏辅材→光伏 0.367（方向修正）/ 激光雷达→智能驾驶系统 0.316（人工）/
AI低代码概念→AI智能体概念 0.304（人工）。

拒绝代表例（重叠率实锤）：商业航天→旅游 0.023 / 煤炭概念→高股息 0.048 /
MR概念→教培 0.0 / 军工信息化→军工 0.249（方向反：军工是大类）。

## 五B、T1 历史重算（用户指令）

- **回滚保障**：旧 mainTheme 全量归档 `data/backups/theme-governance-20261025/
  stockrows_maintheme_archive.jsonl.gz`（760,991 行，restore 命令可回滚）。
- **重放口径**：逐 (tradingDate, slotTime) hot_theme 强度表（同槽优先→同日更早槽
  回退防未来函数）→ resolve_active_theme（gov-v2 治理层：18 挂靠+3 剔除）→
  bulk 更新 mainTheme/sectorLabel/mainThemeBasis/themeHeat/themeRiskFlags。
- **跨代强度源（26.7 万行）**：4-7 月旧代 dict themes 自带 heatScore（5 月 83%/
  6 月 84% 覆盖），sector 断档时段用作行内强度源，basis=`legacy_inrow_heat:`
  前缀如实标注口径差异（仅热度轴，无 ztCount/rank）。
- **结果（760,991 行）**：90.3% 判出 mainTheme（sector 判定 447,628 + 行内跨代
  243,027）；原料真断档 64,989 行（5-6 月 sector 整月缺席+dict 无 heat 的日）+
  行内也全缺 816 行 → mainTheme=None + basis 标记（fail-visible，不伪装）；
  all_themes_excluded 4,531（非题材三条件）。
- **大业基准复核（EOD 槽）**：9-24/9-29/10-19/10-20/10-22/10-23 人形机器人；
  9-28/10-08/10-21 商业航天（当日航天 zt/rank 确实更强=跟强不跟弱的正确动态
  切换）；旧口径同期全为「轮胎」。

## 六、测试与验证

- `tests/theme/test_active_theme.py`（22 用例）：大业基准/排序键/fail-visible/
  家族挂靠/两代格式/治理层落库幂等/对照层继承/归一对称（T3 后断言更新为 18 对）。
- `tests/snapshot/test_snapshot_derivation.py`（+2）：端到端接线（强度判定替换
  列表序 + 无强度 fail-visible）。
- 回归：theme+snapshot 目录 624 passed；8 failed=`test_theme_fund_cache.py`
  存量失败（git stash 对照未改动基线同样 8 failed，与本次无关，如实披露）。

## 七、已知局限（如实登记）

1. **历史重算的跨代口径差**：4-7 月 24.3 万行走行内 heatScore（仅热度轴无
   ztCount/rank），与 7 月后 sector 三键口径不同级；basis 前缀已如实标注，
   跨代比较须过滤 basis。
2. **5-6 月 sector 断档日不可判**：64,989 行（8.6%）mainTheme=None + basis
   `sector_strength_missing_recompute`——sector 整月缺席+dict 无 heat 的日，
   原料真不可用（§4.0 允许不写的唯一情形）；旧值可从归档恢复。
3. **匹配率绝对值天花板**：KPL 题材名与 jiuyan 分组名天然不同粒度（KPL 251 细分
   vs jiuyan 流式粗分组），匹配率不会到 100%；判定正确性以案例基准+候选透明
   （mainThemeBasis/candidates）为准，匹配率只作相对对照。
4. **familyLinks 挂靠语义边界**：仅 active_theme 判定候选扩展消费；不修改
   theme_stock_mappings 成分（KPL 官方成分不动）。
5. **P3 stockHot 增量生效**：只对新刷新行写入，旧行无该字段（消费端按缺失处理）。
6. **_theme_governance 缓存 10 分钟**：apply 治理后最多延迟 10 分钟生效（8001
   采集进程内缓存）；重启立即生效（T3 落库后已重启）。
7. **46 留白题材**：事件/区域/横切/无对应品类主题无产业节点可挂（清单见 §五），
   对照读口按未收录 fail-visible；若后续产业库新增节点（如光伏），补挂即可。
8. **重叠率受 mappings 覆盖噪音影响**：题材定义宽窄影响重叠率读数（如超节点
   0.37 靠人工语义裁定补判），T3 判据是「重叠率主判+语义复核」双保险。
