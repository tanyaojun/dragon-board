# KPL 题材数据治理 P1-P4 实施登记（2026-10-25）

> 立项：用户裁定「KPL 题材数据治理」（题材周期方案无限期延后，待题材数据达到
> 题材情绪周期要求后再启动）。前史：题材周期 V1/V2 已全量回退（0f1539a4）。
> 用户批准：2026-10-25「P1-P4 全部批准，请执行」。
> 关键裁定：KPL 题材名称尽量和 jiuyan 板块保持一致（大盘情绪与题材情绪综合考量）；
> 机器人家族仅官方背书对挂靠（宇树/优必选），智元/小米/AGV/外骨骼不挂；
> 36 对候选全清单一次批（实扫 374 对，泛词过滤后 100 对登记 pending）。

## 〇、结论先行

| 层 | 内容 | 状态 |
|---|---|---|
| P1 | 名录治理：非题材剔除 3 条 / 官方背书家族挂靠 2 对 / 横切假父子禁挂 21 父 / 异名对=空结论 | ✅ 落库 `theme_dict_governance`（gov-v1） |
| P2 | 主题材判定重造（跟强不跟弱）：`active_theme.resolve_active_theme` 纯函数 + projection 接线 | ✅ 大业基准通过 + 月度匹配率 2 倍提升 |
| P3 | HotNum（题材内个股人气）入 `theme_stock_mappings.stockHot` | ✅ 下次 08:30 刷新生效 |
| P4 | KPL题材名↔jiuyan产业库对照层 `theme_industry_mapping`（复用板块节点 V3 引擎） | ✅ auto 51/248 + manual 1 条（人形机器人→国产机器人等 3 节点）+ 家族继承 |

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
- **现状**：auto 51/248（exact 22 + contains 29）；manual 1 条=
  人形机器人→[国产机器人, 特斯拉机器人, 机器人零部件]；
  **家族继承**：宇树/优必选机器人无直接映射时继承父题材对照
  （matchType=family_inherit<人形机器人>，effective_mapping_of 消费治理层 familyLinks）。
- **后续**：映射率提升路径同 V3 先例（auto 55%→manual 补齐 82%），剩余 197 条
  未收录待逐批人工裁定。

## 六、测试与验证

- `tests/theme/test_active_theme.py`（22 用例）：大业基准/排序键/fail-visible/
  家族挂靠/两代格式/治理层落库幂等/对照层继承/归一对称。
- `tests/snapshot/test_snapshot_derivation.py`（+2）：端到端接线（强度判定替换
  列表序 + 无强度 fail-visible）。
- 回归：snapshot_collector + snapshot + theme 三目录 1222 passed；8 failed=
  `test_theme_fund_cache.py` 存量失败（git stash 对照未改动基线同样 8 failed，
  与本次无关，如实披露）。

## 七、已知局限（如实登记）

1. **历史 stock_rows 不回填**：snapshot_stock_rows 的旧 mainTheme（含大业 9-10 月
   403+241 条「轮胎」行）保持原样——采集时快照不改写（口径纪律）；新判定自
   部署时刻起生效，历史正确口径可用 resolve_active_theme 回放重算（79 个交易日
   有 sector 强度原料），是否回放落新字段待后续裁决。
2. **匹配率绝对值天花板**：KPL 题材名与 jiuyan 分组名天然不同粒度（KPL 251 细分
   vs jiuyan 流式粗分组），匹配率不会到 100%；判定正确性以案例基准+候选透明
   （mainThemeBasis/candidates）为准，匹配率只作相对对照。
3. **familyLinks 挂靠语义边界**：仅 active_theme 判定候选扩展消费；不修改
   theme_stock_mappings 成分（KPL 官方成分不动）。
4. **P3 stockHot 增量生效**：只对新刷新行写入，旧行无该字段（消费端按缺失处理）。
5. **_theme_governance 缓存 10 分钟**：apply 治理后最多延迟 10 分钟生效（8001
   采集进程内缓存）；重启立即生效。
6. **P4 未收录 197 条**：auto 引擎字面匹配天花板，同 V3 需 manual 逐批补齐；
   现阶段对照层只读不强制（消费方按未收录 fail-visible 处理）。
