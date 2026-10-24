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


def test_not_a_theme_includes_yiliao_yiyao_variant():
    assert "医疗医药" in D.NOT_A_THEME and "医药医疗" in D.NOT_A_THEME


# ── 证据块：产业树 + 开盘啦三节 ────────────────────────────────────────
def test_block_contains_industry_and_kpl_sections():
    out = D.build_theme_evidence_block(_db(), board_name="机器人", date="2026-10-22")
    text = out["text"]
    assert text.startswith(D.BLOCK_HEADER)
    assert "板块级催化原文（韭研产业树「国产机器人」，匹配方式 contains" in text
    # 开盘啦题材事件：标题锚匹配（GTC 内容含机器人）
    assert "当日题材事件（开盘啦题材事件" in text
    assert "- 2026-10-21 英伟达GTC大会来了！黃仁勋重磅演讲" in text
    assert "黄仁勋将在21日发表主题演讲" in text
    # 前瞻日历（开盘啦）
    assert "未来 3 日既定事件（开盘啦题材日历）" in text
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
    assert "近两日题材新闻（开盘啦题材新闻，Kword 题材标签关联）" in text
    assert "- 2026-10-22 [俄乌重建] 泽连斯基表态推动和平协议预期" in text
    assert "南矿集团" in text and "matchHow" not in text
    assert out["kwordTags"] == ["俄乌重建"]
    # 产业树无俄乌重建节点，但 L2 板内解析在 → 不判缺失
    assert "板块级催化：未映射" in text
    assert "板内解析（韭研异动「俄乌重建」" in text
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
    assert "- 2026-10-22 俄乌和平：泽连斯基表示乌方愿达成和平协议（共享子串「俄乌」" in out["text"]
    assert out["events"][0]["matchHow"] == "共享子串「俄乌」"


def test_block_fail_visible_paths():
    # 1) 语料未采集（全空，且无 L2）
    empty = D.build_theme_evidence_block(FakeDb(), board_name="机器人", date="2026-10-22")
    assert "未采集" in empty["text"] and "无数据 ≠ 无催化" in empty["text"]
    assert empty["evidenceMissing"] is True
    assert empty["evidenceMissingReason"] == "corpus_not_collected"

    # 2) 板块未映射且无事件/新闻/L2 → 才判缺失
    db = _db(news=[], calendar=[])
    out = D.build_theme_evidence_block(db, board_name="培育钻石", date="2026-10-22")
    assert "未映射" in out["text"] and "不代表无催化" in out["text"]
    assert out["industry"] is None
    assert out["evidenceMissingReason"] == "industry_tree_unmapped"

    # 3) 已映射但正文空且无事件
    db3 = _db(industry=[{"code": "0300", "name": "存储芯片", "level": 1, "hot": 1.2,
                         "content": "", "lastFetchDate": "2026-10-22"}],
              news=[], calendar=[])
    out3 = D.build_theme_evidence_block(db3, board_name="存储", date="2026-10-22")
    assert "无催化正文" in out3["text"] and "原文为空" in out3["text"]
    assert out3["evidenceMissingReason"] == "no_content_no_event"

    # 4) 无匹配事件 ≠ 无催化（产业树正文在 → 有可用证据）
    out4 = D.build_theme_evidence_block(_db(topic=[], news=[], calendar=[]),
                                        board_name="机器人", date="2026-10-22")
    assert "当日题材事件：无匹配" in out4["text"]
    # 2026-10-24a：新闻与日历双空合并为一行（原两行各带一遍「无数据 ≠ 无催化」套话）
    assert "题材新闻/前瞻日历：均无匹配（「机器人」Kword 标签与日历均未命中" in out4["text"]
    assert "近两日题材新闻：无匹配" not in out4["text"]
    assert "未来 3 日既定事件：无匹配" not in out4["text"]
    assert out4["evidenceMissing"] is False, "产业树正文在 → 有可用证据，不判缺失"


def test_block_marks_stale_corpus():
    stale_top = [{**e, "lastFetchDate": "2026-10-17"} for e in TOPIC]
    db = _db(industry=[{**NODES[0], "lastFetchDate": "2026-10-17"}],
             topic=stale_top, news=[], calendar=[])
    out = D.build_theme_evidence_block(db, board_name="机器人", date="2026-10-22")
    assert "非当日" in out["text"] and out["state"]["stale"] is True


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
    assert "…[截断，原文 800 字]" in out["text"]
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
    assert "开盘啦题材日历" in text


# ── v5：题材热度序列（炒作深度/延续性判据的核心原料） ─────────────────────
def test_heat_series_daily_aggregation_and_trend_line():
    db = _db()
    out = D.build_theme_evidence_block(db, board_name="俄乌重建", date="2026-10-22",
                                       leader_code="001360")
    text = out["text"]
    assert "题材热度序列（近 5 日新闻/事件按日聚合；看新增密度是否断流/见顶）：" in text
    # 10-22 有 Kword=俄乌重建 的新闻 1 条
    assert "10-22 新闻1·事件0" in text
    # 无痕迹的日如实写 0（不断流伪装成有数据）
    assert "10-20 新闻0·事件0" in text
    assert out["heatSeries"]["any"] is True


def test_heat_series_empty_is_explicit_not_silent():
    db = _db(news=[], topic=[])
    out = D.build_theme_evidence_block(db, board_name="机器人", date="2026-10-22")
    assert "题材热度序列：近 5 日无该题材的新闻/事件痕迹（不代表无催化" in out["text"]
    assert out["heatSeries"]["any"] is False


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


def test_dateline_stripped_from_event_body():
    """电头剥离：通稿开头的「媒体+日期+消息/讯」与条目已带的日期/来源重复，剥后截断。

    确定性正则白名单——不命中（无日期模式/无消息·讯·电后缀）原文一字不动。
    """
    assert D._strip_dateline("新华社北京10月21日消息，对外发布。") == "对外发布。"
    assert D._strip_dateline("财联社10月21日讯，黄仁勋发表演讲。") == "黄仁勋发表演讲。"
    assert D._strip_dateline("10月21日电，正文。") == "正文。"
    assert D._strip_dateline("正文里出现10月21日消息不算电头") == "正文里出现10月21日消息不算电头"
    assert D._strip_dateline("3月15日正式发布产品") == "3月15日正式发布产品", "无消息/讯/电后缀不剥"
    # 端到端：事件正文剥电头后进入叙事
    events = [{"_id": "2026-10-22:x", "day": "2026-10-22", "title": "机器人大会",
               "content": "央视新闻10月22日消息，国产机器人产业大会开幕。",
               "hotVal": 1, "detailFetched": True, "lastFetchDate": "2026-10-22"}]
    out = D.build_theme_evidence_block(_db(topic=events, news=[], calendar=[]),
                                       board_name="机器人", date="2026-10-22")
    assert "国产机器人产业大会开幕" in out["text"]
    assert "央视新闻10月22日消息，" not in out["text"]


def test_news_calendar_merge_only_when_both_empty():
    """双空合并（2026-10-24a）：单边有命中必须维持分列（语义分层不损失）。"""
    # 新闻有命中（俄乌重建 Kword）、日历空 → 新闻节出命中行，日历节出独立无匹配行
    db = _db(calendar=[])
    db.cols["jiuyan_action"] = FakeCol(RUSSIA_ACTION)
    out = D.build_theme_evidence_block(db, board_name="俄乌重建", date="2026-10-22",
                                       leader_code="001360")
    assert "近两日题材新闻（开盘啦题材新闻" in out["text"]
    assert "未来 3 日既定事件：无匹配" in out["text"]
    assert "题材新闻/前瞻日历：均无匹配" not in out["text"]
    # relay 兼容形状（无新闻节）：日历空仍出独立无匹配行，不得被合并逻辑吞掉
    out2 = D.build_theme_evidence_block(_db(news=[], calendar=[]), board_name="机器人",
                                        date="2026-10-22", include_l2=False)
    assert "未来 3 日既定事件：无匹配" in out2["text"]
    assert "题材新闻/前瞻日历" not in out2["text"]
