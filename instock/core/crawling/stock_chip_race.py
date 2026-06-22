#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Date: 2025/2/26 12:18
Desc: 通达信竞价抢筹
http://excalc.icfqs.com:7616/TQLEX?Entry=HQServ.hq_nlp
"""

import pandas as pd
from instock.core.eastmoney_fetcher import get_fetcher

__author__ = 'myh '
__date__ = '2026/06/21 '

fetcher = get_fetcher()


def _post(date, period):
    """封装通达信统一的 POST 调用"""
    url = "http://excalc.icfqs.com:7616/TQLEX?Entry=HQServ.hq_nlp"
    params = [
        {
            "funcId": 20,
            "offset": 0,
            "count": 100,
            "sort": 1,
            "period": period,
            "Token": "6679f5cadca97d68245a086793fc1bfc0a50b487487c812f",
            "modname": "JJQC",
        }
    ]
    if date:
        params[0]["date"] = date
    r = fetcher.make_post_request(url, json=params, timeout=30)
    return r.json()["datas"]


def stock_chip_race_open(date: str = "") -> pd.DataFrame:
    """早盘竞价抢筹"""
    data = _post(date, 0)
    if not data:
        return pd.DataFrame()

    temp_df = pd.DataFrame(data)
    temp_df.columns = [
        "代码", "名称", "昨收", "今开", "开盘金额",
        "抢筹幅度", "抢筹委托金额", "抢筹成交金额", "最新价", "_",
        "天", "板",
    ]

    temp_df["昨收"] = temp_df["昨收"] / 10000
    temp_df["今开"] = temp_df["今开"] / 10000
    temp_df["抢筹幅度"] = round(temp_df["抢筹幅度"] * 100, 2)
    temp_df["最新价"] = pd.to_numeric(temp_df["最新价"], errors="coerce").round(2)
    temp_df["涨跌幅"] = round(
        (temp_df["最新价"] / temp_df["昨收"] - 1) * 100, 2
    )
    temp_df["抢筹占比"] = round(
        (temp_df["抢筹成交金额"] / temp_df["开盘金额"]) * 100, 2
    )

    temp_df = temp_df[[
        "代码", "名称", "最新价", "涨跌幅", "昨收", "今开",
        "开盘金额", "抢筹幅度", "抢筹委托金额", "抢筹成交金额",
        "抢筹占比", "天", "板",
    ]]
    return temp_df


def stock_chip_race_end(date: str = "") -> pd.DataFrame:
    """尾盘竞价抢筹"""
    data = _post(date, 1)
    if not data:
        return pd.DataFrame()

    temp_df = pd.DataFrame(data)
    temp_df.columns = [
        "代码", "名称", "昨收", "今开", "收盘金额",
        "抢筹幅度", "抢筹委托金额", "抢筹成交金额", "最新价", "_",
        "天", "板",
    ]

    temp_df["昨收"] = temp_df["昨收"] / 10000
    temp_df["今开"] = temp_df["今开"] / 10000
    temp_df["抢筹幅度"] = round(temp_df["抢筹幅度"] * 100, 2)
    temp_df["最新价"] = pd.to_numeric(temp_df["最新价"], errors="coerce").round(2)
    temp_df["涨跌幅"] = round(
        (temp_df["最新价"] / temp_df["昨收"] - 1) * 100, 2
    )
    temp_df["抢筹占比"] = round(
        (temp_df["抢筹成交金额"] / temp_df["收盘金额"]) * 100, 2
    )

    temp_df = temp_df[[
        "代码", "名称", "最新价", "涨跌幅", "昨收", "今开",
        "收盘金额", "抢筹幅度", "抢筹委托金额", "抢筹成交金额",
        "抢筹占比", "天", "板",
    ]]
    return temp_df


if __name__ == "__main__":
    print(stock_chip_race_open())
    print(stock_chip_race_end())
