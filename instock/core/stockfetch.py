#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os.path
import datetime
import numpy as np
import pandas as pd
import talib as tl
import instock.core.tablestructure as tbs
import instock.lib.trade_time as trd
import instock.core.crawling.trade_date_hist as tdh
import instock.core.crawling.fund_etf_em as fee
import instock.core.crawling.stock_selection as sst
import instock.core.crawling.stock_lhb_em as sle
import instock.core.crawling.stock_lhb_sina as sls
import instock.core.crawling.stock_dzjy_em as sde
import instock.core.crawling.stock_hist_em as she
import instock.core.crawling.stock_fund_em as sff
import instock.core.crawling.stock_fhps_em as sfe
import instock.core.crawling.stock_chip_race as scr
import instock.core.crawling.stock_limitup_reason as slr
import instock.core.crawling.stock_hist_ts as shts
import instock.core.crawling.stock_spot_sina as sss
import instock.core.crawling.stock_spot_akshare as ssa
import instock.core.tushare_fetcher as tfs

__author__ = 'myh '
__date__ = '2023/3/10 '

# 设置基础目录，每次加载使用。
cpath_current = os.path.dirname(os.path.dirname(__file__))
stock_hist_cache_path = os.path.join(cpath_current, 'cache', 'hist')
if not os.path.exists(stock_hist_cache_path):
    os.makedirs(stock_hist_cache_path)  # 创建多个文件夹结构。


# 600 601 603 605开头的股票是上证A股
# 600开头的股票是上证A股，属于大盘股，其中6006开头的股票是最早上市的股票，
# 6016开头的股票为大盘蓝筹股；900开头的股票是上证B股；
# 688开头的是上证科创板股票；
# 000开头的股票是深证A股，001、002开头的股票也都属于深证A股，
# 其中002开头的股票是深证A股中小企业股票；
# 200开头的股票是深证B股；
# 300、301开头的股票是创业板股票；400开头的股票是三板市场股票。
# 430、83、87开头的股票是北证A股
def is_a_stock(code):
    # 上证A股  # 深证A股
    return code.startswith(('600', '601', '603', '605', '000', '001', '002', '003', '300', '301'))


# 过滤掉 st 股票。
def is_not_st(name):
    return not name.startswith(('*ST', 'ST'))


# 过滤价格，如果没有基本上是退市了。
def is_open(price):
    try:
        return not np.isnan(float(price))
    except (ValueError, TypeError):
        return False


def is_open_with_line(price):
    return price != '-'


# 读取股票交易日历数据
def fetch_stocks_trade_date():
    try:
        data = tdh.tool_trade_date_hist_sina()
        if data is not None and len(data.index) > 0:
            return set(data['trade_date'].values.tolist())
        logging.info("新浪交易日历返回空，尝试使用 tushare 作为补充数据源")
    except Exception as e:
        logging.warning(f"stockfetch.fetch_stocks_trade_date 新浪调用异常：{e}")

    # 回落到 tushare（若已配置）
    try:
        if not tfs.is_enabled():
            return None
        data = shts.tool_trade_date_hist_ts()
        if data is None or len(data.index) == 0:
            return None
        return set(data['trade_date'].values.tolist())
    except Exception as e:
        logging.error(f"stockfetch.fetch_stocks_trade_date tushare 处理异常：{e}")
    return None


def _ts_hist_to_em_columns(df):
    """把 stock_zh_a_hist_ts 返回的中文字段重命名为 CN_STOCK_HIST_DATA 的英文字段名。"""
    if df is None or df.empty:
        return df
    df = df.copy()
    df.rename(columns={
        '日期': 'date',
        '开盘': 'open',
        '收盘': 'close',
        '最高': 'high',
        '最低': 'low',
        '成交量': 'volume',
        '成交额': 'amount',
        '振幅': 'amplitude',
        '涨跌幅': 'quote_change',
        '涨跌额': 'ups_downs',
        '换手率': 'turnover',
    }, inplace=True)
    return df


# 读取当天ETF基金数据
def fetch_etfs(date):
    # 处理日期格式
    if isinstance(date, str):
        date_str = date
    elif date is None:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    else:
        date_str = date.strftime("%Y-%m-%d")
    
    # 1) 优先使用 AKShare ETF接口
    try:
        data = ssa.fund_etf_spot_ak()
        if data is not None and len(data.index) > 0:
            data.insert(0, 'date', date_str)
            # 先插入 date 列（此时 15 列），再设置列名（15 列），避免长度不匹配
            data.columns = list(tbs.TABLE_CN_ETF_SPOT['columns'])
            data = data.loc[data['new_price'].apply(is_open)]
            logging.info(f"fetch_etfs: AKShare ETF获取成功 {len(data)} 条")
            return data
        logging.warning("fetch_etfs: AKShare ETF获取失败，尝试东方财富")
    except Exception as e:
        logging.warning(f"stockfetch.fetch_etfs AKShare异常：{e}")

    # 2) 回落到东方财富 ETF
    try:
        data = fee.fund_etf_spot_em()
        if data is None or len(data.index) == 0:
            return None
        data.insert(0, 'date', date_str)
        data.columns = list(tbs.TABLE_CN_ETF_SPOT['columns'])
        data = data.loc[data['new_price'].apply(is_open)]
        logging.info(f"fetch_etfs: 东方财富 ETF获取成功 {len(data)} 条")
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_etfs处理异常：{e}")
    return None


# 检查数据有效性：至少有 50% 的股票有非零价格
def _check_spot_data_valid(data):
    if data is None or len(data) == 0:
        return False
    try:
        if 'new_price' in data.columns:
            valid_count = data['new_price'].apply(lambda x: float(x) > 0 if pd.notna(x) else False).sum()
            valid_ratio = valid_count / len(data)
            return valid_ratio > 0.5
    except:
        pass
    return False


# 使用 Tushare 抓取当日股票行情数据（优先推荐：稳定、字段全）
def _fetch_stocks_tushare(date):
    """通过 Tushare 的 daily + daily_basic + stock_basic 获取当日全量行情数据"""
    fetcher = tfs.get_fetcher()
    if not fetcher or not getattr(fetcher, 'enabled', False):
        return None

    # 处理日期格式
    if isinstance(date, str):
        date_str = date.replace('-', '')
        display_date = date if '-' in date else f'{date[:4]}-{date[4:6]}-{date[6:8]}'
    elif date:
        date_str = date.strftime('%Y%m%d')
        display_date = date.strftime('%Y-%m-%d')
    else:
        date_str = datetime.datetime.now().strftime('%Y%m%d')
        display_date = datetime.datetime.now().strftime('%Y-%m-%d')

    try:
        # 1) 日线行情：open/high/low/close/pre_close/change/pct_chg/vol/amount
        daily_df = fetcher.call('daily', trade_date=date_str)
        if daily_df is None or daily_df.empty:
            logging.warning(f"fetch_stocks(tushare): daily 无数据 ({date_str})")
            return None

        # 2) 每日指标：turnover_rate/volume_ratio/pe/pe_ttm/pb/total_mv/circ_mv
        basic_df = fetcher.call('daily_basic', trade_date=date_str)
        if basic_df is None or basic_df.empty:
            basic_df = pd.DataFrame(columns=['ts_code'])

        # 3) 股票基础信息：name/industry/list_date
        info_df = fetcher.call('stock_basic')
        if info_df is None or info_df.empty:
            info_df = pd.DataFrame(columns=['ts_code', 'name', 'industry', 'list_date'])

        # 合并
        df = daily_df.merge(basic_df, on='ts_code', how='left', suffixes=('', '_basic'))
        df = df.merge(info_df, on='ts_code', how='left')

        # ts_code 转 6 位代码（如 "000001.SZ" → "000001"）
        df['code'] = df['ts_code'].astype(str).str[:6]

        # 过滤非 A 股（6 位数字代码）
        df = df[df['code'].str.match(r'^\d{6}$')]

        # 构建结果 DataFrame，按 TABLE_CN_STOCK_SPOT 的列顺序
        required_cols = list(tbs.TABLE_CN_STOCK_SPOT['columns'].keys())

        # 计算派生字段
        pre_close_safe = df['pre_close'].replace(0, np.nan)
        amplitude = ((df['high'] - df['low']) / pre_close_safe * 100).round(2)
        list_date_formatted = df.get('list_date', '').apply(
            lambda x: f"{str(x)[:4]}-{str(x)[4:6]}-{str(x)[6:8]}"
            if pd.notna(x) and len(str(x)) == 8 and str(x).isdigit() else None
        )

        # 用字典方式构建 DataFrame，避免索引对齐问题
        out = {
            'date': display_date,
            'code': df['code'].values,
            'name': df.get('name', '').fillna('').values,
            'new_price': df['close'].values,
            'change_rate': df['pct_chg'].values,
            'ups_downs': df['change'].values,
            # tushare vol 单位是"手"（100股/手），转为股
            'volume': (df['vol'].fillna(0) * 100).values.astype(np.int64),
            # tushare amount 单位是"千元"，转为元
            'deal_amount': (df['amount'].fillna(0) * 1000).values.astype(np.int64),
            'amplitude': amplitude.values,
            'turnoverrate': df.get('turnover_rate', 0).fillna(0).values,
            'volume_ratio': df.get('volume_ratio', 0).fillna(0).values,
            'open_price': df['open'].values,
            'high_price': df['high'].values,
            'low_price': df['low'].values,
            'pre_close_price': df['pre_close'].values,
            'speed_increase': 0.0,
            'speed_increase_5': 0.0,
            'speed_increase_60': 0.0,
            'speed_increase_all': 0.0,
            'dtsyl': df.get('pe', 0).fillna(0).values,
            'pe9': df.get('pe_ttm', 0).fillna(0).values,
            'pe': df.get('pe', 0).fillna(0).values,
            'pbnewmrq': df.get('pb', 0).fillna(0).values,
            'basic_eps': 0,
            'bvps': 0,
            'per_capital_reserve': 0,
            'per_unassign_profit': 0,
            'roe_weight': 0,
            'sale_gpr': 0,
            'debt_asset_ratio': 0,
            'total_operate_income': 0,
            'toi_yoy_ratio': 0,
            'parent_netprofit': 0,
            'netprofit_yoy_ratio': 0,
            'report_date': None,
            # tushare total_share 单位是"万股"，转为股
            'total_shares': (df.get('total_share', 0).fillna(0) * 10000).values.astype(np.int64),
            'free_shares': (df.get('free_share', 0).fillna(0) * 10000).values.astype(np.int64),
            # tushare total_mv 单位是"千元"，转为元
            'total_market_cap': (df.get('total_mv', 0).fillna(0) * 1000).values.astype(np.int64),
            'free_cap': (df.get('circ_mv', 0).fillna(0) * 1000).values.astype(np.int64),
            'industry': df.get('industry', '').fillna('').values,
            'listing_date': list_date_formatted.values,
        }
        result = pd.DataFrame(out)

        # 调整列顺序并过滤
        result = result[required_cols]
        # 过滤停牌股票（new_price 为 0 或 NaN）
        result = result.loc[result['new_price'].apply(lambda x: pd.notna(x) and float(x) > 0)]
        result = result.loc[result['code'].apply(is_a_stock)]

        logging.info(f"fetch_stocks: Tushare 行情获取成功 {len(result)} 条")
        return result
    except Exception as e:
        logging.error(f"fetch_stocks(tushare) 处理异常：{e}")
        return None


# 读取当天股票数据
def fetch_stocks(date):
    # 处理日期格式
    if isinstance(date, str):
        date_str = date
    elif date is None:
        date_str = datetime.datetime.now().strftime("%Y-%m-%d")
    else:
        date_str = date.strftime("%Y-%m-%d")
    
    # 0) 优先使用 Tushare（最稳定，字段最全）
    try:
        data = _fetch_stocks_tushare(date)
        if data is not None and len(data) > 0:
            if _check_spot_data_valid(data):
                logging.info(f"fetch_stocks: Tushare 成功 {len(data)} 条")
                return data
            else:
                logging.warning("fetch_stocks: Tushare 数据无效，尝试其他数据源")
    except Exception as e:
        logging.warning(f"stockfetch.fetch_stocks Tushare 异常：{e}")

    # 1) 优先使用新浪实时行情
    try:
        data = sss.stock_zh_a_spot_sina()
        if data is not None and len(data.index) > 0:
            # 检查数据有效性
            if not _check_spot_data_valid(data):
                logging.warning("fetch_stocks: 新浪实时行情数据无效(全0)，尝试 AKShare")
            else:
                data.insert(0, 'date', date_str)
                # 填充缺失的列为 0（新浪数据源字段较少）
                required_cols = list(tbs.TABLE_CN_STOCK_SPOT['columns'].keys())
                for col in required_cols:
                    if col not in data.columns:
                        data[col] = 0
                # 调整列顺序以匹配表结构
                data = data[required_cols]
                data = data.loc[data['code'].apply(is_a_stock)].loc[data['new_price'].apply(is_open)]
                logging.info(f"fetch_stocks: 新浪实时行情获取成功 {len(data)} 条")
                return data
        logging.warning("fetch_stocks: 新浪实时行情获取失败，尝试 AKShare")
    except Exception as e:
        logging.warning(f"stockfetch.fetch_stocks 新浪异常：{e}")

    # 2) 回落到 AKShare 实时行情（使用 curl_cffi 绕过反爬，最稳定）
    try:
        data = ssa.stock_zh_a_spot_ak()
        if data is not None and len(data.index) > 0:
            data.insert(0, 'date', date_str)
            # 填充缺失的列为 0（AKShare 数据源字段可能较少）
            required_cols = list(tbs.TABLE_CN_STOCK_SPOT['columns'].keys())
            for col in required_cols:
                if col not in data.columns:
                    data[col] = 0
            data = data[required_cols]
            data = data.loc[data['code'].apply(is_a_stock)].loc[data['new_price'].apply(is_open)]
            logging.info(f"fetch_stocks: AKShare 实时行情获取成功 {len(data)} 条")
            return data
        logging.warning("fetch_stocks: AKShare 实时行情获取失败，尝试东方财富")
    except Exception as e:
        logging.warning(f"stockfetch.fetch_stocks AKShare 异常：{e}")

    # 3) 最后回落到东方财富实时行情（东财 API 目前被封禁，优先使用前两个数据源）
    try:
        data = she.stock_zh_a_spot_em()
        if data is not None and len(data.index) > 0:
            data.insert(0, 'date', date_str)
            data.columns = list(tbs.TABLE_CN_STOCK_SPOT['columns'])
            data = data.loc[data['code'].apply(is_a_stock)].loc[data['new_price'].apply(is_open)]
            logging.info(f"fetch_stocks: 东方财富实时行情获取成功 {len(data)} 条")
            return data
        logging.error("fetch_stocks: 东方财富实时行情获取失败，所有数据源均不可用")
    except Exception as e:
        logging.error(f"stockfetch.fetch_stocks 东方财富异常：{e}")

    return None


def fetch_stock_selection():
    try:
        data = sst.stock_selection()
        if data is None or len(data.index) == 0:
            return None
        data.columns = list(tbs.TABLE_CN_STOCK_SELECTION['columns'])
        data.drop_duplicates('code', keep='last', inplace=True)
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stocks_selection处理异常：{e}")
    return None


# 使用 Tushare 获取个股资金流向（优先数据源）
def _fetch_stocks_fund_flow_tushare(trade_date):
    """通过 Tushare moneyflow 接口获取个股资金流向
    
    Args:
        trade_date: 交易日期，格式 YYYYMMDD 或 datetime.date
        
    Returns:
        DataFrame 或 None
    """
    fetcher = tfs.get_fetcher()
    if not fetcher or not getattr(fetcher, 'enabled', False):
        return None
    
    # 处理日期格式
    if isinstance(trade_date, str):
        date_str = trade_date.replace('-', '')
    else:
        date_str = trade_date.strftime('%Y%m%d')
    
    try:
        # 获取资金流向数据
        mf_df = fetcher.moneyflow(trade_date=date_str)
        if mf_df is None or mf_df.empty:
            logging.warning(f"_fetch_stocks_fund_flow_tushare: moneyflow 无数据 ({date_str})")
            return None
        
        # 获取当日行情数据（用于补充最新价、涨跌幅）
        daily_df = fetcher.call('daily', trade_date=date_str)
        if daily_df is None or daily_df.empty:
            daily_df = pd.DataFrame(columns=['ts_code', 'close', 'pct_chg'])
        
        # 获取股票名称
        info_df = fetcher.call('stock_basic', list_status='L')
        if info_df is None or info_df.empty:
            info_df = pd.DataFrame(columns=['ts_code', 'name'])
        
        # 合并数据
        df = mf_df.merge(daily_df[['ts_code', 'close', 'pct_chg']], on='ts_code', how='left')
        df = df.merge(info_df[['ts_code', 'name']], on='ts_code', how='left')
        
        # ts_code 转 6 位代码
        df['code'] = df['ts_code'].astype(str).str[:6]
        
        # 过滤 A 股
        df = df[df['code'].str.match(r'^\d{6}$')]
        
        # 计算主力净流入（大单 + 特大单）
        # Tushare 单位：手（成交量）、万元（金额）
        # 东财单位：股（成交量）、元（金额）
        # 转换：手→股（乘100），万元→元（乘10000）
        
        # 特大单（东财叫"超大单"）
        buy_elg_vol = df['buy_elg_vol'].fillna(0) * 100  # 手→股
        sell_elg_vol = df['sell_elg_vol'].fillna(0) * 100
        buy_elg_amount = df['buy_elg_amount'].fillna(0) * 10000  # 万元→元
        sell_elg_amount = df['sell_elg_amount'].fillna(0) * 10000
        
        # 大单
        buy_lg_vol = df['buy_lg_vol'].fillna(0) * 100
        sell_lg_vol = df['sell_lg_vol'].fillna(0) * 100
        buy_lg_amount = df['buy_lg_amount'].fillna(0) * 10000
        sell_lg_amount = df['sell_lg_amount'].fillna(0) * 10000
        
        # 中单
        buy_md_vol = df['buy_md_vol'].fillna(0) * 100
        sell_md_vol = df['sell_md_vol'].fillna(0) * 100
        buy_md_amount = df['buy_md_amount'].fillna(0) * 10000
        sell_md_amount = df['sell_md_amount'].fillna(0) * 10000
        
        # 小单
        buy_sm_vol = df['buy_sm_vol'].fillna(0) * 100
        sell_sm_vol = df['sell_sm_vol'].fillna(0) * 100
        buy_sm_amount = df['buy_sm_amount'].fillna(0) * 10000
        sell_sm_amount = df['sell_sm_amount'].fillna(0) * 10000
        
        # 计算净流入
        net_elg_amount = buy_elg_amount - sell_elg_amount  # 超大单净流入
        net_lg_amount = buy_lg_amount - sell_lg_amount    # 大单净流入
        net_md_amount = buy_md_amount - sell_md_amount    # 中单净流入
        net_sm_amount = buy_sm_amount - sell_sm_amount    # 小单净流入
        
        # 主力净流入 = 大单 + 特大单
        net_mf_amount = net_elg_amount + net_lg_amount
        
        # 计算成交总额（用于计算净占比）
        total_amount = buy_elg_amount + sell_elg_amount + \
                       buy_lg_amount + sell_lg_amount + \
                       buy_md_amount + sell_md_amount + \
                       buy_sm_amount + sell_sm_amount
        
        # 计算净占比
        fund_rate = np.where(total_amount > 0, net_mf_amount / total_amount * 100, 0)
        fund_rate_super = np.where(total_amount > 0, net_elg_amount / total_amount * 100, 0)
        fund_rate_large = np.where(total_amount > 0, net_lg_amount / total_amount * 100, 0)
        fund_rate_medium = np.where(total_amount > 0, net_md_amount / total_amount * 100, 0)
        fund_rate_small = np.where(total_amount > 0, net_sm_amount / total_amount * 100, 0)
        
        # 构建结果 DataFrame（今日指标，index=0）
        result = pd.DataFrame({
            'code': df['code'].values,
            'name': df.get('name', '').fillna('').values,
            'new_price': df.get('close', 0).fillna(0).values,
            'change_rate': df.get('pct_chg', 0).fillna(0).values,
            'fund_amount': net_mf_amount.values.astype(np.int64),
            'fund_rate': fund_rate.round(2),
            'fund_amount_super': net_elg_amount.values.astype(np.int64),
            'fund_rate_super': fund_rate_super.round(2),
            'fund_amount_large': net_lg_amount.values.astype(np.int64),
            'fund_rate_large': fund_rate_large.round(2),
            'fund_amount_medium': net_md_amount.values.astype(np.int64),
            'fund_rate_medium': fund_rate_medium.round(2),
            'fund_amount_small': net_sm_amount.values.astype(np.int64),
            'fund_rate_small': fund_rate_small.round(2),
        })
        
        logging.info(f"fetch_stocks_fund_flow: Tushare 获取成功 {len(result)} 条")
        return result
        
    except Exception as e:
        logging.error(f"_fetch_stocks_fund_flow_tushare 处理异常：{e}")
        return None


# 读取股票资金流向
def fetch_stocks_fund_flow(index):
    """获取股票资金流向数据
    
    Args:
        index: 时间段索引（0=今日, 1=3日, 2=5日, 3=10日）
        
    Note:
        Tushare moneyflow 接口只提供当日数据，不支持 3/5/10 日汇总。
        对于 index > 0，只能回落到东方财富接口。
    """
    # 对于今日数据，优先使用 Tushare
    if index == 0:
        try:
            today = datetime.date.today()
            data = _fetch_stocks_fund_flow_tushare(today)
            if data is not None and len(data) > 0:
                return data
            logging.warning("fetch_stocks_fund_flow: Tushare 无数据，回落东方财富")
        except Exception as e:
            logging.warning(f"fetch_stocks_fund_flow: Tushare 异常 {e}，回落东方财富")
    
    # 回落到东方财富接口
    try:
        cn_flow = tbs.CN_STOCK_FUND_FLOW[index]
        data = sff.stock_individual_fund_flow_rank(indicator=cn_flow['cn'])
        if data is None or len(data.index) == 0:
            return None
        data.columns = list(cn_flow['columns'])
        data = data.loc[data['code'].apply(is_a_stock)].loc[data['new_price'].apply(is_open_with_line)]
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stocks_fund_flow处理异常：{e}")
    return None


# 读取板块资金流向
def fetch_stocks_sector_fund_flow(index_sector, index_indicator):
    try:
        cn_flow = tbs.CN_STOCK_SECTOR_FUND_FLOW[1][index_indicator]
        data = sff.stock_sector_fund_flow_rank(indicator=cn_flow['cn'], sector_type=tbs.CN_STOCK_SECTOR_FUND_FLOW[0][index_sector])
        if data is None or len(data.index) == 0:
            return None
        data.columns = list(cn_flow['columns'])
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stocks_sector_fund_flow处理异常：{e}")
    return None


# 读取股票分红配送
def fetch_stocks_bonus(date):
    try:
        data = sfe.stock_fhps_em(date=trd.get_bonus_report_date())
        if data is None or len(data.index) == 0:
            return None
        if date is None:
            data.insert(0, 'date', datetime.datetime.now().strftime("%Y-%m-%d"))
        elif isinstance(date, str):
            data.insert(0, 'date', date)
        else:
            data.insert(0, 'date', date.strftime("%Y-%m-%d"))
        data.columns = list(tbs.TABLE_CN_STOCK_BONUS['columns'])
        data = data.loc[data['code'].apply(is_a_stock)]
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stocks_bonus处理异常：{e}")
    return None


# 股票近三月上龙虎榜且必须有2次以上机构参与的
def fetch_stock_top_entity_data(date):
    try:
        if isinstance(date, str):
            date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
        else:
            date_obj = date
        run_date = date_obj + datetime.timedelta(days=-90)
        start_date = run_date.strftime("%Y%m%d")
        end_date = date_obj.strftime("%Y%m%d")
        code_name = '代码'
        entity_amount_name = '买方机构数'
        data = sle.stock_lhb_jgmmtj_em(start_date, end_date)
        if data is None or len(data.index) == 0:
            return None

        # 机构买入次数大于1计算方法，首先：每次要有买方机构数(>0),然后：这段时间买方机构数求和大于1
        mask = (data[entity_amount_name] > 0)  # 首先：每次要有买方机构数(>0)
        data = data.loc[mask]

        if len(data.index) == 0:
            return None

        grouped = data.groupby(by=data[code_name])
        data_series = grouped[entity_amount_name].sum()
        data_code = set(data_series[data_series > 1].index.values)  # 然后：这段时间买方机构数求和大于1

        if not data_code:
            return None

        return data_code
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_top_entity_data处理异常：{e}")
    return None

# 使用 Tushare 获取龙虎榜数据
def _fetch_stock_lhb_data_tushare(trade_date):
    """通过 Tushare top_list 接口获取龙虎榜数据
    
    Args:
        trade_date: 交易日期，格式 YYYYMMDD 或 datetime.date 或字符串
        
    Returns:
        DataFrame 或 None
    """
    fetcher = tfs.get_fetcher()
    if not fetcher or not getattr(fetcher, 'enabled', False):
        return None
    
    # 处理日期格式
    if isinstance(trade_date, str):
        date_str = trade_date.replace('-', '')
    else:
        date_str = trade_date.strftime('%Y%m%d')
    
    try:
        df = fetcher.top_list(trade_date=date_str)
        if df is None or df.empty:
            logging.warning(f"_fetch_stock_lhb_data_tushare: top_list 无数据 ({date_str})")
            return None
        
        # ts_code 转 6 位代码
        df['code'] = df['ts_code'].astype(str).str[:6]
        
        # 过滤 A 股
        df = df[df['code'].str.match(r'^\d{6}$')]
        
        # 字段映射：Tushare -> 东财格式
        result = pd.DataFrame({
            'date': date_str[:4] + '-' + date_str[4:6] + '-' + date_str[6:8],
            'code': df['code'].values,
            'name': df['name'].values,
            'ranking_times': date_str[:4] + '-' + date_str[4:6] + '-' + date_str[6:8],  # 上榜日
            'interpret': df['reason'].fillna('').values,  # 上榜原因作为解读
            'new_price': df['close'].fillna(0).values,
            'change_rate': df['pct_change'].fillna(0).values,
            'net_amount_buy': df['net_amount'].fillna(0).values * 10000,  # 万元 -> 元
            'sum_buy': df['l_buy'].fillna(0).values * 10000,  # 万元 -> 元
            'sum_sell': df['l_sell'].fillna(0).values * 10000,  # 万元 -> 元
            'lhb_amount': df['l_amount'].fillna(0).values * 10000,  # 万元 -> 元
            'market_amount': df['float_values'].fillna(0).values * 10000,  # 万元 -> 元
            'net_amount_rate': df['net_rate'].fillna(0).values,
            'sum_rate': df['amount_rate'].fillna(0).values,
            'turnoverrate': df['turnover_rate'].fillna(0).values,
        })
        
        logging.info(f"_fetch_stock_lhb_data_tushare: 成功 {len(result)} 条")
        return result
        
    except Exception as e:
        logging.error(f"_fetch_stock_lhb_data_tushare 处理异常：{e}")
        return None


# 描述: 获取东方财富-龙虎榜-个股上榜统计
def fetch_stock_lhb_data(date,count=12):
    """获取龙虎榜数据
    
    Args:
        date: 交易日期
        count: 回溯交易日数（默认12天）
        
    Note:
        优先使用 Tushare，失败则回落到东方财富接口
    """
    # 优先使用 Tushare
    try:
        data = _fetch_stock_lhb_data_tushare(date)
        if data is not None and len(data) > 0:
            return data
        logging.warning("fetch_stock_lhb_data: Tushare 无数据，回落东方财富")
    except Exception as e:
        logging.warning(f"fetch_stock_lhb_data: Tushare 异常 {e}，回落东方财富")
    
    # 回落到东方财富接口
    try:
        if isinstance(date, str):
            date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
        else:
            date_obj = date
        start_date = trd.get_previous_trade_date(date_obj,count).strftime("%Y%m%d")
        end_date = date_obj.strftime("%Y%m%d")

        data = sle.stock_lhb_detail_em(start_date, end_date)
        if data is None or len(data.index) == 0:
            return None
        _columns = list(tbs.TABLE_CN_STOCK_lHB['columns'])
        _columns.pop(0)
        data.columns = _columns
        data = data.loc[data['code'].apply(is_a_stock)]
        data.drop_duplicates('code', keep='last', inplace=True)
        if date is None:
            data.insert(0, 'date', datetime.datetime.now().strftime("%Y-%m-%d"))
        elif isinstance(date, str):
            data.insert(0, 'date', date)
        else:
            data.insert(0, 'date', date.strftime("%Y-%m-%d"))
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_lhb_data处理异常：{e}")
    return None

# 描述: 获取新浪财经-龙虎榜-个股上榜统计
def fetch_stock_top_data(date):
    """获取龙虎榜数据（新浪格式）- 累计上榜统计
    
    Note:
        新浪龙虎榜是累计统计，需要使用新浪接口
    """
    try:
        data = sls.stock_lhb_ggtj_sina()
        if data is None or len(data.index) == 0:
            return None
        _columns = list(tbs.TABLE_CN_STOCK_TOP['columns'])
        _columns.pop(0)
        data.columns = _columns
        data = data.loc[data['code'].apply(is_a_stock)]
        data.drop_duplicates('code', keep='last', inplace=True)
        if date is None:
            data.insert(0, 'date', datetime.datetime.now().strftime("%Y-%m-%d"))
        elif isinstance(date, str):
            data.insert(0, 'date', date)
        else:
            data.insert(0, 'date', date.strftime("%Y-%m-%d"))
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_top_data处理异常：{e}")
    return None


# 描述: 获取东方财富网-数据中心-大宗交易-每日统计
def fetch_stock_blocktrade_data(date):
    try:
        if isinstance(date, str):
            date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
        else:
            date_obj = date
        date_str = date_obj.strftime("%Y%m%d")
        data = sde.stock_dzjy_mrtj(start_date=date_str, end_date=date_str)
        if data is None or len(data.index) == 0:
            return None

        columns = list(tbs.TABLE_CN_STOCK_BLOCKTRADE['columns'])
        columns.insert(0, 'index')
        data.columns = columns
        data = data.loc[data['code'].apply(is_a_stock)]
        data.drop('index', axis=1, inplace=True)
        return data
    except TypeError:
        logging.error("处理异常：目前还没有大宗交易数据，请17:00点后再获取！")
        return None
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_blocktrade_data处理异常：{e}")
    return None

# 读取早盘抢筹
def fetch_stock_chip_race_open(date):
    try:
        today = datetime.datetime.now().date()
        date_str = ""
        display_date = today.strftime("%Y-%m-%d")
        
        if date is not None:
            if isinstance(date, str):
                display_date = date
                date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
                if date_obj != today:
                    date_str = date.replace("-", "")
            else:
                display_date = date.strftime("%Y-%m-%d")
                if date != today:
                    date_str = date.strftime("%Y%m%d")
        
        data = scr.stock_chip_race_open(date_str)
        if data is None or len(data.index) == 0:
            return None
        
        data.insert(0, 'date', display_date)
        data.columns = list(tbs.TABLE_CN_STOCK_CHIP_RACE_OPEN['columns'])
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_chip_race_open处理异常：{e}")
    return None

# 读取尾盘抢筹
def fetch_stock_chip_race_end(date):
    try:
        today = datetime.datetime.now().date()
        date_str = ""
        display_date = today.strftime("%Y-%m-%d")
        
        if date is not None:
            if isinstance(date, str):
                display_date = date
                date_obj = datetime.datetime.strptime(date, "%Y-%m-%d").date()
                if date_obj != today:
                    date_str = date.replace("-", "")
            else:
                display_date = date.strftime("%Y-%m-%d")
                if date != today:
                    date_str = date.strftime("%Y%m%d")
        
        data = scr.stock_chip_race_end(date_str)
        if data is None or len(data.index) == 0:
            return None
        
        data.insert(0, 'date', display_date)
        data.columns = list(tbs.TABLE_CN_STOCK_CHIP_RACE_END['columns'])
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_chip_race_end处理异常：{e}")
    return None

# 读取涨停原因
def fetch_stock_limitup_reason(date):
    try:
        if isinstance(date, str):
            date_str = date
        else:
            date_str = date.strftime("%Y-%m-%d")
        data = slr.stock_limitup_reason(date_str)
        if data is None or len(data.index) == 0:
            return None
        data.columns = list(tbs.TABLE_CN_STOCK_LIMITUP_REASON['columns'])
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_limitup_reason处理异常：{e}")
    return None

# 读取股票历史数据
def fetch_etf_hist(data_base, date_start=None, date_end=None, adjust='qfq'):
    date = data_base[0]
    code = data_base[1]

    if date_start is None:
        date_start, is_cache = trd.get_trade_hist_interval(date)  # 提高运行效率，只运行一次
    try:
        if date_end is not None:
            data = fee.fund_etf_hist_em(symbol=code, period="daily", start_date=date_start, end_date=date_end,
                                        adjust=adjust)
        else:
            data = fee.fund_etf_hist_em(symbol=code, period="daily", start_date=date_start, adjust=adjust)

        if data is None or len(data.index) == 0:
            return None
        data.columns = tuple(tbs.CN_STOCK_HIST_DATA['columns'])
        data = data.sort_index()  # 将数据按照日期排序下。
        if data is not None:
            data.loc[:, 'p_change'] = tl.ROC(data['close'].values, 1)
            data['p_change'].values[np.isnan(data['p_change'].values)] = 0.0
            data["volume"] = data['volume'].values.astype('double') * 100  # 成交量单位从手变成股。
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_etf_hist处理异常：{e}")
    return None


# 读取股票历史数据
def fetch_stock_hist(data_base, date_start=None, is_cache=True):
    date = data_base[0]
    code = data_base[1]

    if date_start is None:
        date_start, is_cache = trd.get_trade_hist_interval(date)  # 提高运行效率，只运行一次
        # date_end = date_end.strftime("%Y%m%d")
    try:
        data = stock_hist_cache(code, date_start, None, is_cache, 'qfq')
        if data is not None:
            data.loc[:, 'p_change'] = tl.ROC(data['close'].values, 1)
            data['p_change'].values[np.isnan(data['p_change'].values)] = 0.0
            data["volume"] = data['volume'].values.astype('double') * 100  # 成交量单位从手变成股。
        return data
    except Exception as e:
        logging.error(f"stockfetch.fetch_stock_hist处理异常：{e}")
    return None


# 增加读取股票缓存方法。加快处理速度。多线程解决效率
def stock_hist_cache(code, date_start, date_end=None, is_cache=True, adjust=''):
    cache_dir = os.path.join(stock_hist_cache_path, date_start[0:6], date_start)
    # 如果没有文件夹创建一个。月文件夹和日文件夹。方便删除。
    try:
        if not os.path.exists(cache_dir):
            os.makedirs(cache_dir)
    except Exception:
        pass
    cache_file = os.path.join(cache_dir, "%s%s.gzip.pickle" % (code, adjust))
    # 如果缓存存在就直接返回缓存数据。压缩方式。
    try:
        if os.path.isfile(cache_file):
            return pd.read_pickle(cache_file, compression="gzip")
        else:
            # 1. 优先使用新浪接口 (ak.stock_zh_a_daily) —— 东财被封后最稳定的接口
            if date_end is not None:
                stock = ssa.stock_zh_a_hist_ak_sina(
                    symbol=code, period="daily",
                    start_date=date_start, end_date=date_end,
                    adjust=adjust if adjust else "qfq"
                )
            else:
                stock = ssa.stock_zh_a_hist_ak_sina(
                    symbol=code, period="daily",
                    start_date=date_start,
                    adjust=adjust if adjust else "qfq"
                )

            # 2. 新浪接口失败时回落到 AKShare curl_cffi（如东财接口恢复）
            if stock is None or len(stock.index) == 0:
                try:
                    logging.info(f"{code} 新浪历史K线无数据，回落 AKShare")
                    stock = ssa.stock_zh_a_hist_ak(
                        symbol=code, period="daily",
                        start_date=date_start,
                        end_date=date_end if date_end else None,
                        adjust=adjust if adjust else "qfq"
                    )
                except Exception as e:
                    logging.warning(f"{code} AKShare 回退获取失败: {e}")

            # 3. AKShare 失败时回落到 tushare（若已配置）
            if (stock is None or len(stock.index) == 0) and tfs.is_enabled():
                try:
                    logging.info(f"{code} AKShare 无数据，回落到 tushare 获取日行情")
                    stock_raw = shts.stock_zh_a_hist_ts(
                        symbol=code,
                        start_date=date_start,
                        end_date=date_end if date_end else datetime.date.today().strftime("%Y%m%d"),
                    )
                    stock = _ts_hist_to_em_columns(stock_raw)
                except Exception as e:
                    logging.warning(f"{code} tushare 回退获取失败: {e}")

            # 4. 最后回落到东方财富（东财 API 目前被封）
            if stock is None or len(stock.index) == 0:
                try:
                    logging.info(f"{code} 无数据，回落到东方财富获取日行情")
                    stock_raw = she.stock_zh_a_hist(
                        symbol=code, period="daily",
                        start_date=date_start,
                        end_date=date_end if date_end else None,
                        adjust=adjust
                    )
                    if stock_raw is not None and not stock_raw.empty:
                        stock = stock_raw
                except Exception as e:
                    logging.warning(f"{code} 东方财富回退获取失败: {e}")

            if stock is None or len(stock.index) == 0:
                return None
            stock.columns = tuple(tbs.CN_STOCK_HIST_DATA['columns'])
            stock = stock.sort_index()  # 将数据按照日期排序下。
            try:
                if is_cache:
                    stock.to_pickle(cache_file, compression="gzip")
            except Exception:
                pass
            return stock
    except Exception as e:
        logging.error(f"stockfetch.stock_hist_cache处理异常：{code}代码{e}")
    return None
