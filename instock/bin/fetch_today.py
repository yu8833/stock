#!/usr/bin/env python3
"""抓取今日交易数据并写入数据库"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import datetime
import instock.core.stockfetch as stf
import instock.lib.database as mdb
import instock.core.tablestructure as tbs

today = datetime.date.today()
today_str = today.strftime('%Y-%m-%d')
print('抓取今日交易数据 -', today_str)
print('=' * 60)

tasks = [
    ('股票行情', tbs.TABLE_CN_STOCK_SPOT, lambda: stf.fetch_stocks(today)),
    ('龙虎榜', tbs.TABLE_CN_STOCK_lHB, lambda: stf.fetch_stock_lhb_data(today)),
    ('早盘抢筹', tbs.TABLE_CN_STOCK_CHIP_RACE_OPEN, lambda: stf.fetch_stock_chip_race_open(today_str)),
    ('涨停原因', tbs.TABLE_CN_STOCK_LIMITUP_REASON, lambda: stf.fetch_stock_limitup_reason(today_str)),
]

for task_name, table_info, fetch_fn in tasks:
    table_name = table_info['name']
    print()
    print(task_name + '...')
    try:
        data = fetch_fn()
        if data is not None and len(data) > 0:
            cols_type = None
            if not mdb.checkTableIsExist(table_name):
                cols_type = tbs.get_field_types(table_info['columns'])
            mdb.insert_db_from_df(data, table_name, cols_type, False, "`date`,`code`")
            print('  写入', len(data), '条')
        else:
            print('  无数据')
    except Exception as e:
        print('  错误:', e)

print()
print('=' * 60)
print('数据抓取完成 -', today_str)
