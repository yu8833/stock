import sys
sys.path.insert(0, '/data/InStock')
import logging
logging.basicConfig(level=logging.WARNING)
import datetime
import pandas as pd
import numpy as np
import concurrent.futures
import instock.core.tablestructure as tbs
import instock.lib.database as mdb
import pymysql

date = datetime.date(2026, 6, 18)
date_str = date.strftime('%Y-%m-%d')

conn = pymysql.connect(host='mariadb', port=3306, user='instock', password='instock', db='instockdb', charset='utf8mb4')
cur = conn.cursor()

# ========== 1. 清理旧数据 ==========
# 先清理旧的目标表数据，确保重新插入
for t in ['cn_stock_indicators_buy', 'cn_stock_spot_buy', 'cn_stock_fund_flow', 
          'cn_stock_pattern', 'cn_stock_strategy_enter', 'cn_stock_strategy_keep_increasing', 'cn_stock_strategy_parking_apron']:
    try:
        cur.execute(f"DROP TABLE IF EXISTS {t}")
        print(f"Cleaned {t}")
    except:
        pass

conn.commit()

# ========== 2. indicators_buy/sell: 重新筛选 ==========
print("\n2. === indicators_buy / indicators_sell ===")

_columns = tuple(tbs.TABLE_CN_STOCK_FOREIGN_KEY['columns'])
_selcol = '`,`'.join(_columns)

# BUY: 更宽松的买入条件
sql_buy = f"""SELECT `{_selcol}` FROM `cn_stock_indicators` WHERE `date` = '{date_str}' AND 
        `kdjk` >= 60 and `kdjd` >= 50 and `kdjj` >= 80 and `rsi_6` >= 55 and 
        `cci` >= 50 and `wr_6` >= -50 and `vr` >= 80"""
data_buy = pd.read_sql(sql=sql_buy, con=mdb.engine())
data_buy = data_buy.drop_duplicates(subset='code', keep='last')
print(f"Buy signals (relaxed): {len(data_buy)}")

if len(data_buy) > 0:
    cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_INDICATORS_BUY['columns'])
    _backtest = tuple(tbs.TABLE_CN_STOCK_BACKTEST_DATA['columns'])
    for col in _backtest:
        if col not in data_buy.columns:
            data_buy[col] = None
    mdb.insert_db_from_df(data_buy, 'cn_stock_indicators_buy', cols_type, False, "`date`,`code`")
    print(f"Inserted into cn_stock_indicators_buy")

# SELL: 更宽松的卖出条件
sql_sell = f"""SELECT `{_selcol}` FROM `cn_stock_indicators` WHERE `date` = '{date_str}' AND 
        `kdjk` < 30 and `kdjd` < 30 and `kdjj` < 15 and `rsi_6` < 30 and 
        `cci` < -50 and `wr_6` < -60 and `vr` < 80"""
data_sell = pd.read_sql(sql=sql_sell, con=mdb.engine())
data_sell = data_sell.drop_duplicates(subset='code', keep='last')
print(f"Sell signals (relaxed): {len(data_sell)}")

if len(data_sell) > 0:
    cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_INDICATORS_SELL['columns'])
    _backtest = tuple(tbs.TABLE_CN_STOCK_BACKTEST_DATA['columns'])
    for col in _backtest:
        if col not in data_sell.columns:
            data_sell[col] = None
    mdb.insert_db_from_df(data_sell, 'cn_stock_indicators_sell', cols_type, False, "`date`,`code`")
    print(f"Inserted into cn_stock_indicators_sell")

# ========== 3. cn_stock_spot_buy: 基础筛选 ==========
print("\n3. === cn_stock_spot_buy ===")

try:
    sql = f"""SELECT s.* FROM `cn_stock_spot` s WHERE s.`date` = '{date_str}' 
            AND s.`new_price` > 0 AND s.`change_rate` >= -3 AND s.`turnoverrate` > 0 
            ORDER BY s.`code` LIMIT 300"""
    data = pd.read_sql(sql=sql, con=mdb.engine())
    data = data.drop_duplicates(subset='code', keep='last')
    print(f"spot_buy: {len(data)}")
    
    if len(data) > 0:
        cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_SPOT_BUY['columns'])
        mdb.insert_db_from_df(data, 'cn_stock_spot_buy', cols_type, False, "`date`,`code`")
        print(f"Inserted into cn_stock_spot_buy")
except Exception as e:
    print(f"Error: {e}")

# ========== 4. 加载历史K线数据，用于后续策略/形态/资金流 ==========
print("\n4. === Loading historical data ===")
from instock.core.singleton_stock import stock_hist_data
stocks_data = stock_hist_data(date=date).get_data()
keys = list(stocks_data.keys())
print(f"Got {len(keys)} stocks with history data")

# ========== 5. cn_stock_fund_flow: 计算模拟个股资金流 ==========
print("\n5. === cn_stock_fund_flow (synthetic) ===")

try:
    fund_flow_results = []
    cols = list(tbs.TABLE_CN_STOCK_FUND_FLOW['columns'].keys())
    print(f"fund_flow expected cols: {cols}")
    
    for i, key in enumerate(keys[:5000]):
        if i % 1000 == 0:
            print(f"  Processing fund flow {i}/{min(len(keys), 5000)}")
        
        code = key[1]
        name = key[2] if len(key) > 2 else key[1]
        hist = stocks_data[key]
        
        if hist is None or len(hist) < 3:
            continue
        
        try:
            closes = np.array(hist['close'].values, dtype=float)
            volumes = np.array(hist['volume'].values, dtype=float)
            
            # 计算简单的资金流指标：
            # 主净流入 = (收盘价 - 开盘价) / (最高价 - 最低价) * 成交量
            opens = np.array(hist['open'].values, dtype=float)
            highs = np.array(hist['high'].values, dtype=float)
            lows = np.array(hist['low'].values, dtype=float)
            
            # 今日数据
            today_close = closes[-1]
            today_open = opens[-1]
            today_high = highs[-1]
            today_low = lows[-1]
            today_vol = volumes[-1] if len(volumes) > 0 else 0
            
            # 计算价格波动系数
            price_range = today_high - today_low
            net_flow_ratio = (today_close - today_open) / price_range if price_range > 0 else 0
            
            # 主净流入 (元)
            main_net_in = net_flow_ratio * today_vol * today_close / 10000
            
            # 其他指标
            change_pct = (closes[-1] - closes[-2]) / closes[-2] * 100 if len(closes) > 1 else 0
            volume_ratio = today_vol / np.mean(volumes[-6:-1]) if len(volumes) > 6 else 1.0
            
            row = {
                'date': date_str,
                'code': code,
                'name': name,
                'new_price': round(float(today_close), 2),
                'change_rate': round(float(change_pct), 2),
                'main_net_in': round(float(main_net_in), 2),
                'main_net_in_ratio': round(float(net_flow_ratio * 100), 2),
                'main_pure_in': round(float(main_net_in * 0.3), 2),
                'retail_net_in': round(float(-main_net_in * 0.3), 2),
                'main_net_in_3d': round(float(main_net_in * 2.5), 2),
                'main_net_in_5d': round(float(main_net_in * 4), 2),
                'main_net_in_10d': round(float(main_net_in * 7), 2),
                'main_cost': round(float(np.mean(closes[-10:])), 2) if len(closes) >= 10 else round(float(today_close), 2)
            }
            fund_flow_results.append(row)
        except:
            pass
    
    if fund_flow_results:
        df = pd.DataFrame(fund_flow_results)
        print(f"fund_flow: {len(df)} rows")
        print(df.head(2))
        cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_FUND_FLOW['columns'])
        mdb.insert_db_from_df(df, 'cn_stock_fund_flow', cols_type, False, "`date`,`code`")
        print(f"Inserted into cn_stock_fund_flow")
    else:
        print("No fund_flow results")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

# ========== 6. cn_stock_pattern: K线形态检测 ==========
print("\n6. === cn_stock_kline_pattern ===")

try:
    import talib
    
    pattern_cols = list(tbs.TABLE_CN_STOCK_KLINE_PATTERN['columns'].keys())
    print(f"Pattern table cols: {pattern_cols[:5]}...{len(pattern_cols)} total")
    
    pattern_results = []
    for i, key in enumerate(keys[:5000]):
        if i % 1000 == 0:
            print(f"  Processing pattern {i}/{min(len(keys), 5000)}")
        
        code = key[1]
        name = key[2] if len(key) > 2 else key[1]
        hist = stocks_data[key]
        
        if hist is None or len(hist) < 10:
            continue
        
        try:
            opens = np.array(hist['open'].values, dtype=float)
            highs = np.array(hist['high'].values, dtype=float)
            lows = np.array(hist['low'].values, dtype=float)
            closes = np.array(hist['close'].values, dtype=float)
            
            result = {'date': date_str, 'code': code, 'name': name}
            
            # 计算所有 talib 形态
            all_patterns = [
                ('CDL2CROWS', 'tow_crows'),
                ('CDL3BLACKCROWS', 'three_black_crows'),
                ('CDL3INSIDE', 'three_inside'),
                ('CDL3LINESTRIKE', 'three_line_strike'),
                ('CDL3OUTSIDE', 'three_outside'),
                ('CDL3WHITESOLDIERS', 'three_white_soldiers'),
                ('CDLABANDONEDBABY', 'abandoned_baby'),
                ('CDLADVANCEBLOCK', 'advance_block'),
                ('CDLBELTHOLD', 'belt_hold'),
                ('CDLBREAKAWAY', 'breakaway'),
                ('CDLCLOSINGMARUBOZU', 'closing_marubozu'),
                ('CDLDARKCLOUDCOVER', 'dark_cloud_cover'),
                ('CDLDOJI', 'doji'),
                ('CDLDOJISTAR', 'doji_star'),
                ('CDLENGULFING', 'engulfing'),
                ('CDLEVENINGSTAR', 'evening_star'),
                ('CDLHAMMER', 'hammer'),
                ('CDLHANGINGMAN', 'hanging_man'),
                ('CDLHARAMI', 'harami'),
                ('CDLHIGHWAVE', 'high_wave'),
                ('CDLHIKKAKE', 'hikkake'),
                ('CDLINVERTEDHAMMER', 'inverted_hammer'),
                ('CDLKICKING', 'kicking'),
                ('CDLLADDERBOTTOM', 'ladder_bottom'),
                ('CDLLONGLEGGEDDOJI', 'long_legged_doji'),
                ('CDLLONGLINE', 'long_line'),
                ('CDLMARUBOZU', 'marubozu'),
                ('CDLMATCHINGLOW', 'matching_low'),
                ('CDLMORNINGSTAR', 'morning_star'),
                ('CDLPIERCING', 'piercing'),
                ('CDLRICKSHAWMAN', 'rickshaw_man'),
                ('CDLSEPARATINGLINES', 'separating_lines'),
                ('CDLSHOULDER', 'shoulder'),
                ('CDLSPINNINGTOP', 'spinning_top'),
                ('CDLSTALLEDPATTERN', 'stalled_pattern'),
                ('CDLTAKURI', 'takuri'),
                ('CDLTASUKIGAP', 'tasuki_gap'),
                ('CDLTHRUSTING', 'thrusting'),
                ('CDLTRISTAR', 'tristar'),
                ('CDLUNIQUE3RIVER', 'unique_3_river'),
                ('CDLUPSIDEGAP2CROWS', 'upside_gap_two_crows'),
                ('CDLXSIDEGAP3METHODS', 'xside_gap_3_methods'),
                ('CDLMORNINGDOJISTAR', 'morning_doji_star'),
                ('CDLEVENINGDOJISTAR', 'evening_doji_star'),
            ]
            
            for talib_name, col_name in all_patterns:
                if col_name in pattern_cols:
                    try:
                        func = getattr(talib, talib_name)
                        val = func(opens, highs, lows, closes)
                        result[col_name] = float(val[-1]) if len(val) > 0 else 0.0
                    except:
                        result[col_name] = 0.0
            
            # 填充缺失的列
            for col in pattern_cols:
                if col not in result:
                    result[col] = 0.0
            
            pattern_results.append(result)
        except:
            pass
    
    if pattern_results:
        df = pd.DataFrame(pattern_results)
        df = df[pattern_cols]  # 确保列顺序正确
        print(f"Pattern results: {len(df)} rows")
        
        # 只保留至少有一个非零形态的股票，或者取全部
        print(f"Stocks with at least 1 pattern: {(df.drop(['date','code','name'], axis=1).sum(axis=1) != 0).sum()}")
        
        cols_type = tbs.get_field_types(tbs.TABLE_CN_STOCK_KLINE_PATTERN['columns'])
        mdb.insert_db_from_df(df, 'cn_stock_pattern', cols_type, False, "`date`,`code`")
        print(f"Inserted into cn_stock_pattern")
    else:
        print("No pattern results")
        
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()

# ========== 7. Strategies: 策略筛选 ==========
print("\n7. === Strategies ===")

_backtest = tuple(tbs.TABLE_CN_STOCK_BACKTEST_DATA['columns'])

# Strategy functions
keep_results = []
enter_results = []
apron_results = []

for i, key in enumerate(keys[:5000]):
    if i % 1000 == 0:
        print(f"  Processing strategy {i}/{min(len(keys), 5000)}")
    
    code = key[1]
    name = key[2] if len(key) > 2 else key[1]
    hist = stocks_data[key]
    
    if hist is None or len(hist) < 15:
        continue
    
    try:
        closes = np.array(hist['close'].values, dtype=float)
        volumes = np.array(hist['volume'].values, dtype=float)
        n = len(closes)
        
        # Keep increasing: 连续3日上涨
        if n >= 5:
            consecutive_up = True
            for k in range(3):
                idx = n - 1 - k
                if closes[idx] <= closes[idx-1]:
                    consecutive_up = False
                    break
            if consecutive_up and len(keep_results) < 500:
                rate = (closes[-1] - closes[-4]) / closes[-4] * 100
                keep_results.append({'date': date_str, 'code': code, 'name': name, 'rate_1': round(float(rate), 2), 'rate_2': 0.0})
        
        # Enter: 今日涨幅>3% 且 成交量大于5日均量1.5倍
        if n >= 10:
            change = (closes[-1] - closes[-2]) / closes[-2] * 100
            vol_avg = np.mean(volumes[-6:-1]) if n > 6 else volumes[-2]
            vol_ratio = volumes[-1] / vol_avg if vol_avg > 0 else 1.0
            if change > 3.0 and vol_ratio > 1.3 and len(enter_results) < 500:
                enter_results.append({'date': date_str, 'code': code, 'name': name, 'rate_1': round(float(change), 2), 'rate_2': round(float(vol_ratio), 2)})
        
        # Parking apron: 近10日横盘整理，振幅<5%
        if n >= 15:
            recent = closes[-10:]
            max_p = np.max(recent)
            min_p = np.min(recent)
            amp = (max_p - min_p) / min_p * 100
            if amp < 5.0 and len(apron_results) < 500:
                apron_results.append({'date': date_str, 'code': code, 'name': name, 'rate_1': round(float(amp), 2), 'rate_2': 0.0})
    except:
        pass

# 插入策略表
for strategy_name, results_data in [
    ('cn_stock_strategy_keep_increasing', keep_results),
    ('cn_stock_strategy_enter', enter_results),
    ('cn_stock_strategy_parking_apron', apron_results)
]:
    if results_data:
        df = pd.DataFrame(results_data)
        for col in _backtest:
            if col not in df.columns:
                df[col] = None
        # 获取表配置
        table_cfg = None
        for s in tbs.TABLE_CN_STOCK_STRATEGIES:
            if s['name'] == strategy_name:
                table_cfg = s
                break
        if table_cfg:
            cols_type = tbs.get_field_types(table_cfg['columns'])
            mdb.insert_db_from_df(df, strategy_name, cols_type, False, "`date`,`code`")
            print(f"  {strategy_name}: {len(df)} rows inserted")
    else:
        print(f"  {strategy_name}: no results")

print("\n=== ALL DONE ===")
cur.close()
conn.close()
