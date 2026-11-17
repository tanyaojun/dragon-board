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
                if op == "$lt" and (val is None or not val < arg):
                    return False
                if op not in ("$gte", "$lte", "$lt"):
                    raise AssertionError(op)
        elif val != cond:
            return False
    return True


def _project(doc, projection):
    if not projection:
        return dict(doc)
    return {k: doc.get(k) for k, v in projection.items() if v}


class FakeDb:
    def __init__(self, industry=None, topic=None, news=None, calendar=None,
                 industry_stocks=None):
        self.cols = {
            "jiuyan_ai_industry": FakeCol(industry),
            "kpl_topic_events": FakeCol(topic),
            "kpl_theme_news": FakeCol(news),
            "kpl_theme_calendar": FakeCol(calendar),
            "jiuyan_industry_stocks": FakeCol(industry_stocks),
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
    # 无痕迹的连续零日区间化（2026-11-17 语料精简：断流事实无损，逐字重复删除）
    assert "10-13~10-21 新闻0·事件0（连续9日）" in text
    assert "10-20 新闻0·事件0" not in text
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
    # 序列覆盖 10 个日槽（2026-11-17：连续零日区间化，9 零日+1 有痕日=10 槽）
    seg = out["text"].split("题材热度序列（近 10 日）：", 1)[1].split("\n", 1)[0]
    parts = seg.split("；")
    assert parts[0] == "10-13~10-21 新闻0·事件0（连续9日）"
    assert parts[-1].startswith("10-22 ") and len(parts) == 2


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
        {"code": "S1", "name": "半导体产业链", "level": 1, "hot": 12.0,
         "content": "1、2026年8月，全球半导体销售额同比+10%（宽父节点月度旧闻）。",
         "contentChangedDate": "2026-10-15", "lastFetchDate": "2026-10-22",
         "path": ["半导体产业链"]},
        {"code": "S2", "name": "半导体产业链-存储芯片", "level": 2, "hot": 18.0,
         "content": "1、2026年10月21日，存储现货价续涨，合约价四季度看涨。",
         "contentChangedDate": "2026-10-21", "lastFetchDate": "2026-10-22",
         "path": ["半导体产业链", "半导体产业链-存储芯片"]},
    ]
    industry_stocks = [{"_id": "S1", "kind": "jiuyan_industry_stocks",
                        "name": "半导体产业链", "level": 1,
                        "stocks": [{"code": "603733", "name": "睿能科技"}]}]
    action = [{"_id": "2026-10-22:final", "fields": [
        {"name": "半导体", "count": 4, "stocks": [
            {"code": "sh603733", "name": "睿能科技",
             "expound": "存储芯片+机器人+拟收购博泰智能\n1、公司存储芯片业务占比领先。"},
        ]},
    ]}]
    db = _db(industry=industry, topic=[], news=[], calendar=[],
             industry_stocks=industry_stocks)
    db.cols["jiuyan_action"] = FakeCol(action)
    out = D.build_theme_evidence_block(db, board_name="半导体", date="2026-10-22",
                                       leader_code="603733")
    text = out["text"]
    assert "板块级催化原文（「半导体产业链」" in text, "首通道保留不替换（2026-10-30d：exact 常态不标注）"
    assert "产业树补充映射" in text
    assert "「存储芯片」关联「半导体产业链-存储芯片」" in text
    assert "现货价续涨" in text, "补的是对口催化正文"
    assert out["s3State"] == "injected" and out["s3Term"] == "存储芯片"


def test_driver_tag_channel_skips_same_node_and_respects_include_l2():
    """命中首通道同名节点不重复披露；include_l2=False（relay 兼容）整节压制。"""
    industry = NODES + [
        {"code": "B1", "name": "商业航天", "level": 1, "hot": 9.9,
         "content": "1、2026年10月20日，可回收火箭试飞成功。",
         "contentChangedDate": "2026-10-20", "lastFetchDate": "2026-10-22",
         "path": ["商业航天"]},
    ]
    industry_stocks = [{"_id": "B1", "kind": "jiuyan_industry_stocks",
                        "name": "商业航天", "level": 1,
                        "stocks": [{"code": "603278", "name": "大业股份"}]}]
    action = [{"_id": "2026-10-22:final", "fields": [
        {"name": "机器人", "count": 2, "stocks": [
            {"code": "sh603278", "name": "大业股份",
             "expound": "人形机器人+商业航天\n1、腱绳产品尚处探索阶段。"},
        ]},
    ]}]
    db = _db(industry=industry, topic=[], news=[], calendar=[],
             industry_stocks=industry_stocks)
    db.cols["jiuyan_action"] = FakeCol(action)
    out = D.build_theme_evidence_block(db, board_name="机器人", date="2026-10-22",
                                       leader_code="603278")
    text = out["text"]
    # 切词 [人形机器人, 商业航天]：「人形机器人」经别名命中「国产机器人」=首通道节点 → 跳过；
    # 「商业航天」exact 命中不同节点 → 成分验证龙头 ∈ 快照 → 补充
    assert "产业树补充映射" in text and "关联「商业航天」" in text
    assert text.count("板块级催化原文") == 1 and "「国产机器人」" in text
    # relay 兼容形状：无 L2 → 无板内解析、无补充映射
    out2 = D.build_theme_evidence_block(db, board_name="机器人", date="2026-10-22",
                                        leader_code="603278", include_l2=False)
    assert "产业树补充映射" not in out2["text"]


def test_driver_tag_gate_blocks_non_member_tag():
    """S3 成分验证门（2026-11-14 用户报障：大东方 600327 零售标签蹭「商业航天」
    被注入卫星叙事）：标签词词面命中节点但龙头不在成分快照 → 不注入异题材叙事，
    跳过原因留 s3State 不进叙事。"""
    industry = [
        {"code": "B1", "name": "商业航天", "level": 1, "hot": 9.9,
         "content": "1、2026年9月23日晚，我国成功发射卫星互联网低轨 26 组卫星。",
         "contentChangedDate": "2026-10-20", "lastFetchDate": "2026-10-22",
         "path": ["商业航天"]},
    ]
    industry_stocks = [{"_id": "B1", "kind": "jiuyan_industry_stocks",
                        "name": "商业航天", "level": 1,
                        "stocks": [{"code": "001270", "name": "铖昌科技"}]}]
    action = [{"_id": "2026-10-22:final", "fields": [
        {"name": "大消费", "count": 2, "stocks": [
            {"code": "sh600327", "name": "大东方",
             "expound": "零售+商业航天+民营医院\n1、公司商业零售门店情况。"},
        ]},
    ]}]
    db = _db(industry=industry, topic=[], news=[], calendar=[],
             industry_stocks=industry_stocks)
    db.cols["jiuyan_action"] = FakeCol(action)
    out = D.build_theme_evidence_block(db, board_name="大消费", date="2026-10-22",
                                       leader_code="600327")
    assert "产业树补充映射" not in out["text"], "蹭标签词不得注入"
    assert out["s3State"] == "skipped_not_member"
    assert out["s3Term"] == "商业航天" and out["s3Node"] == "商业航天"


def test_driver_tag_gate_unverifiable_injects_with_disclosure():
    """2026-11-18 B9 Fix-3（用户裁决「采纳全部建议」）：快照缺席=无法核验 ≠
    not_member——披露式注入（§4.0 暴露不阻断），叙事行带「成分未核验」数据事实
    标注（与「未证实」来源可靠性标注同类），s3State=injected_unverifiable 留痕；
    验明不在（not_member 蹭标签）仍阻断（上测，2026-11-14 裁决不动）。"""
    industry = [
        {"code": "B1", "name": "商业航天", "level": 1, "hot": 9.9,
         "content": "1、2026年9月23日晚，我国成功发射卫星互联网低轨 26 组卫星。",
         "contentChangedDate": "2026-10-20", "lastFetchDate": "2026-10-22",
         "path": ["商业航天"]},
    ]
    action = [{"_id": "2026-10-22:final", "fields": [
        {"name": "大消费", "count": 2, "stocks": [
            {"code": "sh600327", "name": "大东方",
             "expound": "零售+商业航天+民营医院\n1、公司商业零售门店情况。"},
        ]},
    ]}]
    db = _db(industry=industry, topic=[], news=[], calendar=[],
             industry_stocks=[])
    db.cols["jiuyan_action"] = FakeCol(action)
    out = D.build_theme_evidence_block(db, board_name="大消费", date="2026-10-22",
                                       leader_code="600327")
    assert "产业树补充映射" in out["text"]
    assert "成分未核验" in out["text"], "披露标注是数据事实，模型自行降权"
    assert "卫星互联网" in out["text"], "真正文注入（贫料→有料）"
    assert out["s3State"] == "injected_unverifiable"
    assert out["s3Term"] == "商业航天" and out["s3Node"] == "商业航天"


def test_driver_tag_candidate_iteration_tries_next_on_not_member():
    """2026-11-18 B9 Fix-2（用户裁决）：同词候选独立过门不连坐——pool[0]
    not_member 后继续试同词下一候选（可经不同一级祖先验明）；旧版只试 pool[0]
    即换词，可验明候选结构性饿死（广百案根因之一）。"""
    industry = [
        {"code": "B1", "name": "商业航天", "level": 1, "hot": 9.9,
         "content": "1、2026年9月23日晚，卫星互联网发射。",
         "contentChangedDate": "2026-10-20", "lastFetchDate": "2026-10-22",
         "path": ["商业航天"]},
        {"code": "B2", "name": "航天-卫星", "level": 2, "hot": 5.0,
         "content": "1、2026年10月21日，卫星互联网组网加速。",
         "contentChangedDate": "2026-10-21", "lastFetchDate": "2026-10-22",
         "path": ["航天", "航天-卫星"]},
    ]
    industry_stocks = [
        {"_id": "B1", "kind": "jiuyan_industry_stocks", "name": "商业航天",
         "stocks": [{"code": "001270", "name": "铖昌科技"}]},   # 龙头不在 → not_member
        {"_id": "HK", "kind": "jiuyan_industry_stocks", "name": "航天",
         "stocks": [{"code": "600327", "name": "大东方"}]},     # 经祖先验明 member
    ]
    action = [{"_id": "2026-10-22:final", "fields": [
        {"name": "大消费", "count": 1, "stocks": [
            {"code": "sh600327", "name": "大东方",
             "expound": "航天+零售\n1、公司门店情况。"},
        ]},
    ]}]
    db = _db(industry=industry, topic=[], news=[], calendar=[],
             industry_stocks=industry_stocks)
    db.cols["jiuyan_action"] = FakeCol(action)
    out = D.build_theme_evidence_block(db, board_name="大消费", date="2026-10-22",
                                       leader_code="600327")
    assert out["s3State"] == "injected", "同词第二候选过门即注入"
    assert out["s3Node"] == "航天-卫星" and out["s3Term"] == "航天"
    assert "组网加速" in out["text"] and "成分未核验" not in out["text"]


def test_driver_tag_audit_fields_attribute_to_state_candidate():
    """review minor-1（2026-11-18）：s3Term/s3Node = state 归因候选（首个跳过原因），
    非最后尝试候选——候选 A 残桩→候选 B not_member，终态 skipped_stub_content 必须配 A。"""
    industry = [
        {"code": "B1", "name": "商业航天", "level": 1, "hot": 9.9,
         "content": "航天",   # 残桩（≤9 字）
         "contentChangedDate": "2026-10-20", "lastFetchDate": "2026-10-22",
         "path": ["商业航天"]},
        {"code": "B2", "name": "航天-卫星", "level": 2, "hot": 5.0,
         "content": "1、2026年10月21日，卫星互联网组网加速。",
         "contentChangedDate": "2026-10-21", "lastFetchDate": "2026-10-22",
         "path": ["航天", "航天-卫星"]},
    ]
    industry_stocks = [{"_id": "HK", "kind": "jiuyan_industry_stocks", "name": "航天",
                        "stocks": [{"code": "001270", "name": "铖昌科技"}]}]
    action = [{"_id": "2026-10-22:final", "fields": [
        {"name": "大消费", "count": 1, "stocks": [
            {"code": "sh600327", "name": "大东方",
             "expound": "航天+零售\n1、公司门店情况。"},
        ]},
    ]}]
    db = _db(industry=industry, topic=[], news=[], calendar=[],
             industry_stocks=industry_stocks)
    db.cols["jiuyan_action"] = FakeCol(action)
    out = D.build_theme_evidence_block(db, board_name="大消费", date="2026-10-22",
                                       leader_code="600327")
    assert out["s3State"] == "skipped_stub_content"
    assert out["s3Node"] == "商业航天" and out["s3Term"] == "航天", \
        "审计指向首个跳过原因候选（A 残桩），非最后尝试（B not_member）"


def test_guangbai_retail_tree_mismatch_end_to_end():
    """2026-11-18 B9 广百案端到端回归（库内事实复刻）：「大消费」contains 命中
    全部大消费-* 子节点（level/hot 全同）旧版取最短名「酒」；Fix-1 切词补 ；后
    「零售」独立成词，Fix-4 同档 tie-break 选「大消费-零售百货」（诚实残桩缺席行），
    Fix-2/3 使 L1「零售百货」真正文（无快照）披露式注入。"""
    industry = [
        {"code": "C1", "name": "大消费-酒", "level": 2, "hot": 0.0,
         "content": "酒", "contentChangedDate": "2026-09-26",
         "lastFetchDate": "2026-11-17", "path": ["大消费", "大消费-酒"]},
        {"code": "C2", "name": "大消费-零售百货", "level": 2, "hot": 0.0,
         "content": "零售百货", "contentChangedDate": "2026-09-26",
         "lastFetchDate": "2026-11-17", "path": ["大消费", "大消费-零售百货"]},
        {"code": "R1", "name": "零售百货", "level": 1, "hot": -2.28,
         "content": "2026年10月20日，国家发展改革委新闻发布会表示促进百货零售转型。",
         "contentChangedDate": "2026-10-20", "lastFetchDate": "2026-11-17",
         "path": ["零售百货"]},
    ]
    industry_stocks = [{"_id": "DC", "kind": "jiuyan_industry_stocks",
                        "name": "大消费", "batchDate": "2026-10-25",
                        "stocks": [{"code": "002187", "name": "广百股份"}]}]
    action = [{"_id": "2026-11-17:final", "fields": [
        {"name": "大消费", "count": 1, "stocks": [
            {"code": "sz002187", "name": "广百股份",
             "expound": "零售；据2026年半年报，公司从事百货零售\n1、主业百货零售。"},
        ]},
    ]}]
    db = _db(industry=industry, topic=[], news=[], calendar=[],
             industry_stocks=industry_stocks)
    db.cols["jiuyan_action"] = FakeCol(action)
    out = D.build_theme_evidence_block(db, board_name="大消费", date="2026-11-17",
                                       leader_code="002187")
    text = out["text"]
    assert "产业树「大消费-零售百货」无催化正文" in text, \
        "Fix-4：同档 tie-break 选业务相关兄弟（诚实残桩缺席行；「节点」违禁词已删，review P2）"
    assert "大消费-酒" not in text, "最短名排序伪影消除"
    assert out["tagPreferredTerm"] == "零售"
    assert "产业树补充映射（龙头标签词「零售」关联「零售百货」，成分未核验，" in text
    assert "国家发展改革委" in text, "Fix-1+2+3：唯一真正文节点披露式注入"
    assert out["s3State"] == "injected_unverifiable"
    assert out["s3Term"] == "零售" and out["s3Node"] == "零售百货"


def test_tag_aware_pick_only_breaks_level_hot_ties():
    """Fix-4 边界：level/hot 有差异时排序有意义不覆写（睿能宽父节点案，
    2026-10-30d 首通道不替换设计）；仅同档 tie 时标签词破 tie。"""
    parent = {"name": "半导体产业链", "level": 1, "hot": 12.0}
    child = {"name": "半导体产业链-存储芯片", "level": 2, "hot": 18.0}
    m = {"node": parent, "candidate_nodes": [parent, child]}
    assert D._tag_aware_pick(m, "存储芯片+机器人") == (parent, None)
    a = {"name": "大消费-酒", "level": 2, "hot": 0.0}
    b = {"name": "大消费-零售百货", "level": 2, "hot": 0.0}
    m2 = {"node": a, "candidate_nodes": [a, b]}
    assert D._tag_aware_pick(m2, "零售；据半年报") == (b, "零售")
    assert D._tag_aware_pick(m2, "") == (a, None)
    assert D._tag_aware_pick({"node": a, "candidate_nodes": [a]}, "零售") == (a, None)


def test_stub_content_treated_as_no_catalyst():
    """残桩正文门槛（2026-11-14）：ai_industry 788/995 节点正文 ≤9 字自复述
    （「大消费-酒」正文=「酒」），零信息量整行不投喂——首通道按「无催化正文」
    渲染、hasContent=False（三层缺失门不被假证据托底）；S3 残桩同样不注入。"""
    industry = [
        {"code": "C1", "name": "大消费-酒", "level": 2, "hot": 0.0,
         "content": "酒", "contentChangedDate": "2026-09-26",
         "lastFetchDate": "2026-10-22", "path": ["大消费", "大消费-酒"]},
        {"code": "C2", "name": "白酒概念", "level": 1, "hot": 3.0,
         "content": "白酒", "contentChangedDate": "2026-09-26",
         "lastFetchDate": "2026-10-22", "path": ["白酒概念"]},
    ]
    action = [{"_id": "2026-10-22:final", "fields": [
        {"name": "大消费", "count": 2, "stocks": [
            {"code": "sh600327", "name": "大东方",
             "expound": "零售+白酒+民营医院\n1、公司商业零售门店情况。"},
        ]},
    ]}]
    db = _db(industry=industry, topic=[], news=[], calendar=[],
             industry_stocks=[])
    db.cols["jiuyan_action"] = FakeCol(action)
    out = D.build_theme_evidence_block(db, board_name="大消费", date="2026-10-22",
                                       leader_code="600327")
    text = out["text"]
    assert "板块级催化：产业树「大消费-酒」无催化正文" in text
    assert "节点" not in text, "2026-11-18b review P2：「节点」在 hygiene FORBIDDEN 表，删词保义"
    assert "板块级催化原文" not in text
    assert out["hasContent"] is False
    # S3 同门：标签词「白酒」命中残桩节点 → 不注入
    assert "产业树补充映射" not in text
    assert out["s3State"] == "skipped_stub_content"


def test_tag_terms_split_is_deterministic():
    """切词确定性：按分隔符切、剥泛词黑名单与 <2 字碎片，不做语义分词。"""
    assert D._tag_terms("人形机器人（金属腱绳）+商业航天+光伏+轮胎") == \
        ["人形机器人", "金属腱绳", "商业航天"]
    assert D._tag_terms("应用+科技") == [], "泛词黑名单内的词不作候选"
    assert D._tag_terms("") == [] and D._tag_terms(None) == []
    assert D._tag_terms("零售；据2026年半年报，公司从事百货零售") == \
        ["零售", "据2026年半年报", "公司从事百货零售"], \
        "2026-11-18 B9 Fix-1：；;。：: 入分隔符集（KPL expound 通用格式，广百案「零售」此前被；粘成不可匹配整块）"


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


# ── 早报节（2026-11-14 晨间例外，include_morning=True；缺省 False 题材链零变化）──

MORNING_OK = {"_id": "2026-10-23", "kind": "jiuyan_morning_report", "date": "2026-10-23",
              "state": "ok", "title": "早报",
              "content": "1、热点事件\n1）物理AI：英伟达GTC大会10月23日在柏林举行。\n2）固态电池：某厂发布量产时间表。",
              "paragraphs": ["1、热点事件",
                             "1）物理AI：英伟达GTC大会10月23日在柏林举行。",
                             "2）固态电池：某厂发布量产时间表。"],
              "fetchedAt": "2026-10-23T08:31:00", "quality": {"tokenSource": "cache+minted"}}


def _db_with_morning(doc=None):
    db = _db()
    if doc is not None:
        db.cols["jiuyan_morning_report"] = FakeCol([doc])
    return db


def test_include_morning_default_off_zero_change():
    """缺省 include_morning=False：库里哪怕有早报档，叙事零字节变化（题材链回归锚）。"""
    with_doc = _db_with_morning(MORNING_OK)
    without = _db_with_morning()
    a = D.build_theme_evidence_block(with_doc, board_name="物理AI", date="2026-10-23")
    b = D.build_theme_evidence_block(without, board_name="物理AI", date="2026-10-23")
    assert a["text"] == b["text"], "默认关=字节级零变化"
    assert "早盘催化" not in a["text"] and a["morningState"] is None


def test_include_morning_renders_matched_paragraphs():
    db = _db_with_morning(MORNING_OK)
    res = D.build_theme_evidence_block(db, board_name="物理AI", date="2026-10-23",
                                       include_morning=True)
    assert "早盘催化（韭研早报 2026-10-23）：" in res["text"]
    assert "- 1）物理AI：英伟达GTC大会10月23日在柏林举行。" in res["text"]
    assert "固态电池" not in res["text"], "未命中段不进叙事（整段缺席）"
    assert res["morningState"] == "ok" and res["morningDate"] == "2026-10-23"
    assert len(res["morningHits"]) == 1 and res["morningHits"][0]["matchHow"]


def test_include_morning_no_hit_whole_line_absent():
    db = _db_with_morning(MORNING_OK)
    res = D.build_theme_evidence_block(db, board_name="俄乌重建", date="2026-10-23",
                                       include_morning=True)
    assert "早盘催化" not in res["text"], "无命中=整行缺席，不出占位"
    assert res["morningState"] == "no_hit"


def test_include_morning_missing_and_not_published_disclosed_only_in_state():
    db = _db_with_morning()
    res = D.build_theme_evidence_block(db, board_name="物理AI", date="2026-10-23",
                                       include_morning=True)
    assert "早盘催化" not in res["text"] and res["morningState"] == "missing"
    db2 = _db_with_morning({**MORNING_OK, "state": "not_published", "paragraphs": [],
                            "content": "", "title": ""})
    res2 = D.build_theme_evidence_block(db2, board_name="物理AI", date="2026-10-23",
                                        include_morning=True)
    assert "早盘催化" not in res2["text"] and res2["morningState"] == "not_published"


def test_include_morning_char_budget_600():
    long_para = "1）物理AI：" + "长" * 700
    db = _db_with_morning({**MORNING_OK,
                           "paragraphs": [long_para, "1）固态电池：量产。"],
                           "content": long_para})
    res = D.build_theme_evidence_block(db, board_name="物理AI", date="2026-10-23",
                                       include_morning=True)
    assert "固态电池" not in res["text"], "预算耗尽后续段整段不入"
    body = [ln for ln in res["text"].splitlines() if ln.startswith("- 1）")]
    assert body and len(body[0]) <= D.MORNING_CHARS + 4, "首段截断至预算（含「- 」前缀与省略号）"


def test_include_morning_disabled_for_coarse_bucket():
    db = _db_with_morning(MORNING_OK)
    res = D.build_theme_evidence_block(db, board_name="公告", date="2026-10-23",
                                       include_morning=True)
    assert "早盘催化" not in res["text"] and res["morningState"] == "disabled"


def test_match_morning_paragraphs_deterministic():
    hits = D.match_morning_paragraphs(MORNING_OK["paragraphs"], "物理AI")
    assert len(hits) == 1 and "物理AI" in hits[0]["text"]
    assert D.match_morning_paragraphs(MORNING_OK["paragraphs"], "俄乌重建") == []
    assert D.match_morning_paragraphs(MORNING_OK["paragraphs"], None) == []


# ── 隔夜快讯节（2026-11-14 C 阶段，include_flash=True；缺省 False 题材链零变化）──

def _epoch(date_hhmm: str) -> int:
    from datetime import datetime, timedelta, timezone
    tz = timezone(timedelta(hours=8))
    return int(datetime.strptime(date_hhmm, "%Y-%m-%d %H:%M").replace(tzinfo=tz).timestamp())


FLASH_OK = [
    {"_id": "2026-11-13:2001", "kind": "ths_flash", "id": "2001", "seq": "3001",
     "title": "物理AI产业链获大额订单，龙头业绩超预期",
     "digest": "物理AI产业链获大额订单，龙头业绩超预期",
     "ctimeEpoch": _epoch("2026-11-13 21:30"), "ctimeDate": "2026-11-13", "ctimeHHMM": "21:30",
     "source": "", "stocks": [{"name": "中科曙光", "code": "603019"}], "tags": ["AI"],
     "firstSeenDate": "2026-11-14"},
    {"_id": "2026-11-14:2002", "kind": "ths_flash", "id": "2002", "seq": "3002",
     "title": "隔夜外盘：美股三大指数收跌",
     "digest": "隔夜外盘：美股三大指数收跌",
     "ctimeEpoch": _epoch("2026-11-14 07:10"), "ctimeDate": "2026-11-14", "ctimeHHMM": "07:10",
     "source": "", "stocks": [], "tags": ["美股"], "firstSeenDate": "2026-11-14"},
]


def _db_with_flash(rows=None):
    db = _db()
    if rows is not None:
        db.cols["ths_flash"] = FakeCol(rows)
    return db


def test_include_flash_default_off_zero_change():
    with_doc = _db_with_flash(FLASH_OK)
    without = _db_with_flash()
    a = D.build_theme_evidence_block(with_doc, board_name="物理AI", date="2026-11-14")
    b = D.build_theme_evidence_block(without, board_name="物理AI", date="2026-11-14")
    assert a["text"] == b["text"], "默认关=字节级零变化"
    assert "隔夜快讯" not in a["text"] and a["flashState"] is None


def test_include_flash_renders_matched_title_with_ctime():
    db = _db_with_flash(FLASH_OK)
    res = D.build_theme_evidence_block(db, board_name="物理AI", date="2026-11-14",
                                       include_flash=True)
    assert "隔夜快讯（同花顺7×24）：" in res["text"]
    assert "- 2026-11-13 21:30 物理AI产业链获大额订单" in res["text"]
    assert "美股三大指数收跌" not in res["text"], "未命中条目不进叙事"
    assert res["flashState"] == "ok" and res["flashDate"] == "2026-11-14"
    assert res["flashHits"][0]["matchHow"] and res["flashHits"][0]["stocks"][0]["code"] == "603019"


def test_include_flash_digest_anchor_weak_hit():
    db = _db_with_flash([{**FLASH_OK[0], "title": "隔夜要闻汇总",
                          "digest": "物理AI产业链获大额订单"}])
    res = D.build_theme_evidence_block(db, board_name="物理AI", date="2026-11-14",
                                       include_flash=True)
    assert res["flashState"] == "ok" and res["flashHits"][0]["matchHow"], "digest 兑底命中"


def test_include_flash_no_hit_and_missing():
    db = _db_with_flash([FLASH_OK[1]])
    res = D.build_theme_evidence_block(db, board_name="物理AI", date="2026-11-14",
                                       include_flash=True)
    assert "隔夜快讯" not in res["text"] and res["flashState"] == "no_hit"
    db2 = _db_with_flash()
    res2 = D.build_theme_evidence_block(db2, board_name="物理AI", date="2026-11-14",
                                        include_flash=True)
    assert "隔夜快讯" not in res2["text"] and res2["flashState"] == "missing"


def test_include_flash_window_cutoff_0926_blocks_lookahead():
    """09:26 截止 baked 进读口：盘后重跑/回放时，当日 09:26 后发布的条目不得进晨间证据
    （防单只重跑/回放用盘后语料重建前视，2026-11-13 21:10 重跑教训同类）。"""
    late = {**FLASH_OK[1], "id": "2003", "ctimeEpoch": _epoch("2026-11-14 14:00"),
            "ctimeDate": "2026-11-14", "ctimeHHMM": "14:00",
            "title": "物理AI板块午后拉升", "digest": "物理AI板块午后拉升"}
    db = _db_with_flash(FLASH_OK + [late])
    res = D.build_theme_evidence_block(db, board_name="物理AI", date="2026-11-14",
                                       include_flash=True)
    assert "14:00" not in res["text"], "09:26 后条目不得进晨间窗"
    assert res["flashState"] == "ok"


def test_include_flash_disabled_for_coarse_bucket():
    db = _db_with_flash(FLASH_OK)
    res = D.build_theme_evidence_block(db, board_name="公告", date="2026-11-14",
                                       include_flash=True)
    assert "隔夜快讯" not in res["text"] and res["flashState"] == "disabled"


def test_match_flash_items_deterministic():
    hits = D.match_flash_items(FLASH_OK, "物理AI")
    assert len(hits) == 1 and "物理AI" in hits[0]["title"]
    assert D.match_flash_items(FLASH_OK, "俄乌重建") == []
    assert D.match_flash_items(FLASH_OK, None) == []


def test_include_morning_late_fetch_not_rendered():
    """迟到档：fetch 时点晚于当日 09:26（重启补跑采到晚间早报）→ 不渲染防前视，
    morningState=late 结构化披露（评审修复 P2-1，与快讯侧截止对齐）。"""
    late = {**MORNING_OK, "fetchedAt": "2026-10-23T09:40:00"}
    res = D.build_theme_evidence_block(_db_with_morning(late), board_name="物理AI",
                                       date="2026-10-23", include_morning=True)
    assert "早盘催化" not in res["text"] and res["morningHits"] == []
    assert res["morningState"] == "late" and res["morningDate"] == "2026-10-23"
    # 恰 09:26 及以前仍正常渲染（现有 08:31 夹具路径不受影响）
    ok = D.build_theme_evidence_block(_db_with_morning(MORNING_OK), board_name="物理AI",
                                      date="2026-10-23", include_morning=True)
    assert ok["morningState"] == "ok" and "早盘催化" in ok["text"]


def test_include_flash_exact_0926_boundary_excluded():
    """恰 09:26:00 发布的条目不进半开窗口 [T−1 15:00, 09:26)；09:25:59 正常进。"""
    end = _epoch("2026-11-14 09:26")
    at_end = {**FLASH_OK[1], "id": "2099", "ctimeEpoch": end,
              "ctimeDate": "2026-11-14", "ctimeHHMM": "09:26",
              "title": "物理AI板块竞价异动", "digest": "物理AI板块竞价异动"}
    just_before = {**FLASH_OK[1], "id": "2098", "ctimeEpoch": end - 1,
                   "ctimeDate": "2026-11-14", "ctimeHHMM": "09:25",
                   "title": "物理AI盘前利好", "digest": "物理AI盘前利好"}
    db = _db_with_flash(FLASH_OK + [at_end, just_before])
    res = D.build_theme_evidence_block(db, board_name="物理AI", date="2026-11-14",
                                       include_flash=True)
    assert "09:26 物理AI板块竞价异动" not in res["text"], "恰 09:26:00 不含"
    assert "物理AI盘前利好" in res["text"] and res["flashState"] == "ok"


# ── 2026-11-17 语料精简（用户裁决，西陇科学案例）：枚举压缩/摘录截断治理/零日区间化 ──

def test_compress_enum_long_run_only():
    long = ("公司PCB用化学试剂包括各类规格的过硫酸钠、硫酸铜、硝酸银、氢氧化钠、盐酸、"
            "硫酸、硝酸、环氧氯丙烷、氢氟酸、丙酮、氨水、甲醛等。")
    out = D._compress_enum(long)
    assert "过硫酸钠、硫酸铜、硝酸银等" in out
    assert "氢氧化钠" not in out and "等等" not in out
    # 短枚举（<8 项）原样不动
    short = "剥离液、显影液、蚀刻液、清洗液等"
    assert D._compress_enum(short) == short
    # 尾随「等+类别词」不被吞并、不产生叠「等」
    tail = "甲、乙、丙、丁、戊、己、庚、辛等关键品类持续优化"
    out2 = D._compress_enum(tail)
    assert "关键品类" in out2 and "等等" not in out2


def test_clip_excerpt_sentence_boundary():
    t = ("1、公司铜蚀刻液实现量产供应。 2、2026年9月12日网传研报，需求上涨。 "
         "3、2026年6月23日网传纪要，氧化锆卡盘国产替代")
    out = D._clip_excerpt(t, 60)
    assert out.endswith("…") and "氧化锆" not in out, "半句碎片不投喂"
    assert "需求上涨" in out and "。…" not in out, "2026-11-17b：句号让位省略号，双省略号杂揉治理"
    # 枚举压缩+句界截断叠加：「等。…」→「等…」（西陇科学 PCB 试剂清单案例，长引导句）
    enum_t = ("1、公司PCB用化学试剂包括各类规格的过硫酸钠、硫酸铜、硝酸银、氢氧化钠、"
              "盐酸、硫酸、硝酸、环氧氯丙烷、氢氟酸、丙酮、氨水、甲醛等。 2、后续另述")
    first_sent = D._compress_enum(enum_t)
    first_sent = first_sent[:first_sent.index("。") + 1]
    enum_out = D._clip_excerpt(D._compress_enum(enum_t), len(first_sent) + 3)
    assert enum_out.endswith("等…") and "。…" not in enum_out
    # 短引导句编号头不得被吞成枚举首项（2026-11-17b  lookahead 修复）
    short_lead = "1、试剂包括过硫酸钠、硫酸铜、硝酸银、氢氧化钠、盐酸、硫酸、硝酸、环氧氯丙烷、氢氟酸、丙酮、氨水、甲醛等"
    assert D._compress_enum(short_lead).startswith("1、试剂包括过硫酸钠、硫酸铜、硝酸银等")
    # review n2：「N、。」尾编号空头先删句号再剔编号（反序会 bypass）
    assert D._clip_excerpt("甲。3、。" + "x" * 100, 7) == "甲…"
    assert D._clip_excerpt(t, 500) == t, "预算内原样"
    # 无句界 → 硬截断保留（宁截勿空，fail-visible）
    nb = D._clip_excerpt("无句界长文本" * 10, 20)
    assert nb.endswith("…") and len(nb) == 21
    # 回退后只剩编号空头 → 剔除
    t2 = "首句完整。 2、 " + "x" * 100
    assert "2、" not in D._clip_excerpt(t2, 12)


def test_heat_line_zero_run_compression():
    series = {"series": [
        {"date": "2026-11-08", "newsN": 0, "eventN": 1, "maxHot": 75731},
        *[{"date": f"2026-11-{d:02d}", "newsN": 0, "eventN": 0, "maxHot": None}
          for d in range(9, 18)],
    ]}
    assert D._heat_line(series) == ("11-08 新闻0·事件1（最高热度75731）；"
                                    "11-09~11-17 新闻0·事件0（连续9日）")
    # 单日零值原样（不区间化）；非零日逐日照出
    one = {"series": [{"date": "2026-11-08", "newsN": 1, "eventN": 0, "maxHot": None},
                      {"date": "2026-11-09", "newsN": 0, "eventN": 0, "maxHot": None},
                      {"date": "2026-11-10", "newsN": 2, "eventN": 0, "maxHot": None}]}
    assert D._heat_line(one) == "11-08 新闻1·事件0；11-09 新闻0·事件0；11-10 新闻2·事件0"
