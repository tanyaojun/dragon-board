# -*- coding: utf-8 -*-
"""题材词典治理清单生成器（一次性，2026-10-25）：全量 251 题材 role 建议 + kword 30 条归属。

产出 docs/hotlist-jev/theme-dict-governance-draft-20261025.md（待用户逐条裁定）；
裁定后人工映射层落 theme_dict_governance 集合（manual 范式，本脚本不落库只出清单）。
"""
import collections
import re

from backend.data.repositories.repository_factory import get_runtime_mongodb_database

db = get_runtime_mongodb_database()
docs = sorted(db['themes'].find({}), key=lambda x: x['name'])
by_theme = collections.defaultdict(set)
for m in db['theme_stock_mappings'].find({}):
    by_theme[str(m.get('themeId'))].add(str(m.get('stockCode') or '')[-6:])

MANUAL = {
    '中证A50成分股': 'exclude', '大基金持股': 'exclude', '汇金证金持股': 'exclude',
    '宇树机器人': 'episode', '智元机器人': 'episode', '优必选机器人': 'episode', '小米机器人': 'episode',
    'AGV机器人概念': 'episode', '外骨骼机器人': 'episode',
    '小米发布会': 'episode', '黑神话悟空概念': 'episode', 'Kimi智能助手': 'episode', 'Pika概念': 'episode',
    'DeepSeek概念': 'episode', '摩尔线程概念': 'episode', '影石全景相机': 'episode',
    '华为昇腾': 'episode', '华为海思概念': 'episode', '华为鸿蒙': 'episode', '华为问界': 'episode',
    '华为手机产业链': 'episode', '华为液冷快充': 'episode', '华为储能': 'episode', '华为甄选与支付': 'episode',
    '腾讯AI概念': 'episode', '阿里AI应用': 'episode', '蚂蚁金服概念': 'episode', '蚂蚁阿福概念': 'episode',
    '谷歌概念': 'episode', '甲骨文概念': 'episode', '字节跳动概念': 'episode', '小红书概念': 'episode',
    '智谱AI概念': 'episode', '京东概念': 'episode', '超聚变': 'episode',
    '长江存储概念': 'episode', '长鑫存储概念': 'episode', '麦角硫因概念': 'episode',
    '俄乌重建': 'episode', '海南封关概念': 'episode', '海南VPN': 'episode', '海峡两岸': 'episode',
    '西藏水电概念': 'episode', '远东大开发': 'episode', '中吉乌铁路概念': 'episode', '对日反制': 'episode',
    '出口管制概念': 'episode', '关税战概念': 'episode', '新疆': 'episode',
    '稳定币概念': 'episode', '数字货币概念': 'episode', '跨境支付': 'episode',
    '破净整理': 'style', '高股息': 'style', '涨价概念': 'style', '反内卷概念': 'style', '设备更新': 'style',
    '新质生产力': 'style', '统一大市场': 'style', '自主可控': 'style', '出海': 'style', '地方国资': 'style',
    '国企重组合并': 'style', '券商重组预期': 'style', '并购重组预期概念': 'style', '国企人工智能': 'style',
    '中字头概念': 'style', '人民币升值概念': 'style', '化债概念': 'style',
    '人形机器人': 'branch', '军工': 'branch', '军工信息化': 'branch', '军贸': 'branch', '商业航天': 'branch',
    '大飞机': 'branch', '低空经济': 'branch',
    'AI硬件': 'branch', 'AI手机': 'branch', 'AI眼镜概念': 'branch', 'AI视觉': 'branch', 'AI营销': 'branch',
    'AI安全': 'branch', 'AIGC应用': 'branch', '端侧AI概念': 'branch', '算力租赁概念': 'branch',
    '液冷服务器': 'branch', '高速铜缆互联': 'branch', '云计算': 'branch', '大厂算力梳理': 'branch',
    '核心城市算力': 'branch',
    '半导体设备': 'branch', '半导体材料': 'branch', '半导体存储器': 'branch', 'HBM存储': 'branch',
    '先进封装': 'branch', '扇出型封装': 'branch', 'IC载板': 'branch', '玻璃基板': 'branch',
    '光刻机概念': 'branch', '国产芯片概念': 'branch', '汽车芯片': 'branch', '模拟芯片': 'branch',
    '功率半导体': 'branch', 'SRAM存储概念': 'branch', '硅光技术概念': 'branch', '硅': 'branch',
    '光伏': 'branch', '光伏新技术': 'branch', '光伏辅材': 'branch', 'BC电池': 'branch', '钙钛矿电池': 'branch',
    '风电': 'branch', '核电': 'branch', '可控核聚变': 'branch', '氢能源': 'branch', '绿色甲醇': 'branch',
    '储能概念': 'branch', '充电桩': 'branch', '800V快充': 'branch', '充电宝概念': 'branch', '换电概念': 'branch',
    'V2G概念': 'branch', '智能电网': 'branch', '电力': 'branch', '北美电力基建': 'branch', '欧洲电力基建': 'branch',
    '消费电子': 'branch', '折叠屏概念': 'branch', 'MR概念': 'branch', 'Micro（硅基）OLED': 'branch',
    'LED概念': 'branch', '空中成像': 'branch', '动作捕捉概念': 'branch', '激光雷达': 'branch',
    '智能驾驶系统': 'branch', '车路云一体化': 'branch', '无人驾驶应用': 'branch', '无人车辆': 'branch',
    'AEBS概念': 'branch', '线控底盘': 'branch', '一体化压铸': 'branch', '一体化电感': 'branch',
    '复合集流体': 'branch',
    '锂电池材料': 'branch', '锂矿': 'branch', '固态电池概念': 'branch', '金属空气电池概念': 'branch',
    '卫星互联网': 'branch',
    '创新药进度整理': 'branch', '减肥药概念': 'branch', '中药': 'branch', '再生医学': 'branch',
    '干细胞概念': 'branch', '合成生物': 'branch', '阿尔兹海默症': 'branch', 'AI医疗': 'branch',
    'SPD医疗供应链': 'branch', '医美': 'branch', '维生素': 'branch',
    '农业种植': 'branch', '农机概念': 'branch', '农药': 'branch', '化肥': 'branch', '预制菜': 'branch',
    '食品安全': 'branch', '电子烟': 'branch',
    '旅游': 'branch', '户外运动': 'branch', '教培': 'branch', '宠物经济': 'branch', '银发经济': 'branch',
    '首发经济': 'branch', '谷子经济概念': 'branch', '服务消费概念': 'branch', '新消费': 'branch',
    '复苏消费概念': 'branch', '犒赏经济': 'branch', '线上送礼物概念': 'branch', '乙游概念': 'branch',
    '游戏': 'branch', '影视概念': 'branch', '短剧产业': 'branch', '文生视频概念': 'branch', '版权': 'branch',
    '财经媒体': 'branch',
    '港口航运': 'branch', '跨境电商': 'branch', '离境退税概念': 'branch', '烟花爆竹概念': 'branch',
    '工业母机': 'branch', '冷锻工艺概念': 'branch', '磁悬浮压缩机': 'branch', '5G-A': 'branch',
    '光纤': 'branch', '光通信设备': 'branch',
    '稀土永磁': 'branch', '小金属': 'branch', '金属铜': 'branch', '金属铝概念': 'branch', '黄金白银': 'branch',
    '煤炭概念': 'branch', '石油油气': 'branch', '磷化工': 'branch', '碳纤维': 'branch', '气凝胶': 'branch',
    '共聚聚甲醛': 'branch', 'PEEK轻量化材料': 'branch',
    '量子科技': 'branch', '脑机接口': 'branch', 'RISC-V概念': 'branch', 'FDE概念': 'branch',
    'MCP概念': 'branch', 'AI低代码概念': 'branch', '词元概念': 'branch', 'AI智能体概念': 'branch',
    '大模型概念': 'branch', 'AI PC概念': 'branch',
    '数据要素': 'branch', '数字政务': 'branch', '病毒防治': 'branch', '核污染概念': 'branch',
    '炭疽概念': 'branch', '房屋养老金概念': 'branch', '韧性城市概念': 'branch', '深地探索概念': 'branch',
    '海洋经济': 'branch', '地产链': 'branch',
    '西部大开发': 'branch', '西部陆海新通道': 'branch', '中部崛起概念': 'branch',
}
KW = {
    'AI算力基建': 'AI硬件', '俄乌重建': '俄乌重建', 'MLCC': '无对应（被动元件）', '物理AI': '物理AI概念',
    '轻量化材料': 'PEEK轻量化材料', '算电协同': '无对应（电力×算力交叉）', '电影（体育）消费': '影视概念',
    '飞行汽车（eVTOL）': '低空经济', 'AR眼镜': 'AI眼镜概念', '冰雪产业': '冰雪旅游概念', '硫磺': '磷化工',
    '硅料': '光伏', '电力设备': '电力', 'AI视频': '文生视频概念', 'AI安全': 'AI安全', 'AI应用': 'AIGC应用',
    '光遗传学': '无对应', '创新药': '创新药进度整理', 'DRAM': '半导体存储器', '固态电池': '固态电池概念',
    '玻璃基板': '玻璃基板', '硅片': '半导体材料', '矢量网络分析仪': '无对应（军工信息化·设备？）',
    '通信': '光通信设备', '金属镍': '无对应（小金属类？）', '覆铜板': '无对应（PCB 链）',
    '半导体设备': '半导体设备', '算力概念': '算力租赁概念', 'AI制药': 'AI医疗',
}


def autoguess(name: str) -> str:
    if re.search(r'成分股|持股$', name):
        return 'exclude'
    if re.search(r'机器人$|发布会|黑神话|Kimi|Pika|DeepSeek|摩尔线程|影石|蚂蚁|京东|小红书|腾讯|谷歌|甲骨文|字节|华为|小米|超聚变|存储概念|麦角硫因|智谱|俄乌|海南|西藏|两岸|铁路|远东|关税|反制|封关|稳定币|数字货币', name):
        return 'episode(自动)'
    return 'REVIEW'


rows, missing = [], []
for d in docs:
    n = d['name']
    tid = str(d['id'])
    cnt = len(by_theme.get(tid, set()))
    r = MANUAL.get(n)
    if r is None:
        r = autoguess(n)
        missing.append(n)
    rows.append((tid, n, cnt, r))
c = collections.Counter(r for *_, r in rows)

with open(r'D:\dragon-board\quant-board\docs\hotlist-jev\theme-dict-governance-draft-20261025.md',
          'w', encoding='utf-8') as f:
    f.write('# 题材词典治理清单（草案 v1，2026-10-25，待用户逐条裁定）\n\n')
    f.write('> 目的：题材周期（方案 B）前置的词典治理。role 分层：`branch`=泛概念维度（主线温度计层，'
            '不跑四阶段）；\n> `episode`=事件/公司/政策驱动（题材周期对象层，跑四阶段）；'
            '`style`=市场风格横切（无事件生命周期，不进周期）；\n> `exclude`=非题材（成分清单类，剔除）。\n\n')
    f.write('> 落库形态=人工映射层集合 `theme_dict_governance`（manual 不被上游刷新覆盖，'
            '同 sector_industry_map manual 范式）；\n> `themes`/`theme_stock_mappings` 上游数据不动。\n')
    f.write('> 裁定方式：直接改本文档建议值，或口头逐条拍板由 AI 落库。\n\n')
    f.write('## 一、role 建议分布\n\n| role | 数量 |\n|---|---|\n')
    for k in ('branch', 'episode', 'style', 'exclude', 'episode(自动)', 'REVIEW'):
        if c.get(k):
            f.write(f'| {k} | {c[k]} |\n')
    f.write('\n## 二、全量 251 题材 role 建议表\n\n| themeId | 题材名 | 成分数 | 建议 role |\n|---|---|---|---|\n')
    for tid, n, cnt, r in rows:
        f.write(f'| {tid} | {n} | {cnt} | {r} |\n')
    f.write('\n## 三、KPL kword（29 标签）→ themes 归属建议\n\n| kword | 建议归属 | 备注 |\n|---|---|---|\n')
    for k, v in sorted(KW.items()):
        f.write(f'| {k} | {v} | |\n')
    f.write('\n## 四、家族重叠摘要（成分包含率关键对）\n\n')
    f.write('- 宇树机器人(46) 91% ⊂ 人形机器人(240)；优必选 70% ⊂；智元 50% ⊂——机器人家族 7 题材\n')
    f.write('- 长鑫存储(60) ∩ 长江存储(60) = 53%；先进封装 ⊃ HBM 59%；液冷服务器 56% ⊂ AI硬件(385 巨无霸)\n')
    f.write('- 军工信息化(65) 60% ⊂ 商业航天(347)；军工(177) ⊃ 大飞机 54%\n')
    f.write('- 文生视频(23) ∩ AIGC应用(34) 57%、∩ 短剧产业(57) 52%——AI 内容家族三角互吞\n\n')
    f.write('## 五、待裁重点（AI 不确定、须用户拍板）\n\n')
    f.write('1. **横切风格类**（style 17 条）：破净整理/高股息/涨价概念/设备更新/出海/地方国资(346 只!)——'
            '是否一律不进题材周期？\n')
    f.write('2. **地域政策类**：新疆(46)/海峡两岸(77)/西藏水电/西部大开发/统一大市场——episode 还是 branch？\n')
    f.write('3. **巨无霸 branch**：AI硬件(385)/商业航天(347)/地方国资(346)/关税战(334)/涨价概念(220)——'
            '家数门槛下几乎日日出行的题材如何处置？\n')
    f.write('4. **kword 无对应 6 条**（MLCC/算电协同/光遗传学/矢量网络分析仪/金属镍/覆铜板）：'
            '不映射留缺口，还是新建 themes 题材？\n')
    f.write('5. **AI 自动判 REVIEW/episode(自动) 条目**（表中标注）逐条确认。\n')
print('未命中人工表(自动规则兜底):', len(missing), missing)
print('最终建议分布:', dict(c))
print('文档已写盘 theme-dict-governance-draft-20261025.md')
