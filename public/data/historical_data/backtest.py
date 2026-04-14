# backtest.py
# 主线龙头股回测脚本

import json
import os
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ========== 配置 ==========
DATA_DIR = "D:/dragon-board/public/data/historical_data"  # 你的数据文件夹路径
HOLD_DAYS = 1                    # 持有天数（临时用1天测试）
MIN_STRENGTH = 80                # 最小主线强度
MIN_CONFIDENCE = 50              # 最小龙头置信度

# ========== 加载数据 ==========
def load_snapshots(data_dir):
    """加载所有快照文件"""
    snapshots = []
    for filename in os.listdir(data_dir):
        if filename.startswith('daily_') and filename.endswith('.json'):
            with open(os.path.join(data_dir, filename), 'r', encoding='utf-8') as f:
                snapshots.append(json.load(f))
    
    # 按日期排序
    snapshots.sort(key=lambda x: x['date'])
    print(f"加载了 {len(snapshots)} 天的数据")
    if len(snapshots) > 0:
        print(f"数据范围: {snapshots[0]['date']} 到 {snapshots[-1]['date']}")
    return snapshots

# ========== 获取股票价格 ==========
def get_stock_price(snapshot, code):
    """从快照的热榜中获取股票价格"""
    hotlist = snapshot.get('hotlist', [])
    for stock in hotlist:
        if stock.get('code') == code:
            return stock.get('price')
    return None

# ========== 主线龙头回测 ==========
def run_backtest(snapshots, hold_days=3, min_strength=80, min_confidence=50):
    """主线龙头回测"""
    results = []
    
    for i in range(len(snapshots) - hold_days):
        today = snapshots[i]
        sell_day = snapshots[i + hold_days]
        
        # 1. 获取主线数据
        rotation = today.get('rotation')
        if not rotation:
            print(f"  {today['date']}: 无 rotation 数据")
            continue
        
        main_lines = rotation.get('mainLines', [])
        if not main_lines:
            print(f"  {today['date']}: 无 mainLines 数据")
            continue
        
        main = main_lines[0]  # 第一条主线
        theme_name = main.get('themeName')
        strength = main.get('strengthScore', 0)
        
        print(f"  {today['date']}: 主线={theme_name}, 强度={strength}")
        
        # 强度过滤
        if strength < min_strength:
            print(f"    强度不足 ({strength} < {min_strength})，跳过")
            continue
        
        # 2. 获取联动数据（龙头）
        correlations = today.get('themeCorrelations', [])
        corr = None
        for c in correlations:
            if c.get('themeName') == theme_name:
                corr = c
                break
        
        if not corr:
            print(f"    无联动数据")
            continue
        
        leader = corr.get('leader')
        if not leader:
            print(f"    无龙头数据")
            continue
        
        confidence = leader.get('confidence', 0)
        print(f"    龙头: {leader.get('name')}, 置信度={confidence}%")
        
        if confidence < min_confidence:
            print(f"    置信度不足 ({confidence} < {min_confidence})，跳过")
            continue
        
        # 3. 获取买入价（今日收盘价）
        buy_code = leader.get('code')
        buy_price = get_stock_price(today, buy_code)
        if not buy_price or buy_price == 0:
            print(f"    无法获取买入价")
            continue
        
        # 4. 获取卖出价（N日后）
        sell_price = get_stock_price(sell_day, buy_code)
        if not sell_price:
            print(f"    无法获取卖出价")
            continue
        
        # 5. 计算收益
        profit = (sell_price - buy_price) / buy_price * 100
        
        # 6. 记录结果
        results.append({
            'date': today['date'],
            'market_phase': rotation.get('marketPhase'),
            'theme': theme_name,
            'strength': strength,
            'persistent_days': main.get('persistentDays', 0),
            'leader_name': leader.get('name'),
            'leader_code': buy_code,
            'leader_score': leader.get('score'),
            'confidence': confidence,
            'buy_price': buy_price,
            'sell_price': sell_price,
            'profit_pct': profit
        })
        
        print(f"    ✅ 交易: 买入{buy_price} -> 卖出{sell_price} | 收益:{profit:.2f}%")
    
    if results:
        print(f"\n共产生 {len(results)} 笔交易")
    else:
        print(f"\n没有符合条件的交易")
    
    return pd.DataFrame(results) if results else pd.DataFrame()

# ========== 分析结果 ==========
def analyze_results(df):
    """分析回测结果"""
    if df.empty:
        print("\n没有交易记录，无法分析")
        return df
    
    print("\n" + "="*60)
    print("主线龙头股回测结果")
    print("="*60)
    print(f"持有天数: {HOLD_DAYS}")
    print(f"最小主线强度: {MIN_STRENGTH}")
    print(f"最小置信度: {MIN_CONFIDENCE}")
    print("-"*60)
    print(f"总交易次数: {len(df)}")
    print(f"盈利次数: {len(df[df['profit_pct'] > 0])}")
    print(f"亏损次数: {len(df[df['profit_pct'] < 0])}")
    print(f"胜率: {(df['profit_pct'] > 0).mean() * 100:.1f}%")
    print(f"平均收益: {df['profit_pct'].mean():.2f}%")
    print(f"最大收益: {df['profit_pct'].max():.2f}%")
    print(f"最大亏损: {df['profit_pct'].min():.2f}%")
    print(f"累计收益: {df['profit_pct'].sum():.2f}%")
    
    # 按市场阶段分组
    if 'market_phase' in df.columns and len(df['market_phase'].unique()) > 1:
        print("\n" + "-"*40)
        print("按市场阶段分组:")
        phase_stats = df.groupby('market_phase')['profit_pct'].agg(['count', 'mean', 'std'])
        print(phase_stats)
    
    # 按主线强度分组
    if len(df) > 1:
        print("\n" + "-"*40)
        print("按主线强度分组:")
        df['strength_group'] = pd.cut(df['strength'], 
                                       bins=[0, 60, 80, 100, 200],
                                       labels=['弱(<60)', '中(60-80)', '强(80-100)', '超强(>100)'])
        strength_stats = df.groupby('strength_group')['profit_pct'].agg(['count', 'mean'])
        print(strength_stats)
    
    # 最近5笔交易
    print("\n" + "-"*40)
    print("最近5笔交易:")
    print(df.tail(5)[['date', 'theme', 'leader_name', 'profit_pct', 'market_phase']])
    
    return df

# ========== 画图 ==========
def plot_results(df):
    """绘制结果图表"""
    if df.empty:
        print("\n没有交易记录，无法画图")
        return
    
    try:
        import matplotlib.pyplot as plt
        
        plt.figure(figsize=(14, 8))
        
        # 图1：累计收益曲线
        plt.subplot(2, 2, 1)
        df['cumulative'] = (1 + df['profit_pct']/100).cumprod()
        plt.plot(range(len(df)), df['cumulative'], marker='o', linewidth=2)
        plt.axhline(y=1, color='gray', linestyle='--')
        plt.title('累计收益曲线')
        plt.xlabel('交易次数')
        plt.ylabel('净值')
        plt.grid(True, alpha=0.3)
        
        # 图2：收益率分布
        plt.subplot(2, 2, 2)
        plt.hist(df['profit_pct'], bins=10, edgecolor='black', alpha=0.7)
        plt.axvline(x=0, color='red', linestyle='--')
        plt.title('收益率分布')
        plt.xlabel('收益率(%)')
        plt.ylabel('频次')
        plt.grid(True, alpha=0.3)
        
        # 图3：按市场阶段箱线图
        plt.subplot(2, 2, 3)
        if 'market_phase' in df.columns and len(df['market_phase'].unique()) > 1:
            df.boxplot(column='profit_pct', by='market_phase', ax=plt.gca())
            plt.title('不同市场阶段收益率')
            plt.xlabel('市场阶段')
            plt.ylabel('收益率(%)')
            plt.xticks(rotation=45)
        
        # 图4：按强度分组箱线图
        plt.subplot(2, 2, 4)
        if 'strength_group' in df.columns and len(df['strength_group'].unique()) > 1:
            df.boxplot(column='profit_pct', by='strength_group', ax=plt.gca())
            plt.title('不同主线强度收益率')
            plt.xlabel('主线强度')
            plt.ylabel('收益率(%)')
        
        plt.tight_layout()
        plt.savefig('backtest_result.png', dpi=150)
        plt.show()
        print("\n图表已保存到 backtest_result.png")
    except Exception as e:
        print(f"图表生成失败: {e}")

# ========== 主程序 ==========
if __name__ == '__main__':
    print("="*60)
    print("主线龙头股回测脚本")
    print("="*60)
    
    # 1. 加载数据
    snapshots = load_snapshots(DATA_DIR)
    
    if len(snapshots) < HOLD_DAYS + 1:
        print(f"\n数据不足，需要至少 {HOLD_DAYS + 1} 天数据，当前只有 {len(snapshots)} 天")
        print("请等待更多数据积累后再运行回测")
        exit()
    
    # 2. 运行回测
    print(f"\n开始回测...")
    print(f"持有天数: {HOLD_DAYS}")
    print(f"最小主线强度: {MIN_STRENGTH}")
    print(f"最小龙头置信度: {MIN_CONFIDENCE}")
    print("-"*40)
    
    results_df = run_backtest(snapshots, HOLD_DAYS, MIN_STRENGTH, MIN_CONFIDENCE)
    
    # 3. 分析结果
    results_df = analyze_results(results_df)
    
    # 4. 画图
    if not results_df.empty:
        plot_results(results_df)
        
        # 5. 保存结果
        results_df.to_csv('backtest_results.csv', index=False, encoding='utf-8-sig')
        print("\n结果已保存到 backtest_results.csv")
    else:
        print("\n没有交易记录，无法保存结果")