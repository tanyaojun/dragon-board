# -*- coding: utf-8 -*-
"""题材词典治理落库（2026-10-25，用户批准草案 v1 + 要求 kword/题材名尽量对齐 jiuyan 板块）。

落库 theme_dict_governance（人工映射层，manual 不被上游刷新覆盖）：
- kind=role    : themeId → {branch|episode|style|exclude}（251 全量）
- kind=kword   : KPL kword → themeId（变体归一）或 target="none"（无对应缺口，fail-visible）
- kind=jiuyan  : themeId → jiuyan 板块对照名（大盘情绪与题材情绪同名综合，用户要求）

幂等 upsert；上游 themes/theme_stock_mappings 零改动。
"""
import collections
import re
import sys

from backend.data.repositories.repository_factory import get_runtime_mongodb_database

RULED_BY = "user-20261025"

ROLES = {
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
    'AMD概念': 'episode', '英伟达概念': 'episode', '小米汽车': 'episode', '沙特合作概念': 'episode',
    '外卖概念': 'episode', '冰雪旅游概念': 'episode',
    '破净整理': 'style', '高股息': 'style', '涨价概念': 'style', '反内卷概念': 'style', '设备更新': 'style',
    '新质生产力': 'style', '统一大市场': 'style', '自主可控': 'style', '出海': 'style', '地方国资': 'style',
    '国企重组合并': 'style', '券商重组预期': 'style', '并购重组预期概念': 'style', '国企人工智能': 'style',
    '中字头概念': 'style', '人民币升值概念': 'style', '化债概念': 'style', '科技重组预期概念': 'style',
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
    '超节点概念': 'branch', '大金融': 'branch', '国潮消费': 'branch', '生育概念': 'branch',
    '灯塔工厂概念': 'branch', '拆解回收概念': 'branch', '新能车检概念': 'branch', '轮胎': 'branch',
    '磷化铟概念': 'branch', '韬（τ）定律概念': 'branch', 'ITER概念': 'branch', 'NMN概念': 'branch',
    '比亚迪产业链': 'branch', '物理AI概念': 'branch',
    '5G-A': 'branch', 'MCP概念': 'branch',
}

KW = {
    'AI算力基建': 'AI硬件', '俄乌重建': '俄乌重建', 'MLCC': None, '物理AI': '物理AI概念',
    '轻量化材料': 'PEEK轻量化材料', '算电协同': None, '电影（体育）消费': '影视概念',
    '飞行汽车（eVTOL）': '低空经济', 'AR眼镜': 'AI眼镜概念', '冰雪产业': '冰雪旅游概念', '硫磺': '磷化工',
    '硅料': '光伏', '电力设备': '电力', 'AI视频': '文生视频概念', 'AI安全': 'AI安全', 'AI应用': 'AIGC应用',
    '光遗传学': None, '创新药': '创新药进度整理', 'DRAM': '半导体存储器', '固态电池': '固态电池概念',
    '玻璃基板': '玻璃基板', '硅片': '半导体材料', '矢量网络分析仪': None, '通信': '光通信设备',
    '金属镍': None, '覆铜板': None, '半导体设备': '半导体设备', '算力概念': '算力租赁概念', 'AI制药': 'AI医疗',
}


def main() -> int:
    db = get_runtime_mongodb_database()
    themes = {str(d['id']): d['name'] for d in db['themes'].find({})}
    name2id = {v: k for k, v in themes.items()}
    col = db['theme_dict_governance']
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)

    n_role = n_kw = 0
    for tid, name in themes.items():
        role = ROLES.get(name)
        if role is None:
            print(f"[MISS] themeId={tid} {name} 无 role 建议（须补）")
            continue
        col.update_one({"_id": f"role:{tid}"},
                       {"$set": {"kind": "role", "themeId": tid, "name": name, "role": role,
                                 "ruledBy": RULED_BY, "updatedAt": now}}, upsert=True)
        n_role += 1
    for kword, target in KW.items():
        tid = name2id.get(target) if target else None
        if target and tid is None:
            print(f"[MISS] kword={kword} 目标题材 '{target}' 不在 themes（须补）")
            continue
        col.update_one({"_id": f"kword:{kword}"},
                       {"$set": {"kind": "kword", "kword": kword,
                                 "themeId": tid, "targetName": target or "none",
                                 "target": target if target else "none",
                                 "ruledBy": RULED_BY, "updatedAt": now}}, upsert=True)
        n_kw += 1
    print(f"role 落库 {n_role} 条，kword 落库 {n_kw} 条")

    # jiuyan 板块对照（用户要求：题材名尽量与 jiuyan 板块一致，大盘/题材情绪同名综合）
    names = set()
    for d in db["jiuyan_action"].find({"_id": {"$regex": ":final$"}}, {"fields.name": 1}):
        for fl in d.get("fields") or []:
            b = str(fl.get("name") or "")
            if b:
                names.add(b)
    print(f"jiuyan 历史板块名 {len(names)} 个")

    def norm(s: str) -> str:
        return re.sub(r"(概念|产业|经济|题材)$", "", s)

    n_jy = 0
    exact = fuzzy = 0
    for tid, name in themes.items():
        role_doc = col.find_one({"_id": f"role:{tid}"}) or {}
        if role_doc.get("role") not in ("episode", "branch"):
            continue
        target = None
        if name in names:
            target = name
            exact += 1
        else:
            nn = norm(name)
            cands = [b for b in names if norm(b) == nn]
            if not cands:
                cands = [b for b in names if nn and (nn in norm(b) or norm(b) in nn)
                         and abs(len(norm(b)) - len(nn)) <= 2]
            if cands:
                target = sorted(cands, key=len)[0]
                fuzzy += 1
        if target:
            col.update_one({"_id": f"jiuyan:{tid}"},
                           {"$set": {"kind": "jiuyan", "themeId": tid, "themeName": name,
                                     "jiuyanBoard": target, "match": "exact" if name == target else "fuzzy",
                                     "ruledBy": RULED_BY, "updatedAt": now}}, upsert=True)
            n_jy += 1
    print(f"jiuyan 对照落库 {n_jy} 条（精确 {exact} / 模糊 {fuzzy}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
