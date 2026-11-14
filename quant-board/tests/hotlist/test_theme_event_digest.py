# -*- coding: utf-8 -*-
"""题材证据块（L3 消费层）测试——纯假 collection，零网络零模型。

锁定口径（v4，2026-10-23 换源后）：
1. **确定性映射**：本名精确 > 本名包含 > 别名包含；别名不得参与精确匹配；
2. **fail-visible**：语料未采集 / 板块未映射 / 无事件，三种"空"必须各自说清；
3. **事件层唯一权威源=开盘啦**：题材事件（标题/正文确定性关联+共享子串锚）、
   题材新闻（**Kword 题材标签优先**）、前瞻日历三节逐层展示；韭研 timeline 已退役；
4. L2 板内解析（韭研异动库）可用时不再判证据缺失（缺一层≠无证据）；
5. `include_l2=False` = relay 兼容形状（无板内解析/新闻流节）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.analysis.hotlist import theme_event_digest as D


class FakeCol:
    def __init__(self, docs=None):
        self.docs = [dict(d) for d in (docs or [])]

    def find(self, query=None, projection=None):
        out = []
        for d in self.docs:
            if _match(d, query):
                out.append(_project(d, projection))
        return out

    def find_one(self, query=None, projection=None, sort=None):
        rows = self.find(query, projection)
        return rows[0] if rows else None

    def count_documents(self, query=None):
        return len(self.find(query))


def _match(doc, query):
    for key, cond in (query or {}).items():
        val = doc.get(key)
        if isinstance(cond, dict):
            for op, arg in cond.items():
                if op == "$gte" and (val is None or not val >= arg):
                    return False
                if op == "$lte" and (val is None or not val <= arg):
                    return False
                if op not in ("$gte", "$lte"):
                    raise AssertionError(op)
        elif val != cond:
            return False
    return True


def _project(doc, projection):
    if not projection:
        return dict(doc)
    return {k: doc.get(k) for k, v in projection.items() if v}


class FakeDb:
    def __init__(self, industry=None, topic=None, news=None, calendar=None):
        self.cols = {
            "jiuyan_ai_industry": FakeCol(industry),
            "kpl_topic_events": FakeCol(topic),
            "kpl_theme_news": FakeCol(news),
            "kpl_theme_calendar": FakeCol(calendar),
        }

    def __getitem__(self, name):
        return self.cols.setdefault(name, FakeCol())


NODES = [
    {"code": "0079", "name": "国产机器人", "level": 1, "hot": 19.11,
     "content": "1、2026年8月19日，宇树机器人上市，发行市值约609亿元。",
     "contentChangedDate": "2026-10-20", "lastFetchDate": "2026-10-22"},
    {"code": "0120", "name": "物理AI", "level": 1, "hot": 14.89,
     "content": "2026年6月5日讯，英伟达官宣 NVIDIA Cosmos 3 物理AI模型。",
     "contentChangedDate": "2026-10-18", "lastFetchDate": "2026-10-22"},
    {"code": "0300", "name": "存储芯片", "level": 1, "hot": 5.0, "content": "",
     "contentChangedDate": None, "lastFetchDate": "2026-10-22"},
]

# 开盘啦题材事件（真实样本：2026-10-21/22 实抓）
TOPIC = [
    {"_id": "2026-10-21:2498", "kind": "kpl_topic_event", "eventId": "2498",
     "day": "2026-10-21",
     "title": "泽连斯基：愿在保留至少75%领土控制权的基础上达成和平协议",
     "content": "央视新闻10月21日消息，乌克兰总统泽连斯基…“现在我们必须冻结（战线）…”",
     "source": "央视新闻", "hotVal": 38836, "num": 58, "detailFetched": True,
     "lastFetchDate": "2026-10-22"},
    {"_id": "2026-10-21:2499", "kind": "kpl_topic_event", "eventId": "2499",
     "day": "2026-10-21", "title": "英伟达GTC大会来了！黃仁勋重磅演讲",
     "content": "黄仁勋将在21日发表主题演讲，聚焦物理AI与机器人。", "source": "开盘啦",
     "hotVal": 46417, "detailFetched": True, "lastFetchDate": "2026-10-22"},
]

# 开盘啦题材新闻流（Kword 题材标签 + 关联个股）
NEWS = [
    {"_id": "news:7939", "kind": "kpl_theme_news", "cid": "7939",
     "title": "泽连斯基表态推动和平协议预期，基建出口链异动", "kword": "俄乌重建",
     "source": "开盘啦", "eventDate": "2026-10-22", "timeStamp": 1792600000,
     "stocks": [{"code": "001360", "name": "南矿集团", "rate": 10.0, "setTop": 1}],
     "lastFetchDate": "2026-10-22"},
    {"_id": "news:7938", "kind": "kpl_theme_news", "cid": "7938",
     "title": "Meta未来支出承诺总额达8250亿美元涉及AI算力、数据中心及能源基础设施",
     "kword": "AI算力基建", "source": "开盘啦", "eventDate": "2026-10-22",
     "timeStamp": 1792681975,
     "stocks": [{"code": "603019", "name": "中科曙光", "rate": 0.29, "setTop": 1}],
     "lastFetchDate": "2026-10-22"},
]

# 开盘啦前瞻日历
CALENDAR = [
    {"_id": "cal:4803", "kind": "kpl_theme_calendar", "pid": "4803",
     "brief": "国产机器人产业大会将于10月25日至27日举行", "date": "2026-10-25",
     "tagName": "会议", "stocks": [], "lastFetchDate": "2026-10-22"},
]

# 韭研异动板内解析（L2，俄乌重建分组）
RUSSIA_ACTION = [{"_id": "2026-10-22:final", "fields": [
    {"name": "俄乌重建", "count": 5, "stocks": [
        {"code": "sz001360", "name": "南矿集团",
         "expound": "金属矿山设备+金矿\n1、2023年6月2日互动，俄罗斯市场主机和配件供应受限是公司的市场机会。"},
        {"code": "sz002097", "name": "山河智能",
         "expound": "工程机械+超深振冲钻机\n1、2026年半年报，旋挖钻机、液压静压压桩机等。"},
    ]},
]}]


def _db(**kw):
    kw.setdefault("industry", NODES)
    kw.setdefault("topic", TOPIC)
    kw.setdefault("news", NEWS)
    kw.setdefault("calendar", CALENDAR)
    return FakeDb(**kw)


# ── 名字归一与匹配优先级 ────────────────────────────────────────────────
def test_normalize_strips_noise_and_suffixes():
    assert D.normalize_name("机器人概念") == "机器人"
    assert D.normalize_name(" Ai 硬件 ") == "Ai硬件"
    assert D.normalize_name("ST摘帽") == "ST摘帽"
    assert D.normalize_name(None) == ""


def test_match_industry_precedence_and_alias_not_exact():
    nodes = NODES + [{"code": "x", "name": "机器人", "level": 1, "hot": 1.0, "content": "c"}]
    m = D.match_industry(nodes, "机器人")
    assert m["matched"] and m["method"] == "exact" and m["node"]["name"] == "机器人"

    m2 = D.match_industry(NODES, "机器人")            # 无同名 → 本名包含，取热度最高
    assert m2["method"] == "contains" and m2["node"]["name"] == "国产机器人"

    m3 = D.match_industry(NODES, "AI硬件")            # 无节点 → 未匹配（别名表中无此项）
    assert m3["matched"] is False


def test_shared_anchor_requires_cjk_and_length():
    assert D._shared_anchor("俄乌重建", "俄乌和平") == "俄乌"
    assert D._shared_anchor("AI应用", "AI算力扩产") is None, "纯拉丁锚「AI」不得关联"
    assert D._shared_anchor("机器人", "机器视觉") == "机器"
    assert D._shared_anchor("", "俄乌") is None


def test_not_a_theme_scope_after_2026_1026():
    """2026-10-26 用户裁决摘除四个「大X」域桶：名单只剩纯行政桶（预登记 §20）。"""
    assert D.NOT_A_THEME == ("公告", "新股", "其他", "ST板块", "ST")
    # P2-1（review）："ST" 入名单——"ST 板块"空格变体归一后恰为 "ST"
    assert "大消费" not in D.NOT_A_THEME and "医疗医药" not in D.NOT_A_THEME


# ── 证据块：产业树 + 开盘啦三节 ────────────────────────────────────────
def test_block_contains_industry_and_kpl_sections():
    out = D.build_theme_evidence_block(_db(), board_name="机器人", date="2026-10-22")
    text = out["text"]
    assert text.startswith(D.BLOCK_HEADER)
    assert "板块级催化原文（「国产机器人」" in text and "匹配方式" not in text
    # 开盘啦题材事件：仅标题+热度+日期（2026-10-28 用户裁决，正文不出）；
    # GTC 为正文级命中（标题未含机器人）→ 弱匹配降级标注
    assert "当日题材事件：" in text, "2026-10-30g：括号注删"
    assert "- 2026-10-21 英伟达GTC大会来了！黃仁勋重磅演讲" in text
    assert "黄仁勋将在21日发表主题演讲" not in text, "事件正文不再进叙事（仅标题+热度+日期）"
    assert "弱匹配" not in text, "弱匹配标注撤出叙事（AGENTS §1.2-8）"
    # 前瞻日历（开盘啦）
    assert "未来 3 日既定事件：" in text
    assert "国产机器人产业大会" in text
    assert out["state"]["ok"] is True
    assert out["evidenceMissing"] is False


def test_news_kword_tag_takes_priority():
    """Kword 题材标签是开盘啦现成的关联：俄乌重建板块直接命中 Kword=俄乌重建 的新闻。"""
    db = _db()
    db.cols["jiuyan_action"] = FakeCol(RUSSIA_ACTION)
    out = D.build_theme_evidence_block(db, board_name="俄乌重建", date="2026-10-22",
                                       leader_code="001360")
    text = out["text"]
    # 新闻流：Kword 标签命中 + 关联股披露
    assert "近两日题材新闻：" in text, "2026-10-30g：括号注删"
    assert "- 2026-10-22 [俄乌重建] 泽连斯基表态推动和平协议预期" in text
    assert "南矿集团" in text and "matchHow" not in text and "关联股" in text
    assert out["kwordTags"] == ["俄乌重建"]
    # 产业树无俄乌重建节点，但 L2 板内解析在 → 不判缺失
    assert "产业树未映射" in text
    assert "板内解析（「俄乌重建」" in text
    assert "俄罗斯市场" in text
    assert out["boardResolved"] is True
    assert out["evidenceMissing"] is False and out["evidenceMissingReason"] is None


def test_topic_event_shared_anchor_disclosure():
    """事件标题与板块无包含关系时，靠共享子串锚关联并显式披露（俄乌重建↔俄乌和平）。"""
    events = [{"_id": "2026-10-22:x", "day": "2026-10-22",
               "title": "俄乌和平：泽连斯基表示乌方愿达成和平协议",
               "content": "", "source": "央视新闻", "hotVal": 100,
               "detailFetched": True, "lastFetchDate": "2026-10-22"}]
    out = D.build_theme_evidence_block(_db(topic=events, news=[], calendar=[]),
                                       board_name="俄乌重建", date="2026-10-22")
    assert "- 2026-10-22 俄乌和平：泽连斯基表示乌方愿达成和平协议" in out["text"]
    assert "共享子串" not in out["text"], "匹配方式注撤出叙事"
    assert "来源 央视新闻，热度 100" in out["text"]
    assert out["events"][0]["matchHow"] == "共享子串「俄乌」"


def test_block_fail_visible_paths():
    # 1) 语料未采集（全空，且无 L2）
    empty = D.build_theme_evidence_block(FakeDb(), board_name="机器人", date="2026-10-22")
    assert "题材语料未采集。" in empty["text"], "判据注撤出叙事（AGENTS §1.2-8）"
    assert "无数据 ≠ 无催化" not in empty["text"]
    assert empty["evidenceMissing"] is True
    assert empty["evidenceMissingReason"] == "corpus_not_collected"

    # 2) 板块未映射且无事件/新闻/L2 → 才判缺失
    db = _db(news=[], calendar=[])
    out = D.build_theme_evidence_block(db, board_name="培育钻石", date="2026-10-22")
    assert "未映射" in out["text"] and "不代表无催化" not in out["text"]
    assert out["industry"] is None
    assert out["evidenceMissingReason"] == "industry_tree_unmapped"

    # 3) 已映射但正文空且无事件
    db3 = _db(industry=[{"code": "0300", "name": "存储芯片", "level": 1, "hot": 1.2,
                         "content": "", "lastFetchDate": "2026-10-22"}],
              news=[], calendar=[])
    out3 = D.build_theme_evidence_block(db3, board_name="存储", date="2026-10-22")
    assert "无催化正文" in out3["text"]
    assert out3["evidenceMissingReason"] == "no_content_no_event"

    # 4) 无匹配事件 ≠ 无催化（产业树正文在 → 有可用证据）
    out4 = D.build_theme_evidence_block(_db(topic=[], news=[], calendar=[]),
                                        board_name="机器人", date="2026-10-22")
    assert "当日题材事件：无匹配" in out4["text"]
    # 2026-10-24a：新闻与日历双空合并为一行（原两行各带一遍「无数据 ≠ 无催化」套话）
    assert "题材新闻/前瞻日历：均无匹配" in out4["text"]  # 2026-10-30d 精简：重复解释括号删
    assert "近两日题材新闻：无匹配" not in out4["text"]
    assert "未来 3 日既定事件：无匹配" not in out4["text"]
    assert out4["evidenceMissing"] is False, "产业树正文在 → 有可用证据，不判缺失"


def test_block_marks_stale_corpus():
    stale_top = [{**e, "lastFetchDate": "2026-10-17"} for e in TOPIC]
    db = _db(industry=[{**NODES[0], "lastFetchDate": "2026-10-17"}],
             topic=stale_top, news=[], calendar=[])
    out = D.build_theme_evidence_block(db, board_name="机器人", date="2026-10-22")
    assert out["state"]["stale"] is True and "非当日" not in out["text"], "采集日注撤出叙事"


def test_block_respects_char_budget():
    long_content = "催化" * 400
    db = _db(industry=[{"code": "0079", "name": "机器人", "level": 1, "hot": 1.0,
                        "content": long_content, "lastFetchDate": "2026-10-22"}],
             topic=[{"_id": "2026-10-22:1", "day": "2026-10-22", "title": "机器人大会",
                     "content": "长文" * 500, "hotVal": 1, "detailFetched": True,
                     "lastFetchDate": "2026-10-22"}],
             news=[], calendar=[])
    out = D.build_theme_evidence_block(db, board_name="机器人", date="2026-10-22",
                                       content_chars=100, max_events=1)
    assert "…" in out["text"] and "截断" not in out["text"]
    assert len(out["text"]) < 1500


def test_relay_compat_shape_has_no_l2_or_news_sections():
    """include_l2=False（relay 兼容形状）：无板内解析/新闻流节；事件层来源标签已换开盘啦。"""
    db = _db()
    db.cols["jiuyan_action"] = FakeCol(RUSSIA_ACTION)
    out = D.build_theme_evidence_block(db, board_name="机器人", date="2026-10-22",
                                       include_l2=False)
    text = out["text"]
    assert "板内解析" not in text
    assert "近两日题材新闻" not in text
    assert "当日题材事件" in text and "既定事件" in text, "relay 保留当日+未来事件层（来源=开盘啦）"
    assert "既定事件" in text


# ── v5：题材热度序列（炒作深度/延续性判据的核心原料） ─────────────────────
def test_heat_series_daily_aggregation_and_trend_line():
    db = _db()
    out = D.build_theme_evidence_block(db, board_name="俄乌重建", date="2026-10-22",
                                       leader_code="001360")
    text = out["text"]
    assert f"题材热度序列（近 {D.HEAT_WINDOW_DAYS} 日）：" in text
    assert "断流/见顶" not in text
    # 10-22 有 Kword=俄乌重建 的新闻 1 条
    assert "10-22 新闻1·事件0" in text
    # 无痕迹的日如实写 0（不断流伪装成有数据）
    assert "10-20 新闻0·事件0" in text
    assert out["heatSeries"]["any"] is True


def test_heat_series_empty_is_explicit_not_silent():
    db = _db(news=[], topic=[])
    out = D.build_theme_evidence_block(db, board_name="机器人", date="2026-10-22")
    assert (f"题材热度序列：近 {D.HEAT_WINDOW_DAYS} 日无该题材的新闻/事件痕迹"
            ) in out["text"] and "不代表无催化" not in out["text"]
    assert out["heatSeries"]["any"] is False


def test_heat_window_widened_to_ten_days():
    """S2（2026-10-24b）：窗 5→10 日——「断流/见顶」判据需要更长窗看趋势拐点。"""
    assert D.HEAT_WINDOW_DAYS == 10
    db = _db()
    out = D.build_theme_evidence_block(db, board_name="俄乌重建", date="2026-10-22",
                                       leader_code="001360")
    # 序列覆盖 10 个日槽（无痕迹日如实写 0）
    seg = out["text"].split("题材热度序列（近 10 日）：", 1)[1].split("\n", 1)[0]
    days = [d.split()[0] for d in seg.split("；")]
    assert len(days) == 10 and days[0] == "10-13" and days[-1] == "10-22"


def test_heat_series_absent_in_relay_compat_shape():
    out = D.build_theme_evidence_block(_db(), board_name="俄乌重建", date="2026-10-22",
                                       include_l2=False)
    assert "题材热度序列" not in out["text"], "relay 兼容形状不出热度序列/新闻流/L2 节"


# ── 2026-10-24a：泛词锚黑名单 / 电头剥离 / 双空合并 ─────────────────────
def test_shared_anchor_generic_words_are_not_anchors():
    """泛词黑名单：横切多题材的 2 字词（应用/科技/智能…）不得充当关联锚。

    10-23 实例：中办国办《意见》正文含「典型应用场景」，经「应用」被挂给 AI应用——
    该事件与 AI应用 的唯一关联就是这 2 字泛词。专有 2 字锚（俄乌）不受影响。
    """
    assert D._shared_anchor("AI应用", "意见提出探索典型应用场景") is None, "「应用」泛词不当锚"
    assert D._shared_anchor("机器人", "机器视觉") == "机器", "非泛词锚维持原行为"
    assert D._shared_anchor("俄乌重建", "俄乌和平") == "俄乌", "G2 修复依赖的专有 2 字锚保留"
    # 泛词只跳过、不整体否决（2026-10-24 review 处置）：专有锚与泛词同现时保留专有锚，
    # 不因泛词在板名里扫描序靠前就连坐（修复前此处返回 None）
    assert D._shared_anchor("智能驾驶", "智能网联驾驶辅助政策出台") == "驾驶", \
        "泛词「智能」不得否决专有锚「驾驶」"
    for w in D.GENERIC_ANCHORS:
        assert len(w) == 2, "黑名单只封 2 字泛词（更长锚自带区分度）"


def test_generic_anchor_blocks_false_event_association():
    """端到端：事件与板块只共享泛词时不得挂靠（关联方式披露里不得出现该泛词锚）。"""
    events = [{"_id": "2026-10-21:x", "day": "2026-10-21",
               "title": "中办国办发布《关于推动科技创新和产业创新深度融合的意见》",
               "content": "全面实施人工智能+行动，探索典型应用场景与商业模式。",
               "source": "新华社", "hotVal": 74714, "detailFetched": True,
               "lastFetchDate": "2026-10-22"}]
    out = D.build_theme_evidence_block(_db(topic=events, news=[], calendar=[]),
                                       board_name="AI应用", date="2026-10-22")
    assert out["events"] == [], "「应用」泛词锚不得把跨题材事件挂给 AI应用"
    # 对照：含专有别名（智能体）的正文仍经「包含」命中——GTC 类事件不受黑名单影响
    events2 = [{**events[0], "title": "英伟达GTC大会：从模块化AI工厂到企业级智能体",
                "content": "英伟达正将竞争优势延伸到智能体与行业应用生态。"}]
    out2 = D.build_theme_evidence_block(_db(topic=events2, news=[], calendar=[]),
                                        board_name="AI应用", date="2026-10-22")
    assert len(out2["events"]) == 1 and "包含" in out2["events"][0]["matchHow"]


def test_news_calendar_merge_only_when_both_empty():
    """双空合并（2026-10-24a）：单边有命中必须维持分列（语义分层不损失）。"""
    # 新闻有命中（俄乌重建 Kword）、日历空 → 新闻节出命中行，日历节出独立无匹配行
    db = _db(calendar=[])
    db.cols["jiuyan_action"] = FakeCol(RUSSIA_ACTION)
    out = D.build_theme_evidence_block(db, board_name="俄乌重建", date="2026-10-22",
                                       leader_code="001360")
    assert "近两日题材新闻：" in out["text"]
    assert "未来 3 日既定事件：无匹配" in out["text"]
    assert "题材新闻/前瞻日历：均无匹配" not in out["text"]
    # relay 兼容形状（无新闻节）：日历空仍出独立无匹配行，不得被合并逻辑吞掉
    out2 = D.build_theme_evidence_block(_db(news=[], calendar=[]), board_name="机器人",
                                        date="2026-10-22", include_l2=False)
    assert "未来 3 日既定事件：无匹配" in out2["text"]
    assert "题材新闻/前瞻日历" not in out2["text"]


# ── S3（2026-10-24b）：驱动标签第二匹配通道 ──────────────────────────────
def test_driver_tag_channel_supplements_mismatched_first_match():
    """睿能科技实例（10-22/23 两日真实 fire）：板块名「半导体」命中宽父节点，
    龙头驱动标签「存储芯片」补对口子节点——只并列披露，不替换首通道。

    注：华林证券（金融）案例经真实库核验**不 fire**（产业树金融类为层级命名
    「金融-券商」，与标签词「证券」无字面子串关系——确定性匹配的边界，不编语义
    别名；其对口内容由板内解析 expound 承载）。10-22/23 真实扫描 fire 9/14。
    """
    industry = [
        {"code": "S1", "name": "半导体", "level": 1, "hot": 12.0,
         "content": "1、2026年8月，全球半导体销售额同比+10%（宽父节点月度旧闻）。",
         "contentChangedDate": "2026-10-15", "lastFetchDate": "2026-10-22"},
        {"code": "S2", "name": "存储芯片", "level": 2, "hot": 18.0,
         "content": "1、2026年10月21日，存储现货价续涨，合约价四季度看涨。",
         "contentChangedDate": "2026-10-21", "lastFetchDate": "2026-10-22"},
    ]
    action = [{"_id": "2026-10-22:final", "fields": [
        {"name": "半导体", "count": 4, "stocks": [
            {"code": "sh603733", "name": "睿能科技",
             "expound": "存储芯片+机器人+拟收购博泰智能\n1、公司存储芯片业务占比领先。"},
        ]},
    ]}]
    db = _db(industry=industry, topic=[], news=[], calendar=[])
    db.cols["jiuyan_action"] = FakeCol(action)
    out = D.build_theme_evidence_block(db, board_name="半导体", date="2026-10-22",
                                       leader_code="603733")
    text = out["text"]
    assert "板块级催化原文（「半导体」" in text, "首通道保留不替换（2026-10-30d：exact 常态不标注）"
    assert "产业树补充映射" in text
    assert "「存储芯片」关联「存储芯片」" in text
    assert "现货价续涨" in text, "补的是对口催化正文"


def test_driver_tag_channel_skips_same_node_and_respects_include_l2():
    """命中首通道同名节点不重复披露；include_l2=False（relay 兼容）整节压制。"""
    industry = NODES + [
        {"code": "B1", "name": "商业航天", "level": 1, "hot": 9.9,
         "content": "1、2026年10月20日，可回收火箭试飞成功。",
         "contentChangedDate": "2026-10-20", "lastFetchDate": "2026-10-22"},
    ]
    action = [{"_id": "2026-10-22:final", "fields": [
        {"name": "机器人", "count": 2, "stocks": [
            {"code": "sh603278", "name": "大业股份",
             "expound": "人形机器人+商业航天\n1、腱绳产品尚处探索阶段。"},
        ]},
    ]}]
    db = _db(industry=industry, topic=[], news=[], calendar=[])
    db.cols["jiuyan_action"] = FakeCol(action)
    out = D.build_theme_evidence_block(db, board_name="机器人", date="2026-10-22",
                                       leader_code="603278")
    text = out["text"]
    # 切词 [人形机器人, 商业航天]：「人形机器人」经别名命中「国产机器人」=首通道节点 → 跳过；
    # 「商业航天」exact 命中不同节点 → 补充
    assert "产业树补充映射" in text and "关联「商业航天」" in text
    assert text.count("板块级催化原文") == 1 and "「国产机器人」" in text
    # relay 兼容形状：无 L2 → 无板内解析、无补充映射
    out2 = D.build_theme_evidence_block(db, board_name="机器人", date="2026-10-22",
                                        leader_code="603278", include_l2=False)
    assert "产业树补充映射" not in out2["text"]


def test_tag_terms_split_is_deterministic():
    """切词确定性：按分隔符切、剥泛词黑名单与 <2 字碎片，不做语义分词。"""
    assert D._tag_terms("人形机器人（金属腱绳）+商业航天+光伏+轮胎") == \
        ["人形机器人", "金属腱绳", "商业航天"]
    assert D._tag_terms("应用+科技") == [], "泛词黑名单内的词不作候选"
    assert D._tag_terms("") == [] and D._tag_terms(None) == []


def test_generic_anchor_econ_p1_1():
    """P1-1（review）：「经济」入泛词黑名单——冰雪经济/低空经济/银发经济并存不互锚。"""
    assert D._shared_anchor("冰雪经济", "低空经济") is None
    assert D._shared_anchor("银发经济", "低空经济") is None


def test_board_keywords_suffix_bridge_econ_industry():
    """2026-10-30e 后缀桥：韭研「冰雪经济」↔ KPL「冰雪产业」命名差异确定性互认。

    实证：10-29 龙江交通（冰雪经济龙一）10:38 播报「冰雪产业异动拉升，冰山冷热直线
    涨停」漏配。桥规则：X经济/X产业 双向补词干+对侧变体；泛词词干不桥；非 X经济/产业
    板块不受影响。
    """
    assert D.board_keywords("冰雪经济") == ["冰雪经济", "冰雪", "冰雪产业"]
    assert D.board_keywords("冰雪产业") == ["冰雪产业", "冰雪", "冰雪经济"]
    assert D.board_keywords("低空经济") == ["低空经济", "低空", "eVTOL", "低空产业"], \
        "既有别名优先，桥补充对侧变体"
    assert D.board_keywords("消费经济") == ["消费经济"], "词干=泛词（消费）不桥，防伪造关联"
    assert D.board_keywords("机器人") == ["机器人"], "非后缀板块零变化"
    assert D.board_keywords("半导体") == ["半导体", "芯片"], "2026-10-30e 清点实证别名"


def test_alias_ai_video_board_normalized_key():
    """韭研「AI影视/传媒」→ KPL「AI视频」（用户裁决 2026-11-02）。

    锁两点：①ALIASES key 必须用**归一形式**「AI影视传媒」（normalize_name 去斜杠，
    带斜杠 key 永远查不到——2026-11-02 实测首次落表未生效的根因）；
    ②别名展开后 Kword 标签/标题锚/日历 brief 三条匹配路径全通。
    """
    assert D.board_keywords("AI影视/传媒") == ["AI影视传媒", "AI视频"]
    news = {"kword": "AI视频", "title": "PineDrama下载破亿，字节想在海外再造一个红果",
            "eventDate": "2026-10-11"}
    hits = D.match_kpl_news([news], "AI影视/传媒")
    assert [h["matchHow"] for h in hits] == ["Kword标签"]
    ev = {"title": "AI视频概念异动：红果短剧流量新高", "content": "",
          "day": "2026-11-02", "hotVal": 88}
    ev_hits = D.match_kpl_events([ev], "AI影视/传媒")
    assert ev_hits and ev_hits[0]["titleHit"] is True, "标题级命中=强关联"
    cal = {"tagName": "会议", "brief": "AI视频产业大会将于11月5日举行", "date": "2026-11-05"}
    assert D.match_kpl_calendar([cal], "AI影视/传媒"), "日历 brief 包含锚命中"
    # 短剧/影视短剧/AI短剧 同归 AI视频
    assert "AI视频" in D.board_keywords("短剧")
    assert "AI视频" in D.board_keywords("AI短剧")


def test_match_kpl_news_zsname_official_board_channel():
    """ZSName 官方板块通道（2026-11-02 用户裁决①）：KPL 新题自带板块归属，
    匹配次序 Kword 标签 → ZSName 板块（双向包含，≥2 字）→ 标题锚；
    ZSName 空（约七成条目）不参与，标题锚兜底不回退。"""
    # ① ZSName 精确互认：kword 空、标题不含关键词，靠官方板块命中
    it = {"cid": "1", "title": "2026年世界互联网大会乌镇峰会开幕",
          "kword": "", "zsName": "文化传媒", "eventDate": "2026-11-02", "stocks": []}
    hits = D.match_kpl_news([it], "出版传媒")  # 别名含「文化传媒」
    assert [h["matchHow"] for h in hits] == ["ZSName板块「文化传媒」"], \
        "Kword 空时 ZSName 板块名经别名展开互认命中"
    # ② 双向包含：官方板块名比本名宽（k ⊂ zs，review 2026-11-02 Nit：原 or True 恒真零断言）
    it2 = {"cid": "2", "title": "某公司公告", "kword": "", "zsName": "光伏玻璃",
           "eventDate": "2026-11-02", "stocks": []}
    hits2 = D.match_kpl_news([it2], "光伏")
    assert [h["matchHow"] for h in hits2] == ["ZSName板块「光伏玻璃」"], "key「光伏」⊂ zs 命中"
    it3 = {"cid": "3", "title": "标题完全无关的通稿", "kword": "",
           "zsName": "半导体", "eventDate": "2026-11-02", "stocks": []}
    hits3 = D.match_kpl_news([it3], "半导体")  # 别名「芯片」在场：zs=半导体==base 命中
    assert [h["matchHow"] for h in hits3] == ["ZSName板块「半导体」"]
    # ③ ZSName 空不参与、标题锚兜底路径不回退
    it4 = {"cid": "4", "title": "光伏电池及制造装备创新生态发展研讨会即将在长沙召开",
           "kword": "", "zsName": "", "eventDate": "2026-11-02", "stocks": []}
    hits4 = D.match_kpl_news([it4], "光伏")
    assert [h["matchHow"] for h in hits4] == ["包含"], "无 ZSName 时标题锚仍命中"


def test_match_kpl_news_content_anchor_weak_hit():
    """正文锚兜底（2026-11-02 正文预登记 §五.1）：标题/Kword/ZSName 全空时，
    正文剥 HTML 后确定性命中，标 titleHit=False 弱匹配；叙事行带弱匹配标注。"""
    import re as _re
    from backend.analysis.hotlist import theme_event_digest as _D
    body_html = "<p>财联社11月2日讯 商业航天再提速：2029 年轨道算力将超过地面。</p>"
    it = {"cid": "9", "title": "马斯克重磅预测", "kword": "", "zsName": "",
          "contentHtml": body_html, "eventDate": "2026-11-02", "stocks": []}
    hits = _D.match_kpl_news([it], "商业航天")
    assert len(hits) == 1
    h = hits[0]
    assert h["matchHow"].startswith("正文锚"), f"got {h['matchHow']}"
    assert h["titleHit"] is False, "正文锚命中必须标弱匹配"
    # 标题命中路径不受影响：不带 titleHit 字段（默认弱匹配不触发）
    it2 = {"cid": "10", "title": "商业航天发射新进展", "kword": "", "zsName": "",
           "contentHtml": body_html, "eventDate": "2026-11-02", "stocks": []}
    h2 = _D.match_kpl_news([it2], "商业航天")[0]
    assert "titleHit" not in h2 and h2["matchHow"] == "包含"
    # 正文不命中则整条不进（不加噪声）
    it3 = {"cid": "11", "title": "完全无关通稿", "kword": "", "zsName": "",
           "contentHtml": "<p>今天天气不错</p>", "eventDate": "2026-11-02", "stocks": []}
    assert _D.match_kpl_news([it3], "商业航天") == []
    # 剥 HTML：标签不算词符（<p> 与词之间不形成假锚），替换为空格后首尾含空白
    assert _re.sub(r"\s+", " ", _D._strip_html(body_html)).strip().startswith("财联社")


def test_news_line_renders_weak_match_badge_for_content_anchor():
    """叙事行：正文锚命中条目带「弱匹配（标题未命中，仅正文级关联）」；标题命中不带。"""
    news = [
        {"_id": "news:1", "kind": "kpl_theme_news", "cid": "1",
         "title": "马斯克重磅预测", "kword": "", "zsName": "",
         "contentHtml": "<p>商业航天又一里程碑，卫星互联网提速。</p>",
         "source": "开盘啦", "eventDate": "2026-10-22", "timeStamp": None,
         "stocks": [], "lastFetchDate": "2026-10-22"},
        {"_id": "news:2", "kind": "kpl_theme_news", "cid": "2",
         "title": "商业航天发射计划公布", "kword": "", "zsName": "",
         "source": "开盘啦", "eventDate": "2026-10-22", "timeStamp": None,
         "stocks": [], "lastFetchDate": "2026-10-22"},
    ]
    out = D.build_theme_evidence_block(_db(news=news, calendar=[]),
                                       board_name="商业航天", date="2026-10-22")
    # 语料卫生红线：弱匹配/匹配方式标注撤出叙事，正文锚条目与标题命中条目同样平铺
    news_lines = [ln for ln in out["text"].splitlines() if ln.startswith("- ")]
    assert len(news_lines) == 2, news_lines
    assert any("马斯克重磅预测" in ln for ln in news_lines)
    assert any("商业航天发射计划公布" in ln for ln in news_lines)
    assert "弱匹配" not in out["text"] and "正文锚" not in out["text"]
    weak = [h for h in D.match_kpl_news(news, "商业航天") if h.get("titleHit") is False]
    assert len(weak) == 1, "正文锚命中仍由结构化 titleHit 承载"


def test_match_kpl_news_content_only_shared_substring_hits():
    """review 2026-11-02 Minor：仅存在于正文的共享子串关联也要命中
    （正文锚两步：标题短锚未中 → 正文全文共享子串），仍标弱匹配。"""
    it = {"cid": "20", "title": "盘前必读丨产业风向标", "kword": "", "zsName": "",
          "contentHtml": "<p>协会数据显示，上周商业航天领域发射任务环比增加。</p>",
          "eventDate": "2026-11-02", "stocks": []}
    hits = D.match_kpl_news([it], "商业航天")
    assert len(hits) == 1 and hits[0]["matchHow"].startswith("正文锚")
    assert hits[0]["titleHit"] is False


def test_alias_yiliao_yiyao_anchor_ai_medical():
    """2026-11-13 用户裁决（终锚）：竞价链 T−1 分组名「医疗医药」锚「AI医疗」。

    实证链：产业树无裸「医药」节点可子串命中；同日四轮裁决 创新药→医疗（落
    医疗器械弱相关）→脑机接口（hot-1.79）→终锚 AI医疗（level1 hot-2.12，
    正文在；子树 AI制药/华为/阿里同池）。字面「医药医疗」树内零命中不采用。
    """
    assert D.ALIASES["医疗医药"] == ("AI医疗",)
    assert D.board_keywords("医疗医药") == ["医疗医药", "AI医疗"]
    nodes = [{"name": "AI医疗", "level": 1, "hot": -2.12, "content": "x"},
             {"name": "AI医疗-AI制药", "level": 2, "hot": 0.0, "content": "y"},
             {"name": "医疗器械", "level": 1, "hot": 0.7, "content": "z"}]
    m = D.match_industry(nodes, "医疗医药")
    assert m["matched"] is True and m["method"] == "alias"
    assert (m["node"] or {}).get("name") == "AI医疗", "alias 精确命中 level1 裸节点，医疗器械不入池"


# 2026-11-14b 竞价链原料修复：L2 回退 + 龙头解析全文（天普 605255 复盘）
LONG_EXP_CORE = "2023年6月2日互动，俄罗斯市场主机和配件供应受限是公司的市场机会，公司已布局俄语区售后服务网络。"
LONG_ACTION = [{"_id": "2026-10-22:final", "fields": [
    {"name": "俄乌重建", "count": 1, "stocks": [
        {"code": "sz001360", "name": "南矿集团",
         "expound": "金属矿山设备+金矿\n1、" + LONG_EXP_CORE * 8 + "ENDTOKEN控制权变更句。"}]}]}]


def test_l2_fallback_date_when_today_final_missing():
    """当日 final 未生成（晨间 09:26 槽常态）→ 回退 l2_fallback_date（T−1）final；
    回退命中时行内显式标注榜单日期（数据事实），l2Date/l2FallbackUsed 返回供留痕。"""
    db = _db()
    db.cols["jiuyan_action"] = FakeCol(RUSSIA_ACTION)   # 仅 2026-10-22:final
    res = D.build_theme_evidence_block(db, board_name="俄乌重建", date="2026-10-23",
                                       leader_code="001360",
                                       l2_fallback_date="2026-10-22")
    assert "板内解析（「俄乌重建」2 只，2026-10-22 榜单）" in res["text"]
    assert res["l2FallbackUsed"] is True and res["l2Date"] == "2026-10-22"


def test_l2_no_fallback_keeps_absence_line():
    """不传回退日 = 旧行为（题材链零变化）：当日无分组行照出，l2FallbackUsed=False。"""
    db = _db()
    db.cols["jiuyan_action"] = FakeCol(RUSSIA_ACTION)
    res = D.build_theme_evidence_block(db, board_name="俄乌重建", date="2026-10-23",
                                       leader_code="001360")
    assert "板内解析：当日无「俄乌重建」板块分组" in res["text"]
    assert res["l2FallbackUsed"] is False


def test_leader_expound_not_clipped_when_budget_given():
    """260 字截断会丢公司级硬事实（天普案：控制权变更句被截）——
    leader_expound_chars 放行龙头自身摘录；同伴/板块级仍 content_chars。"""
    db = _db()
    db.cols["jiuyan_action"] = FakeCol(LONG_ACTION)
    base = D.build_theme_evidence_block(db, board_name="俄乌重建", date="2026-10-22",
                                        leader_code="001360")
    full = D.build_theme_evidence_block(db, board_name="俄乌重建", date="2026-10-22",
                                        leader_code="001360", leader_expound_chars=1200)
    assert "ENDTOKEN" not in base["text"]      # 预设 260 截断丢尾部
    assert "ENDTOKEN" in full["text"]          # 全文进窗
    assert full["text"].count("解析摘录：") == 1
