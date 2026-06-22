#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Date: 2026-06-21
Desc: AKShare A股实时行情数据
基于 AKShare 库获取沪深京A股实时行情，支持 curl_cffi 绕过反爬
"""

import logging
import time
import pandas as pd

__author__ = 'myh'
__date__ = '2026-06-21'

# 全局 AKShare 实例（延迟初始化）
_ak = None


def _get_akshare():
    """获取或初始化 AKShare 实例（单例模式）"""
    global _ak
    if _ak is not None:
        return _ak

    try:
        import akshare as ak
        _ak = ak
        logging.info("AKShare 初始化成功")
        return _ak
    except ImportError:
        logging.error("AKShare 未安装，请执行: pip install akshare")
        return None
    except Exception as e:
        logging.error(f"AKShare 初始化失败: {e}")
        return None


def stock_zh_a_spot_ak() -> pd.DataFrame:
    """
    使用 AKShare 获取沪深京A股实时行情（优先新浪，失败回落到东方财富）
    :return: 实时行情 DataFrame
    """
    ak = _get_akshare()
    if ak is None:
        return pd.DataFrame()

    # 尝试 AKShare 的 stock_zh_a_spot()（使用新浪接口，更稳定）
    try:
        df = ak.stock_zh_a_spot()
        if df is not None and not df.empty:
            logging.info(f"AKShare 新浪接口获取成功: {len(df)} 条")
            return _normalize_akshare_spot(df)
    except Exception as e:
        logging.warning(f"AKShare 新浪接口失败: {e}")

    # 回落到 AKShare 的 stock_zh_a_spot_em()（东方财富接口）
    try:
        df = ak.stock_zh_a_spot_em()
        if df is not None and not df.empty:
            logging.info(f"AKShare 东方财富接口获取成功: {len(df)} 条")
            return _normalize_akshare_spot_em(df)
    except Exception as e:
        logging.warning(f"AKShare 东方财富接口失败: {e}")

    logging.error("AKShare 所有接口均失败")
    return pd.DataFrame()


def _normalize_akshare_spot(df: pd.DataFrame) -> pd.DataFrame:
    """
    标准化 AKShare 新浪接口返回的数据
    AKShare stock_zh_a_spot() 返回列: symbol, code, name, trade, pricechange, changepercent,
                                      buy, sell, settlement, open, high, low, volume, amount, ...
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # 重命名列
    column_mapping = {
        'symbol': 'code',       # symbol 已经是 sh600519 格式
        'name': 'name',
        'trade': 'new_price',
        'pricechange': 'ups_downs',
        'changepercent': 'change_rate',
        'buy': 'buy_price',
        'sell': 'sell_price',
        'settlement': 'pre_close_price',
        'open': 'open_price',
        'high': 'high_price',
        'low': 'low_price',
        'volume': 'volume',
        'amount': 'deal_amount',
    }

    # 只保留存在的列
    available_cols = {k: v for k, v in column_mapping.items() if k in df.columns}
    df = df.rename(columns=available_cols)

    # 处理 symbol 列（可能是 sh600519 或 600519 格式，也可能是整数）
    if 'code' in df.columns:
        # 先转为字符串
        df['code'] = df['code'].astype(str)
        # 如果是 sh600519 格式，提取出 600519
        df['code'] = df['code'].str.replace(r'^[a-z]{2}', '', regex=True)
        df['code'] = df['code'].str.zfill(6)

    # 过滤非 A 股（只保留 0/3/6/8/9 开头的 6 位代码）
    if 'code' in df.columns:
        df = df[df['code'].str.match(r'^[03689]\d{5}$', na=False)]

    # 选择需要的列
    needed_cols = ['code', 'name', 'new_price', 'ups_downs', 'change_rate',
                   'open_price', 'high_price', 'low_price', 'pre_close_price',
                   'volume', 'deal_amount', 'buy_price', 'sell_price']
    cols = [c for c in needed_cols if c in df.columns]
    df = df[cols]

    return df


def _normalize_akshare_spot_em(df: pd.DataFrame) -> pd.DataFrame:
    """
    标准化 AKShare 东方财富接口返回的数据
    AKShare stock_zh_a_spot_em() 返回列: code, name, latest_price, change, change_percent,
                                         buy, sell, volume, amount, open, high, low, pre_close, ...
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # 重命名列
    column_mapping = {
        'code': 'code',
        'name': 'name',
        'latest_price': 'new_price',
        'change': 'ups_downs',
        'change_percent': 'change_rate',
        'buy': 'buy_price',
        'sell': 'sell_price',
        'pre_close': 'pre_close_price',
        'open': 'open_price',
        'high': 'high_price',
        'low': 'low_price',
        'volume': 'volume',
        'amount': 'deal_amount',
    }

    # 只保留存在的列
    available_cols = {k: v for k, v in column_mapping.items() if k in df.columns}
    df = df.rename(columns=available_cols)

    # code 转为字符串并补零
    if 'code' in df.columns:
        df['code'] = df['code'].astype(str).str.zfill(6)
        # 过滤非 A 股
        df = df[df['code'].str.match(r'^[03689]\d{5}$', na=False)]

    # 选择需要的列
    needed_cols = ['code', 'name', 'new_price', 'ups_downs', 'change_rate',
                   'open_price', 'high_price', 'low_price', 'pre_close_price',
                   'volume', 'deal_amount', 'buy_price', 'sell_price']
    cols = [c for c in needed_cols if c in df.columns]
    df = df[cols]

    return df


def stock_zh_a_hist_ak(symbol: str, period: str = "daily",
                         start_date: str = None, end_date: str = None,
                         adjust: str = "qfq") -> pd.DataFrame:
    """
    使用 AKShare 获取 A 股历史行情
    :param symbol: 股票代码（如 600519）
    :param period: K线周期 (daily/weekly/monthly)
    :param start_date: 开始日期（如 20230101）
    :param end_date: 结束日期（如 20231231）
    :param adjust: 复权类型 (qfq/qfqs/none)
    :return: 历史行情 DataFrame
    """
    ak = _get_akshare()
    if ak is None:
        return pd.DataFrame()

    try:
        # 标准化 symbol（如果已经是 6 位数字，直接使用）
        symbol_6 = symbol.strip().zfill(6)

        df = ak.stock_zh_a_hist(symbol=symbol_6, period=period,
                                 start_date=start_date, end_date=end_date, adjust=adjust)
        if df is not None and not df.empty:
            logging.info(f"AKShare 历史K线获取成功: {symbol_6} {len(df)} 条")
            return df
    except Exception as e:
        logging.warning(f"AKShare 历史K线获取失败 {symbol}: {e}")

    return pd.DataFrame()


def fund_etf_spot_ak() -> pd.DataFrame:
    """
    使用 AKShare 获取 ETF 实时行情
    :return: ETF 实时行情 DataFrame
    """
    ak = _get_akshare()
    if ak is None:
        return pd.DataFrame()

    try:
        df = ak.fund_etf_spot_em()
        if df is None or df.empty:
            return pd.DataFrame()

        column_mapping = {
            '代码': 'code',
            '名称': 'name',
            '最新价': 'new_price',
            '涨跌幅': 'change_rate',
            '涨跌额': 'ups_downs',
            '成交量': 'volume',
            '成交额': 'deal_amount',
            '开盘价': 'open_price',
            '最高价': 'high_price',
            '最低价': 'low_price',
            '昨收': 'pre_close_price',
            '换手率': 'turnoverrate',
            '总市值': 'total_market_cap',
            '流通市值': 'free_cap',
        }

        available_cols = {k: v for k, v in column_mapping.items() if k in df.columns}
        df = df.rename(columns=available_cols)

        if 'code' in df.columns:
            df['code'] = df['code'].astype(str).str.zfill(6)

        # 确保所有必需列都存在，不存在则填充为 0
        needed_cols = ['code', 'name', 'new_price', 'change_rate', 'ups_downs',
                       'volume', 'deal_amount', 'open_price', 'high_price', 'low_price',
                       'pre_close_price', 'turnoverrate', 'total_market_cap', 'free_cap']
        for col in needed_cols:
            if col not in df.columns:
                df[col] = 0

        # 按顺序选择列
        df = df[needed_cols]

        logging.info(f"AKShare ETF获取成功: {len(df)} 条")
        return df
    except Exception as e:
        logging.warning(f"AKShare ETF获取失败: {e}")
        return pd.DataFrame()


def stock_zh_a_hist_ak_sina(symbol: str, period: str = "daily",
                             start_date: str = None, end_date: str = None,
                             adjust: str = "qfq") -> pd.DataFrame:
    """
    使用新浪接口 (ak.stock_zh_a_daily) 获取 A 股历史行情
    避免东方财富接口被封的问题
    :param symbol: 股票代码（6位数字，如 '600519'）
    :param period: 'daily'（目前只支持日线）
    :param start_date: 开始日期（YYYYMMDD）
    :param end_date: 结束日期（YYYYMMDD）
    :param adjust: 复权类型 'qfq'（前复权）或 'hfq'（后复权）或 ''（不复权）
    :return: DataFrame，列：date, open, close, high, low, volume, amount, amplitude, quote_change, ups_downs, turnover
    """
    ak = _get_akshare()
    if ak is None:
        return pd.DataFrame()

    try:
        # 新浪接口需要 sh/sz 前缀
        symbol_clean = symbol.strip()
        if len(symbol_clean) == 6 and symbol_clean.isdigit():
            if symbol_clean.startswith(('60', '68', '900')):
                sina_symbol = 'sh' + symbol_clean
            else:
                sina_symbol = 'sz' + symbol_clean
        else:
            sina_symbol = symbol_clean

        df = ak.stock_zh_a_daily(symbol=sina_symbol, start_date=start_date, end_date=end_date, adjust=adjust)
        if df is None or df.empty:
            return pd.DataFrame()

        # 新浪接口返回: date, open, high, low, close, volume, amount, outstanding_share, turnover
        # 需要映射为: date, open, close, high, low, volume, amount, amplitude, quote_change, ups_downs, turnover
        df = df.sort_values('date', ascending=True).reset_index(drop=True)

        result = pd.DataFrame()
        result['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')
        result['open'] = df['open'].astype(float)
        result['close'] = df['close'].astype(float)
        result['high'] = df['high'].astype(float)
        result['low'] = df['low'].astype(float)
        result['volume'] = df['volume'].astype(float)
        result['amount'] = df['amount'].astype(float)

        # 计算派生指标
        pre_close = df['close'].shift(1)
        # 振幅 = (high - low) / pre_close * 100
        result['amplitude'] = ((df['high'] - df['low']) / pre_close * 100).round(2)
        # 涨跌幅 = (close - pre_close) / pre_close * 100
        result['quote_change'] = ((df['close'] - pre_close) / pre_close * 100).round(2)
        # 涨跌额 = close - pre_close
        result['ups_downs'] = (df['close'] - pre_close).round(2)
        # 换手率（新浪接口已有但需要处理）
        if 'turnover' in df.columns:
            result['turnover'] = (df['turnover'] * 100).round(2)
        else:
            result['turnover'] = 0.0

        # 填充第一天的 NaN 值为 0
        result.loc[0, 'amplitude'] = 0.0
        result.loc[0, 'quote_change'] = 0.0
        result.loc[0, 'ups_downs'] = 0.0

        # date保持为普通列（与其他接口一致，11列，stock_hist_cache 会直接分配列名）
        return result
    except Exception as e:
        logging.warning(f"AKShare 新浪历史K线获取失败 {symbol}: {e}")
        return pd.DataFrame()


def stock_fund_flow_industry_ak() -> pd.DataFrame:
    """
    使用 AKShare 获取行业资金流向
    :return: 行业资金流向 DataFrame
    """
    ak = _get_akshare()
    if ak is None:
        return pd.DataFrame()

    try:
        df = ak.stock_fund_flow_industry()
        if df is None or df.empty:
            return pd.DataFrame()

        # 标准化列名: AKShare 返回 ['序号', '行业', '行业指数', '行业-涨跌幅', '流入资金', '流出资金', '净额', '公司家数', '领涨股', '领涨股-涨跌幅', '当前价']
        column_mapping = {
            '行业': 'name',
            '行业指数': 'index_value',
            '行业-涨跌幅': 'change_rate',
            '流入资金': 'fund_in',
            '流出资金': 'fund_out',
            '净额': 'fund_amount',
            '公司家数': 'company_count',
            '领涨股': 'leading_stock',
            '领涨股-涨跌幅': 'leading_change',
            '当前价': 'leading_price',
        }
        available_cols = {k: v for k, v in column_mapping.items() if k in df.columns}
        df = df.rename(columns=available_cols)

        # 确保列存在
        for col in ['name', 'index_value', 'change_rate', 'fund_in', 'fund_out', 'fund_amount', 'company_count', 'leading_stock', 'leading_change', 'leading_price']:
            if col not in df.columns:
                df[col] = 0 if col != 'name' and col != 'leading_stock' else ''

        logging.info(f"AKShare 行业资金流向获取成功: {len(df)} 条")
        return df
    except Exception as e:
        logging.warning(f"AKShare 行业资金流向获取失败: {e}")
        return pd.DataFrame()


def stock_fund_flow_concept_ak() -> pd.DataFrame:
    """
    使用 AKShare 获取概念资金流向
    :return: 概念资金流向 DataFrame
    """
    ak = _get_akshare()
    if ak is None:
        return pd.DataFrame()

    try:
        df = ak.stock_fund_flow_concept()
        if df is None or df.empty:
            return pd.DataFrame()

        column_mapping = {
            '行业': 'name',  # 注意: AKShare 概念板块也用'行业'列
            '行业指数': 'index_value',
            '行业-涨跌幅': 'change_rate',
            '流入资金': 'fund_in',
            '流出资金': 'fund_out',
            '净额': 'fund_amount',
            '公司家数': 'company_count',
            '领涨股': 'leading_stock',
            '领涨股-涨跌幅': 'leading_change',
            '当前价': 'leading_price',
        }
        available_cols = {k: v for k, v in column_mapping.items() if k in df.columns}
        df = df.rename(columns=available_cols)

        for col in ['name', 'index_value', 'change_rate', 'fund_in', 'fund_out', 'fund_amount', 'company_count', 'leading_stock', 'leading_change', 'leading_price']:
            if col not in df.columns:
                df[col] = 0 if col != 'name' and col != 'leading_stock' else ''

        logging.info(f"AKShare 概念资金流向获取成功: {len(df)} 条")
        return df
    except Exception as e:
        logging.warning(f"AKShare 概念资金流向获取失败: {e}")
        return pd.DataFrame()


def stock_block_trade_ak(start_date: str, end_date: str) -> pd.DataFrame:
    """
    使用 AKShare 获取大宗交易数据
    :param start_date: 开始日期 YYYYMMDD
    :param end_date: 结束日期 YYYYMMDD
    :return: 大宗交易 DataFrame
    """
    ak = _get_akshare()
    if ak is None:
        return pd.DataFrame()

    try:
        df = ak.stock_dzjy_mrtj(start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            return pd.DataFrame()

        # AKShare 返回: ['序号', '交易日期', '证券代码', '证券简称', '涨跌幅', '收盘价', '成交价', '折溢率', '成交笔数', '成交总量', '成交总额', '成交总额/流通市值']
        column_mapping = {
            '证券代码': 'code',
            '证券简称': 'name',
            '交易日期': 'trade_date',
            '收盘价': 'close_price',
            '成交价': 'trade_price',
            '涨跌幅': 'change_rate',
            '折溢率': 'discount_rate',
            '成交笔数': 'trade_count',
            '成交总量': 'volume',
            '成交总额': 'amount',
            '成交总额/流通市值': 'amount_ratio',
        }
        available_cols = {k: v for k, v in column_mapping.items() if k in df.columns}
        df = df.rename(columns=available_cols)

        if 'code' in df.columns:
            df['code'] = df['code'].astype(str).str.zfill(6)

        for col in ['code', 'name', 'trade_date', 'close_price', 'trade_price', 'change_rate', 'discount_rate', 'trade_count', 'volume', 'amount', 'amount_ratio']:
            if col not in df.columns:
                df[col] = 0 if col not in ['code', 'name', 'trade_date'] else ''

        logging.info(f"AKShare 大宗交易获取成功: {len(df)} 条")
        return df
    except Exception as e:
        logging.warning(f"AKShare 大宗交易获取失败: {e}")
        return pd.DataFrame()