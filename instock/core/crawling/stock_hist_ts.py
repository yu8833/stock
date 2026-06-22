#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tushare 数据源 —— 以现有东方财富模块的同样风格暴露常用接口。

接口清单：
- stock_zh_a_hist_ts(ts_code, start_date, end_date) : 日线行情（单位：手、元）
- stock_basic_ts() / stock_basic_ts(ts_code="000001.SZ") : 股票基本信息
- daily_basic_ts(ts_code, start_date, end_date) : 每日指标（换手率/PE/PB/市值）
- tool_trade_date_hist_ts() : 上交所交易日历
- code_id_map_ts() : 股票代码 -> ts_code 映射
"""

import logging
import pandas as pd
from instock.core import tushare_fetcher as tfs

__author__ = 'myh '
__date__ = '2026/06/21 '

fetcher = tfs.get_fetcher()
logger = logging.getLogger(__name__)


def _to_ts_code(code):
    """把 '000001' / '600000' 等 6 位 A 股代码转为 tushare 的 ts_code"""
    if code is None:
        return code
    code = str(code).strip().upper()
    if '.' in code:
        return code
    if len(code) != 6:
        return code
    if code.startswith(('6', '9')):
        return f"{code}.SH"
    if code.startswith(('0', '3')):
        return f"{code}.SZ"
    if code.startswith(('8', '43', '87', '430')):
        return f"{code}.BJ"
    return code


def code_id_map_ts():
    """tushare 风格的 A 股代码映射；返回 dict: {6位代码: ts_code}"""
    if not fetcher.enabled:
        return {}
    df = fetcher.stock_basic(list_status='L')
    if df is None or df.empty:
        return {}
    out = {}
    for row in df.itertuples(index=False):
        ts_code = row.ts_code
        if isinstance(ts_code, str) and '.' in ts_code:
            code = ts_code.split('.')[0]
            if code:
                out[code] = ts_code
    return out


def stock_zh_a_hist_ts(
    symbol: str = "000001.SZ",
    start_date: str = "20240101",
    end_date: str = "20241231",
) -> pd.DataFrame:
    """日线行情。字段命名与 stock_hist_em.stock_zh_a_hist 完全一致。"""
    if not fetcher.enabled:
        return pd.DataFrame()
    ts_code = _to_ts_code(symbol)
    df = fetcher.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        return pd.DataFrame()
    return df


def stock_basic_ts(symbol: str = "") -> pd.DataFrame:
    """股票基本信息"""
    if not fetcher.enabled:
        return pd.DataFrame()
    ts_code = _to_ts_code(symbol) if symbol else ''
    df = fetcher.stock_basic(ts_code=ts_code, list_status='L')
    if df is None or df.empty:
        return pd.DataFrame()
    return df


def daily_basic_ts(
    symbol: str = "000001.SZ",
    start_date: str = "20240101",
    end_date: str = "20241231",
) -> pd.DataFrame:
    """每日指标（换手率/量比/PE/PB/总市值/流通市值等）"""
    if not fetcher.enabled:
        return pd.DataFrame()
    ts_code = _to_ts_code(symbol)
    df = fetcher.daily_basic(ts_code=ts_code, start_date=start_date, end_date=end_date)
    if df is None or df.empty:
        return pd.DataFrame()
    return df


def tool_trade_date_hist_ts(
    start_date: str = "19900101",
    end_date: str = "20991231",
) -> pd.DataFrame:
    """上交所交易日历；单列 DataFrame：trade_date（datetime.date）"""
    if not fetcher.enabled:
        return pd.DataFrame()
    df = fetcher.trade_cal(start_date=start_date, end_date=end_date,
                           exchange='SSE', is_open=1)
    if df is None or df.empty:
        return pd.DataFrame()
    return df


if __name__ == "__main__":
    print(stock_zh_a_hist_ts("000001.SZ", "20240101", "20240301"))
    print(tool_trade_date_hist_ts().tail())
