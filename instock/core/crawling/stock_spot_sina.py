#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Date: 2025/12/31
Desc: 新浪财经-沪深京A股实时行情
https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeDataSimple
"""

import random
import time

import pandas as pd
from instock.core.eastmoney_fetcher import get_fetcher

__author__ = 'myh'
__date__ = '2025/12/31'

fetcher = get_fetcher()


def stock_zh_a_spot_sina() -> pd.DataFrame:
    """
    新浪财经-沪深京A股实时行情（获取所有页面）
    :return: 实时行情 DataFrame
    """
    url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeDataSimple"
    all_data = []
    page = 1
    while True:
        params = {
            "page": page,
            "num": 500,
            "sort": "symbol",
            "asc": 1,
            "node": "hs_a",
            "symbol": "",
            "_s_r_a": "page"
        }
        try:
            r = fetcher.make_request(url, params=params, timeout=30)
            data = r.json()
            if not data:
                break
            all_data.extend(data)
            if len(data) < 500:
                break
            page += 1
            time.sleep(random.uniform(0.5, 1.0))  # 避免请求过快
        except Exception:
            break

    if not all_data:
        return pd.DataFrame()
    df = pd.DataFrame(all_data)
    # 新浪字段映射到标准字段（symbol 不重命名，直接使用 code 列）
    df = df.rename(columns={
        "name": "name",
        "trade": "new_price",
        "pricechange": "ups_downs",
        "changepercent": "change_rate",
        "buy": "buy_price",
        "sell": "sell_price",
        "settlement": "pre_close_price",
        "open": "open_price",
        "high": "high_price",
        "low": "low_price",
        "volume": "volume",
        "amount": "deal_amount",
        "ticktime": "ticktime"
    })
    # 过滤 B股和无用的列
    df = df[["code", "name", "new_price", "ups_downs", "change_rate",
              "open_price", "high_price", "low_price", "pre_close_price",
              "volume", "deal_amount", "buy_price", "sell_price", "ticktime"]]
    # code 转为字符串，并过滤非 A 股（code 以 0/3/6/8/9 开头）
    df["code"] = df["code"].astype(str).str.zfill(6)
    df = df[df["code"].str.match(r"^[03689]\d{5}$")]
    return df