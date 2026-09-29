# -*- coding: utf-8 -*-
"""微信个股信息差解析/发现测试（fixture 取自真实文章结构）。"""
from backend.operations.wechat_info_diff import (
    article_text,
    parse_info_diff_entries,
    pick_latest_discovery,
)

FIXTURE_HTML = """<html><body><div id="js_content">
<p>盘中段子汇总</p>
<p>马斯克：人形机器人</p>
<p>（雪龙集团、襄阳轴承等）</p>
<p><strong>个股信息差（欢迎交流补充）</strong></p>
<p>1、</p>
<p><strong>善水科技：</strong>公司生产2-氯吡啶等氯代吡啶系列产品。2-氯吡啶是一种高附加值的精细化工产品</p>
<p>2、<strong>雪龙集团：</strong>公司通过深创投基金间接持股宇树科技，公司专注于内燃机冷却系统产品及汽车轻量化塑料产品的研产销</p>
<p>3、</p>
<p><strong>福建水泥：</strong>公司为福建省水泥行业的传统龙头企业，是福建地区产能规模最大的水泥制造企业</p>
<p>飞火挖掘社</p>
</div><script>x</script></body></html>"""

SOGOU_HTML = """
<a href="/link?url=AAA" id="sogou_vr_1"><em>3.3</em>个股信息差(元宵快乐)</a>
<a href="/link?url=BBB"><em>9.23</em>个股信息差(无题)</a>
<a href="/link?url=CCC">其他文章</a>
<a href="/link?url=DDD"><em>9.28</em>个股信息差(盘后)</a>
"""


def test_parse_entries():
    entries = parse_info_diff_entries(article_text(FIXTURE_HTML),
                                      known_names={"善水科技", "雪龙集团", "福建水泥"})
    names = [e["name"] for e in entries]
    assert names == ["善水科技", "雪龙集团", "福建水泥"]
    assert entries[0]["reason"].startswith("公司生产2-氯吡啶")
    assert entries[1]["reason"].startswith("公司通过深创投基金")
    assert all(len(e["reason"]) <= 600 for e in entries)


def test_parse_no_section():
    assert parse_info_diff_entries(article_text("<div id='js_content'>没有该栏目</div>")) == []


def test_pick_latest_discovery():
    best = pick_latest_discovery(SOGOU_HTML)
    assert best["month"] == 9 and best["day"] == 28
    assert best["href"].endswith("DDD")
    assert "9.28" in best["title"]


def test_parse_subnumbered_entry_merged():
    """条目内嵌 1、2、 子编号必须并入描述，不丢内容不产生幻影条目。"""
    html = """<div id="js_content">
    <p>个股信息差（欢迎交流补充）</p>
    <p>5、</p>
    <p><strong>襄阳轴承：</strong>1、公司是湖北省军民融合企业，根据2024年报东风公司的军车轴承一直指定公司独家供应；</p>
    <p>2、公司柔性轴承、交叉滚子轴承已试制完成，目前处于送样验证阶段。机器人用精密轴承项目已进入开发试制阶段</p>
    <p>6、</p>
    <p><strong>巨力索具：</strong>公司为商业航天地面发射提供了系统性保障</p>
    </div><script>x</script>"""
    entries = parse_info_diff_entries(article_text(html),
                                      known_names={"襄阳轴承", "巨力索具"})
    assert [e["name"] for e in entries] == ["襄阳轴承", "巨力索具"]
    assert "军民融合企业" in entries[0]["reason"] and "柔性轴承" in entries[0]["reason"]
    assert "商业航天" in entries[1]["reason"]
