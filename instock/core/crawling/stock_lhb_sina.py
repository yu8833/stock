#!/usr/bin/env python3
# -*- coding:utf-8 -*-
"""
Date: 2024/5/10 00:00
Desc: 新浪财经-龙虎榜
https://vip.stock.finance.sina.com.cn/q/go.php/vInvestConsult/kind/lhb/index.phtml
"""

from io import StringIO
import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm
from instock.core.eastmoney_fetcher import get_fetcher

__author__ = 'myh '
__date__ = '2026/06/21 '

fetcher = get_fetcher()


def stock_lhb_detail_daily_sina(date: str = "20240222") -> pd.DataFrame:
    """龙虎榜-每日详情"""
    date = "-".join([date[:4], date[4:6], date[6:]])
    url = "https://vip.stock.finance.sina.com.cn/q/go.php/vInvestConsult/kind/lhb/index.phtml"
    r = fetcher.make_request(url, params={"tradedate": date}, timeout=20)
    soup = BeautifulSoup(r.text, features="lxml")
    selected_html = soup.find(name="div", attrs={"class": "list"}).find_all(
        name="table", attrs={"class": "list_table"}
    )
    big_df = pd.DataFrame()
    for table in selected_html:
        temp_df = pd.read_html(StringIO(table.prettify()), header=0, skiprows=1)[0]
        temp_symbol = pd.read_html(StringIO(table.prettify()))[0].iat[0, 0]
        temp_df["指标"] = temp_symbol
        big_df = pd.concat(objs=[big_df, temp_df], ignore_index=True)
    big_df["股票代码"] = big_df["股票代码"].astype(str).str.zfill(6)
    del big_df["查看详情"]
    big_df.columns = [
        "序号", "股票代码", "股票名称", "收盘价", "对应值",
        "成交量", "成交额", "指标",
    ]
    for col in ("收盘价", "对应值", "成交量", "成交额"):
        big_df[col] = pd.to_numeric(big_df[col], errors="coerce")
    return big_df


def _find_last_page(
    url: str = "https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/ggtj/index.phtml",
    recent_day: str = "60",
):
    params = {"last": recent_day, "p": "1"}
    r = fetcher.make_request(url, params=params, timeout=20)
    soup = BeautifulSoup(r.text, "lxml")
    try:
        previous_page = int(soup.find_all(attrs={"class": "page"})[-2].text)
    except Exception:
        previous_page = 1
    if previous_page != 1:
        while True:
            params = {"last": recent_day, "p": previous_page}
            r = fetcher.make_request(url, params=params, timeout=20)
            soup = BeautifulSoup(r.text, "lxml")
            try:
                last_page = int(soup.find_all(attrs={"class": "page"})[-2].text)
            except Exception:
                break
            if last_page != previous_page:
                previous_page = last_page
                continue
            break
    return previous_page


def stock_lhb_ggtj_sina(symbol: str = "5") -> pd.DataFrame:
    """龙虎榜-个股上榜统计"""
    url = "https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/ggtj/index.phtml"
    last_page_num = _find_last_page(url, symbol)
    big_df = pd.DataFrame()
    for page in tqdm(range(1, last_page_num + 1), leave=False):
        r = fetcher.make_request(url, params={"last": symbol, "p": page}, timeout=20)
        temp_df = pd.read_html(StringIO(r.text))[0].iloc[0:, :]
        big_df = pd.concat(objs=[big_df, temp_df], ignore_index=True)
    big_df["股票代码"] = big_df["股票代码"].astype(str).str.zfill(6)
    big_df.columns = [
        "股票代码", "股票名称", "上榜次数", "累积购买额",
        "累积卖出额", "净额", "买入席位数", "卖出席位数",
    ]
    return big_df


def stock_lhb_yytj_sina(symbol: str = "5") -> pd.DataFrame:
    """龙虎榜-营业部上榜统计"""
    url = "https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/yytj/index.phtml"
    last_page_num = _find_last_page(url, symbol)
    big_df = pd.DataFrame()
    for page in tqdm(range(1, last_page_num + 1), leave=False):
        r = fetcher.make_request(url, params={"last": "5", "p": page}, timeout=20)
        temp_df = pd.read_html(StringIO(r.text))[0].iloc[0:, :]
        big_df = pd.concat([big_df, temp_df], ignore_index=True)
    big_df.columns = [
        "营业部名称", "上榜次数", "累积购买额", "买入席位数",
        "累积卖出额", "卖出席位数", "买入前三股票",
    ]
    for col in ("上榜次数", "买入席位数", "卖出席位数"):
        big_df[col] = pd.to_numeric(big_df[col], errors="coerce")
    return big_df


def stock_lhb_jgzz_sina(symbol: str = "5") -> pd.DataFrame:
    """龙虎榜-机构席位追踪"""
    url = "https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/jgzz/index.phtml"
    last_page_num = _find_last_page(url, symbol)
    big_df = pd.DataFrame()
    for page in tqdm(range(1, last_page_num + 1), leave=False):
        r = fetcher.make_request(url, params={"last": symbol, "p": page}, timeout=20)
        temp_df = pd.read_html(StringIO(r.text))[0].iloc[0:, :]
        if temp_df.empty:
            continue
        big_df = pd.concat(objs=[big_df, temp_df], ignore_index=True)
    big_df["股票代码"] = big_df["股票代码"].astype(str).str.zfill(6)
    del big_df["当前价"]
    del big_df["涨跌幅"]
    big_df.columns = [
        "股票代码", "股票名称", "累积买入额", "买入次数",
        "累积卖出额", "卖出次数", "净额",
    ]
    for col in ("买入次数", "卖出次数"):
        big_df[col] = pd.to_numeric(big_df[col], errors="coerce")
    return big_df


def stock_lhb_jgmx_sina() -> pd.DataFrame:
    """龙虎榜-机构席位成交明细"""
    url = "https://vip.stock.finance.sina.com.cn/q/go.php/vLHBData/kind/jgmx/index.phtml"
    r = fetcher.make_request(url, params={"p": "1"}, timeout=20)
    soup = BeautifulSoup(r.text, features="lxml")
    try:
        last_page_num = int(soup.find_all(attrs={"class": "page"})[-2].text)
    except Exception:
        last_page_num = 1
    big_df = pd.DataFrame()
    for page in tqdm(range(1, last_page_num + 1), leave=False):
        r = fetcher.make_request(url, params={"p": page}, timeout=20)
        temp_df = pd.read_html(StringIO(r.text))[0].iloc[0:, :]
        big_df = pd.concat(objs=[big_df, temp_df], ignore_index=True)
    big_df["股票代码"] = big_df["股票代码"].astype(str).str.zfill(6)
    big_df["交易日期"] = pd.to_datetime(big_df["交易日期"], errors="coerce").dt.date
    big_df.rename(
        columns={
            "机构席位买入额(万)": "机构席位买入额",
            "机构席位卖出额(万)": "机构席位卖出额",
        },
        inplace=True,
    )
    big_df["机构席位买入额"] = pd.to_numeric(big_df["机构席位买入额"], errors="coerce")
    big_df["机构席位卖出额"] = pd.to_numeric(big_df["机构席位卖出额"], errors="coerce")
    return big_df


if __name__ == "__main__":
    print(stock_lhb_detail_daily_sina(date="20240222"))
    print(stock_lhb_ggtj_sina(symbol="5"))
    print(stock_lhb_yytj_sina(symbol="5"))
    print(stock_lhb_jgzz_sina(symbol="5"))
    print(stock_lhb_jgmx_sina())
