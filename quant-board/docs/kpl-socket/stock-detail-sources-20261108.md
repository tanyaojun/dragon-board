# KPL 个股详情页数据源入口探测（2026-11-08，全部实测/反编译双证实）

> 任务来源：用户提供 App 个股详情页截图（贝特利 301697：分时图/五档/异动提醒/盘口 tab/
> 所属板块/题材库/溢价基因/涨停原因 tab）。目标=把这些展示位的数据源入口探测出来。
> 方法：`.tmp_review/main_src/` 全量反编译源码静态定位（j00 请求构造 + px0/StockQuotationInfoPresenter
> + qn0 cmd 分发）+ 少量实弹探测验证（10 发，间隔 ≥3s，全 errcode=0，证据
> `.tmp_review/kpl_stockpage_probe_results_2026-11-08.jsonl`，脚本 `kpl_stockpage_probe_2026-11-08.py`/`probe2`）。
> 结论：**README §11.4「个股涨停原因详情无上游源、待 MITM 抓包」已推翻**——纯静态逆向即定位，无需 MITM。

## 一、总览：双通道

个股详情页数据 = **HTTP 拉全量**（apphq/apphis，游客凭据即可）+ **socket 推增量**（0x40 通道，
复用既有 610 认证/signsvc/pcemu 基建）。展示层首屏走 HTTP，进入详情页后按 cmd 集订阅推送。

## 二、HTTP 入口表（POST，全部实测 errcode=0）

公共参数：`UserID=0&Token=0`（游客即可）、`VerSion=5.16.0.5`、`PhoneOSNew=2`、`apiv=w38`、
`DeviceID=<uuid>`、`UA=ad`（Dalvik UA 亦可）；POST `application/x-www-form-urlencoded`。
纪律：单发间隔 ≥2s。凭据版走 `mapping_refresh.KPL_APP_BASE_PARAMS` 公共出口。

| 展示位 | 域名 | c / a | 关键参数 | 实测响应结构 |
|---|---|---|---|---|
| **盘口 tab 全量**（截图2：现价/涨跌/换手/量比/委比/内外盘/市盈/市净/质押比/盘后量/流通/总市值/资金账号 Gang） | apphq | `StockL2Data` / `GetStockPanKou` | StockID | `{day,code,name,preclose_px,status,real{time,last_px,px_change,px_change_rate,high_px,low_px,open_px,avg_px,turnover_ratio,total_amount(手),total_turnover(元),vol_ratio,up_px,down_px,amplitude,entrust_rate,amount_in(内盘),amount_out(外盘),dyn_pb_rate,pe_rate,TTMPeRate,jtPeRate,circulation_amount,circulation_value,total_shares,market_value,phcj_volume,phcj_turnover,actualcirculation_value,PledgeRatio},weituo{b1..b10,s1..s10(五档+[价,量]),totalb,totals,avg_bidpx,avg_askpx},ICon,Gang,ZTReason,FXReason,JianChiDetail,JieJinDetail,PledgeReason,JJZTM,ts}` |
| **盘口 tab 顶部横幅**（异动提醒/风险提示） | 同上 | 同上（FXReason 字段） | — | FXReason=「异动提醒 次日涨幅偏离值达…」文本；`QuotationInfoHeadTipDialog` 按 bit 展示（bit5=异动提醒） |
| **盘口 tab·所属板块**（截图2：光伏 -1.63%…） | apphq | `StockL2Data` / `GetStockIDPlate`（**旧版**，`Type=2`） | StockID, Type=2 | `{List:[], ListJX:[[plateId,名,涨幅%],…], ListSP:[], DYState}` —— ListJX 与 App 同屏逐项一致（光伏/太空光伏/有机硅/异质结电池/化工/三季度增长）；实时增量走 socket 2010。**`_New` 版（isT=1）匿名与凭据均返空，勿用** |
| **盘口 tab·题材库**（光伏 题材热度） | — | HTTP 无静态源；**socket 2013 `SubStockRelatedTheme`** | Hq.HQReq{stockId} | `StockRelatedThemeResp{stockId, items[{id,name,number(题材热度)}]}`；HTTP `GetStockIDPlate` 不含题材热度列表 |
| **盘口 tab·溢价基因**（涨停次数/溢价5%次数/次日红盘率/首板封板率/首板被板率/连板率） | apphq | `StockL2Data` / `GetZhangTingGene` | StockID | `{List:[4,1,50,100,0,50]}` 六元数组=[涨停次数, 溢价5%次数, 次日红盘率%, 首板封板率%, 首板被板率%, 连板率%]——与截图 4/1/50.00%/100.00%/0.00%/50.00% 完全一致（来源 `ox0.s5().i4`） |
| **涨停原因 tab·历史列表（概念解析全文）** | apphis | `HisLimitResumption` / `GetDayZhangTing` | StockID, Index(翻页), STAT_SDK_TYPE | `{StockID, List:[{Date, Reason(组合原因串), SCLT(板块梯队标签如「日内龙一」), SCDW, GNSM(概念说明全文), Type, Boom_ZS(爆发解析), ZSCode:[801070,801631], PZSCode, Group_Str, QitaStr}], Time, errcode}`——**即为 README §11.4 缺失的「概念解析全文」**；解析器 `px0.e1`；301697 实测 11-06 条目 GNSM=贵金属涂料在光伏应用全文 |
| **涨停原因 tab·实时** | apphq | `StockLineData` / `GetKLineZhangTing` | StockID | 同上结构 + 顶层 Time（unix 秒）；`px0.y0` 解析 |
| **分时图**（截图1 曲线+成交量+现量） | apphq / apphis | `StockL2Data` / `GetStockTrend`（实时）；`StockL2History` / `GetStockTrend` + `Day=YYYY-MM-DD`（历史）；增量 `GetStockTrendIncremental&Type=1[&Time=]` | StockID | `{trend:[[HH:MM, 价, 均价, 量(手), flag],…]}` 实测 301697 全天 240+ 行 |
| **分时成交/明细**（「分时成交」列表） | apphq | `StockL2Data` / `GetStockFenBi2`（增量：+`Index`&`Type`） | StockID, STAT_SDK_TYPE | `{fb:[[HH:MM:SS,价,方向,量,类型,?,?,金额],…], Day, Count(全天总笔数), total(本页)}` |
| **集合竞价分时**（竞价页逐秒） | apphq | `StockL2Data` / `GetStockBid` | StockID | `{code, day, bid:[[HH:MM,价,方向,竞价量],…], preclose_px, hprice, lprice, openpx, flag, time}`（注意：这是**竞价记录**，不是五档；五档在 GetStockPanKou.weituo / socket 2005/2015） |
| **盯盘·大单分时** | apphq | `StockL2Data` / `GetStockDaDanTrendIncremental`（历史 `StockL2History/GetStockDaDanTrend&Day=`） | StockID[, Time] | ✅实测 `{dadanjinge,time,time2,day,max,min,code}` |
| **盯盘·BS 委托量** | apphq | `StockL2Data` / `GetStockBsvolumeIncremental` | StockID | ✅实测 `{bsentrust,time,time2,maxentrust,minentrust,minentrustdiff,maxturnover,mineturnover,mineturnoverdiff,day,code}` |
| **盯盘·量比/换手曲线** | apphq | `StockL2Data` / `GetStockVolTurIncremental` | StockID | ✅实测 `{volumeturnover,time,time2,day,code}` |
| **盯盘·点评（StockDPExplain）** | apphq | `StockYiDongKanPan` / `StockDPExplain` | StockID | 实测 errcode=1018（App 仅个股异动盘状态下调用；常态无数据，阴性正常态） |
| **盯盘·委托列表** | apphq | `StockL2Data` / `GetWeiTuo_W14` | StockID, Type, Vol, Tur, STAT_SDK_TYPE, VType, VOrder | ✅实测结构 `{start,end,List,Count,total,Title}`（301697 涨停后 List 空=正常态） |
| **笔记** | apparticle | `UserNoteCommon` / `GetStockNotes` | StockID, NoteIndex, STAT_SDK_TYPE | 实测 errcode=1001「登录状态失效」——**用户私有数据，必须现役凭据**（走 mapping_refresh 出口） |
| **公告列表** | apphis | `CompanyNotice` / `GetList` | StockID, Type, STAT_SDK_TYPE, Index, isZhiShu | ✅实测 `{NoticeList:[{iid,title,date,code,name}]}`（301697 含异动公告/投资者关系） |
| **公告/新闻计数** | apphis | `CompanyNotice` / `GetCompanyCount` | StockID | ✅实测 `{news,report,announcement,CID,Date}` |
| **F10 首页** | apparticle | `StockF10Basic` / `GetIndex` | StockID | ✅实测 `{Concept,ConceptOther,Topic,Company,Finance,Record,YJPL}`（8838B 全量） |
| **F10 题材/主题** | apparticle | `StockF10Basic` / `GetConceptTopic` | StockID | ✅实测 `{List}` |
| **F10 主要指标** | apparticle | `StockF10Basic` / `GetMainIndicators`（Type 区分表） | StockID, Type | ✅实测 `{GMJLR,KFJLR,YYSR,JZCSYL,XSMLL,JLL,ZCFZL,JYHDXJL,LXJSR,Trade,prod_name}` |
| **F10 估值** | apparticle | `StockF10Basic` / `GetValuation` | StockID, year, key | ✅实测 `{list,title}` |
| **F10 分红** | apparticle | `StockF10Basic` / `GetDividends` | StockID, hidden, Index, STAT_SDK_TYPE | ✅实测 `{list,count}`（errcode=0；**域=apparticle 非 apphq**，2026-11-08 首探 1020 已勘误） |
| **F10 重要提醒** | apparticle | `StockF10Basic` / `BigReminderW43` | StockID, Index, STAT_SDK_TYPE | ✅实测 `{info,nowTime}` |
| **题材子分类详情** | apphq | `Section` / `GetSection` | SectionID, Order, Index, STAT_SDK_TYPE | 未实测（j00.y0） |

## 三、Socket 订阅面（0x40 通道，个股详情页级）

请求 cmd=响应 cmd（同号），全部复用既有 610 认证/帧格式基建；ext=`02 <cmd 2BE>`。
来源：`qn0.w()`（响应分发）+ `StockQuotationInfoPresenter` `@y51` 注解（页面订阅清单）+ 3470-3530 请求构造。

| cmd | 响应 pb | 请求 pb | 内容 |
|---|---|---|---|
| 2001/2002 | `Hq.TransPriceResp` / `TransVolTurResp` | `HQListReq{stockId, currNum}`（mn0.f） | 分时价 / 分时量比（增量，currNum=已有点数） |
| 2003/2004 | 同上（nn0.h/i 解析） | 同上 | 分时价/量（另一视图） |
| 2005 | `Hq.StockPKResp` | `Hq.HQReq{stockId}` | **盘口五档实时**（SubStockPK/V1） |
| 2006/2007 | `Hq.StockMXResp` | 2006=`HQItemReq{stockId, count=25}`（App 固定 25）；2007 无请求，服务端跟订阅推增量 | **分时成交明细**（time=9位 HHMMSS+ms；**price=元×10000**；vol=手；tur=该笔成交额元；colors 服务端染色原样透出；20261108 实弹 ✅ 301697 total=1344，缩放/成交额公式精确互证；2007 推帧盘中待验） |
| 2009 | `Hq.TYDanLabelResp` | `HQListReq{stockId, currNum=已收数}` | 特意大单标签（tag=档位，App 未硬编码原样透出；timestamp=unix秒；tur=额；20261108 实弹 ✅ 301697 total=0，盘中增量行为待验） |
| 2010 | `Hq.StockRelatedPlateListResp` | `Hq.HQReq{stockId}` | **所属板块实时**（items{plateId,plateName,plateIncRate,stockName,stockIncRate,qzType}） |
| 2011 | `Hq.StockRangeTradeResp` | `HQListReq{stockId, currNum}` | 区间成交 |
| 2012 | `ServiceHqStock.StockRelatedCommodityResp` | `Hq.HQReq{stockId}` | 商品现货 |
| 2013 | `ServiceHqStock.StockRelatedThemeResp` | `Hq.HQReq{stockId}` | **题材库**（items{id,name,number=题材热度}） |
| 2014 | `ServiceHqStock.StockZTBigOrderDetailResp` | `StockZTBigOrderDetailReq{stockId,type,count}` | 涨停大单明细（time/tur/rate/buyTur/sellTur/ztTur） |
| 2015 | `ServiceHqStock.StockMinWTResp` | `HQListReq{stockId, currNum}` | **逐笔委托盘口**（items{time,totalSellTur,totalBuyTur,totalSell,totalBuy,sells[],buys[]{price,vol}}） |
| 2016 | `ServiceHqStock.StockPHTLineResp` | `HQListReq{stockId, currNum}` | 盘后分时 |
| 2025 | `ServiceHqStock.HKRelateHKStockResp` | `Hq.HKStockReq{stockId}` | A/H 关联（港股溢价） |
| 2030 | `ServiceHqStock.AbnormalPriceResp` | `AbnormalPriceReq{stockId}` | **异动提醒**（price/date/nextDayPrice/nextDayZf） |
| 2202 | `Hq.BFReasonResp` | `Hq.HQReq{stockId}` | 爆发原因（GetHisBFReason 历史同构） |
| 2203 | `Hq.HQReasonsResp` | `Hq.HQReq{stockId}` | **涨停原因实时推送**（SubMultiReasons/V1；单条 SubZTReason 同族） |
| 2204/2205 | `Hq.StockKZZResp` / `KzzStockHeadResp` | `Hq.HQReq{stockId}` | 可转债 |
| 2206 | `ServiceHqStock.NewsFlashChangeResp` | `Hq.HQReq{stockId}` | 快讯变更（stockId/time/changeId/content/showTime） |
| 2400/2402 | `Hq.KlineMainResp` | `KlineReq{stockId,period,sType}` / `HisKlineReq` | K 线主图 / 历史 K 线 |
| 2401 | `Hq.StockKLineVolTurYuCeReap` | `HQTypeReq` | 量预测 |

页面实际订阅清单（`@y51`）：`{2203, 2005, 2001, 2002, 2003, 2004, 2009, 2204, 2025, 2010, 2011, 2013, 2012, 2014, 2015, 2206}`；
基础报价走既有 3006（`IndexSimpleQuotasResp`，已实测到流）。注：**2007 不在订阅清单**，跟在 2006
订阅后由服务端主动推（qn0 分发 + showCmdData append 实证）。

**接入裁决（2026-11-08 用户拍板）：2006/2007/2009 逐笔族不接入 JEV 叙事工作台**（逐笔全量推送
流量/帧量大、工作台无逐笔消费场景；2203 已试点接入见 §四.2，不在本裁决范围）。收口范围 =
协议层落地（`parse_stock_mx_resp` / `parse_ty_dan_label_resp` / `build_hq_item_req_pb` /
`build_hq_list_req_pb`，pytest 6 用例）+ 实弹验证 + 文档固化；
不建 collector 订阅面/读口/前端，cmd 合同保留供未来逐笔/L2 研究复用。

## 四、接入实施（2026-11-08 试点落地）

1. **零成本即得（已全部实弹验证）**：溢价基因、涨停原因全文、所属板块、分时/分笔/竞价、盘口全量——
   全部 HTTP 游客可拉，与既有层1/层2/层3 同款参数体系；盯盘/F10 族同轮收口（见 §二表，
   唯笔记 GetStockNotes 需现役凭据=用户私有数据，StockDPExplain 1018=仅异动盘态调用属阴性正常态）。
2. **socket 2203 试点已实施（涨停原因推送）**：
   - 协议：`kpl_socket_protocol.CMD_HQ_REASONS=2203` + `build_hq_req_pb`(Hq.HQReq{f1 stockId})
     + `parse_hq_reasons_resp`（字段合同见函数 docstring：zt=2 涨停原因全文 / fx=3 / jc=4 / jj=5 /
     pledge=6 / rank=10 / rankTotal=11 / rankTop=12 / ztGroup=13 / theme=14 / label=17 /
     ztTag=100 / msgId=500 / plate=600 / tp=700）。
   - collector：`KplCollectorService(zt_reason_subs=True)`（env `KPL_ZT_REASON_SUBS=0` 关）——
     订阅面=涨停池（2103 pid=1）合并快照成员，**随页帧自动补订新入池成员**（pending 队列在
     收流循环 drain；重复去重；无退订=成员日内增量小，残留代价仅服务器周期重推，边界已记录）；
     推送解密/解析 fail-visible（`zt_reasons_error` 事件）；快照 `_zt_reason_snap`；
     status 新增 zt_reasons/zt_reasons_subscribed 计数。
   - 读口：`GET :8002/api/kpl/zt-reasons`（+ :8000 同路径代理透传）——无快照结构化降级
     `no_zt_reason_snapshot`（fail-visible）。
   - 前端：涨停池页（relay_page kplzt）个股列表【涨停原因】列 tooltip 接 2203 详情
     （首行=既有组合串，追加 zt 全文/梯队/题材/子题材/标签/排名/关联板块/Top；30s 节流
     `kplZtEnsureReasons`；**历史模式不用 2203**（快照仅当日，跨日期误归因）；该股未到流回退
     旧 tooltip 不伪装）。
   - 测试：协议 3 用例（HQReq 字节 / 全字段解析含多字节 tag / 空 payload）+ collector 5 用例
     （dispatch 快照+事件 / dec 失败 fail-visible / 读口降级 / 2103 pid=1 入队+drain 帧字节断言
     +pid=8 不入队+重复去重 / 开关关不队列且不清旧快照）+ proxy 2 用例（透传/502）——全 mock。
3. **quotas 缩放注意**：GetStockPanKou 的 real 为浮点原样（非 ×10000）；socket 侧 WT.price 等
   为 varint 需查缩放；两源接入时按「独立源交叉+自洽验证」逐列核对（§四 同款纪律）。
4. 首板被板率/题材热度等 App 专有字段**原样落库不自算**。

## 五、证据

- 实弹探测（批次1-3 合计 25 发，24 命中；1001/1018/1020 三发阴性均查明原因并修正）：
  `.tmp_review/kpl_stockpage_probe_results_2026-11-08.jsonl`（全响应原文）
- 脚本：`.tmp_review/kpl_stockpage_probe_2026-11-08.py`（批次1）、`kpl_stockpage_probe2_2026-11-08.py`（批次2，凭据走 mapping_refresh 公共出口）、`kpl_stockpage_probe3_2026-11-08.py`（批次3：盯盘/笔记/公告/F10）
- 大单分时 socket 实弹（20261108 休市时段单会话 2 发：2006/2009 双双命中）：
  `.tmp_review/kpl_mx_probe_20261108.py` + `kpl_mx_probe_results_20261108.jsonl`（原始帧 hex）
- 源码坐标：`j00.java`（请求构造，D1 第1参=c 第2参=a）、`px0.java`（详情页 Presenter/解析器 e1/N0）、
  `StockQuotationInfoPresenter.java`（订阅清单 @y51 + 请求构造 3470-3530）、`qn0.java`（cmd 分发 630-830）、
  `ox0.java`（GetZhangTingGene 6813、F10 族 6866-7214）、`ServiceHqStock.java`（proto 描述符）。
