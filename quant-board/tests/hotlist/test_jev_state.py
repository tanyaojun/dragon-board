# -*- coding: utf-8 -*-
"""jev 构建器测试（阶段3 驱动打标保留件；阶段1/2 测试随证伪清理移除，见 git 历史）。"""
from backend.analysis.hotlist.jev_state import build_driver_label_narrative


def test_driver_label_narrative():
    mappings = [{"themeName": "AI影视", "tags": ["视频数据"], "reason": "图片数据资源类国内第一"},
                {"themeName": "上海国资", "tags": ["地方国资"], "reason": "上海国资背景"}]
    s = build_driver_label_narrative("首部AI电影上映+《三星堆：未来往事》",
                                     {"name": "新华传媒", "rank": 2, "mainTheme": "AI应用"},
                                     mappings)
    assert "新华传媒" in s and "首部AI电影上映" in s
    assert "AI影视" in s and "图片数据资源类国内第一" in s and "上海国资" in s
    assert "AI应用" in s


def test_driver_label_narrative_object_tags():
    mappings = [{"themeName": "AI影视", "tags": [{"Name": "视频数据"}], "reason": "图片数据资源类国内第一"}]
    s = build_driver_label_narrative("首部AI电影上映", {"name": "新华传媒", "rank": 2}, mappings)
    assert "标签:视频数据" in s


def test_driver_label_narrative_no_mapping():
    s = build_driver_label_narrative("算力租赁概念", {"name": "X股"}, [])
    assert "无题材映射记录" in s and "算力租赁概念" in s
