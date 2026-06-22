#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tushare 数据源客户端。

- 配置：instock/config/tushare.json（必须包含 token 字段）
- 单例：get_fetcher() 返回全局客户端
- 依赖：pip install tushare
"""

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

__author__ = 'myh '
__date__ = '2026/06/21 '


def _config_path():
    """tushare.json 的绝对路径（与项目中其他配置文件同目录）。"""
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, 'config', 'tushare.json')


def load_config():
    """加载 tushare.json；文件缺失或 token 未配置时返回 {}。
    优先级：环境变量 TUSHARE_TOKEN > 配置文件 tushare.json 中的 token
    """
    path = _config_path()
    cfg = {}
    try:
        with open(path, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except FileNotFoundError:
        logger.warning("tushare 配置文件不存在：%s", path)
    except Exception as e:
        logger.warning("读取 tushare 配置失败：%s -> %s", path, e)

    # 优先使用环境变量 TUSHARE_TOKEN（方便 docker compose -e TUSHARE_TOKEN=... 注入）
    env_token = (os.environ.get('TUSHARE_TOKEN') or '').strip()
    if env_token:
        cfg['token'] = env_token

    token = (cfg.get('token') or '').strip()
    if not token or token in ('YOUR_TUSHARE_TOKEN_HERE', ''):
        logger.warning(
            "tushare token 未配置（可用环境变量 TUSHARE_TOKEN 或在 %s 中填写）",
            path,
        )
        return {}

    # 缺省值填充
    cfg.setdefault('enabled', True)
    cfg.setdefault('preferred', ['daily', 'trade_cal', 'daily_basic', 'stock_basic'])
    cfg.setdefault('connect_timeout', 30)
    cfg.setdefault('read_timeout', 60)
    cfg.setdefault('retry_count', 3)
    cfg.setdefault('pause_sec', 0.05)
    return cfg


class tushare_fetcher:
    """统一的 tushare 客户端：读取配置、创建 pro_api、封装高频接口。"""

    def __init__(self):
        self.config = load_config()
        self.enabled = bool(self.config) and self.config.get('enabled', True)
        self.token = self.config.get('token', '')
        self._pro = None
        self._ts = None
        if self.enabled:
            self._init_client()

    # ------------------------------------------------------------------
    # client 初始化
    # ------------------------------------------------------------------
    def _init_client(self):
        try:
            import tushare as ts
        except ImportError:
            logger.error("未安装 tushare 库，执行：pip install tushare")
            self.enabled = False
            return

        self._ts = ts
        try:
            ts.set_token(self.token)
            self._pro = ts.pro_api(
                token=self.token,
                timeout=(int(self.config.get('connect_timeout', 30)),
                         int(self.config.get('read_timeout', 60))),
            )
        except Exception as e:
            logger.error("初始化 tushare pro_api 失败：%s", e)
            self.enabled = False

    # ------------------------------------------------------------------
    # 通用 call：自动处理节流与重试
    # ------------------------------------------------------------------
    def call(self, api_name, **kwargs):
        """调用 tushare 指定接口（带重试/限速），失败返回 None。"""
        if not self.enabled or self._pro is None:
            logger.warning("tushare 未启用，跳过 %s 调用", api_name)
            return None

        api = getattr(self._pro, api_name, None)
        if api is None:
            logger.error("tushare 接口不存在：%s", api_name)
            return None

        retry = int(self.config.get('retry_count', 3))
        pause = float(self.config.get('pause_sec', 0.05))
        last_err = None
        for attempt in range(1, retry + 1):
            try:
                df = api(**kwargs)
                # tushare 会返回空 DataFrame 表示无数据
                if pause:
                    time.sleep(pause)
                return df
            except Exception as e:
                last_err = e
                msg = str(e)
                # 识别到频次/权限错误时再退避一段时间
                if any(k in msg for k in ('4029', '4028', '权限', '频率', '调用次数')):
                    backoff = pause * 10 * attempt
                else:
                    backoff = pause * 5 * attempt
                logger.warning(
                    "tushare.%s 第 %d 次失败：%s，退避 %.2fs 后重试",
                    api_name, attempt, e, backoff,
                )
                time.sleep(backoff)

        logger.error("tushare.%s 已达最大重试次数，放弃：%s", api_name, last_err)
        return None

    # ------------------------------------------------------------------
    # 常用接口的便捷封装（返回 pandas.DataFrame，字段命名与东财模块一致）
    # ------------------------------------------------------------------
    def trade_cal(self, start_date, end_date, exchange='SSE', is_open=1):
        """交易日历；DataFrame 列：trade_date（datetime.date）"""
        df = self.call('trade_cal', exchange=exchange,
                       start_date=start_date, end_date=end_date,
                       is_open=str(is_open))
        if df is None or df.empty:
            return df
        df = df.copy()
        df['trade_date'] = df['cal_date'].apply(lambda x: _to_date(x))
        return df[['trade_date']]

    def stock_basic(self, ts_code='', name='', list_status='L'):
        """股票基本信息；ts_code 可留空拉全量，DataFrame 列与 tushare 一致"""
        return self.call('stock_basic', ts_code=ts_code, name=name, list_status=list_status)

    def daily(self, ts_code, start_date, end_date):
        """日线行情（未复权）：日期/开盘/收盘/最高/最低/成交量/成交额/涨跌幅"""
        df = self.call('daily', ts_code=ts_code, start_date=start_date, end_date=end_date)
        if df is None or df.empty:
            return df
        return self._normalize_daily(df)

    def daily_basic(self, ts_code, start_date, end_date):
        """每日指标（换手率/量比/市盈率/市净率/总市值/流通市值 等）"""
        return self.call('daily_basic', ts_code=ts_code,
                         start_date=start_date, end_date=end_date)

    def moneyflow(self, trade_date='', ts_code='', start_date='', end_date=''):
        """个股资金流向（小单/中单/大单/特大单 买卖量与金额）
        
        Args:
            trade_date: 交易日期，格式 YYYYMMDD（如 '20240621'）
            ts_code: 股票代码（如 '000001.SZ'），与日期参数至少输入一个
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            DataFrame 包含：ts_code, trade_date, buy_sm_vol, buy_sm_amount, 
            sell_sm_vol, sell_sm_amount, buy_md_vol, buy_md_amount, 
            sell_md_vol, sell_md_amount, buy_lg_vol, buy_lg_amount, 
            sell_lg_vol, sell_lg_amount, buy_elg_vol, buy_elg_amount, 
            sell_elg_vol, sell_elg_amount, net_mf_vol, net_mf_amount
        """
        kwargs = {}
        if trade_date:
            kwargs['trade_date'] = trade_date
        if ts_code:
            kwargs['ts_code'] = ts_code
        if start_date:
            kwargs['start_date'] = start_date
        if end_date:
            kwargs['end_date'] = end_date
        return self.call('moneyflow', **kwargs)

    def moneyflow_hsgt(self, trade_date=''):
        """沪港深资金流向（北向/南向资金）
        
        Args:
            trade_date: 交易日期，格式 YYYYMMDD
            
        Returns:
            DataFrame 包含：trade_date, ggt_ss, ggt_sz, hgt, sgt, 
            north_money, south_money
        """
        kwargs = {}
        if trade_date:
            kwargs['trade_date'] = trade_date
        return self.call('moneyflow_hsgt', **kwargs)

    def top_list(self, trade_date=''):
        """龙虎榜个股列表
        
        Args:
            trade_date: 交易日期，格式 YYYYMMDD
            
        Returns:
            DataFrame 包含：trade_date, ts_code, name, close, pct_change,
            turnover_rate, amount, l_sell, l_buy, l_amount, net_amount,
            net_rate, amount_rate, float_values, reason
        """
        kwargs = {}
        if trade_date:
            kwargs['trade_date'] = trade_date
        return self.call('top_list', **kwargs)

    def weekly(self, trade_date=''):
        """每周 IPO 辅导开始
        
        Args:
            trade_date: 交易日期，格式 YYYYMMDD
            
        Returns:
            DataFrame 包含：股票每周重要行为数据
        """
        kwargs = {}
        if trade_date:
            kwargs['trade_date'] = trade_date
        return self.call('weekly', **kwargs)

    def monthly(self, trade_date=''):
        """每月 IPO 辅导
        
        Args:
            trade_date: 交易日期，格式 YYYYMMDD
            
        Returns:
            DataFrame 包含：股票每月重要行为数据
        """
        kwargs = {}
        if trade_date:
            kwargs['trade_date'] = trade_date
        return self.call('monthly', **kwargs)

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_daily(df):
        df = df.copy()
        df['trade_date'] = df['trade_date'].apply(_to_date)
        df.sort_values('trade_date', inplace=True)
        df.reset_index(drop=True, inplace=True)
        df.rename(columns={
            'trade_date': '日期',
            'open': '开盘',
            'close': '收盘',
            'high': '最高',
            'low': '最低',
            'vol': '成交量',
            'amount': '成交额',
            'pct_chg': '涨跌幅',
            'change': '涨跌额',
        }, inplace=True)
        # 东财模块输出还包含"振幅/换手率"，tushare daily 没有就留空
        for col in ('振幅', '换手率'):
            if col not in df.columns:
                df[col] = float('nan')
        return df[['日期', '开盘', '收盘', '最高', '最低',
                   '成交量', '成交额', '振幅', '涨跌幅', '涨跌额', '换手率']]


def _to_date(val):
    """把 '20240221' / '2024-02-21' / datetime 等统一为 datetime.date"""
    if val is None:
        return None
    if isinstance(val, str):
        val = val.strip().replace('-', '')
        try:
            from datetime import datetime
            return datetime.strptime(val, '%Y%m%d').date()
        except Exception:
            return None
    try:
        return val.date()
    except AttributeError:
        try:
            return val
        except Exception:
            return None


# ----------------------------------------------------------------------
# 全局单例
# ----------------------------------------------------------------------
_fetcher_instance = None


def get_fetcher():
    global _fetcher_instance
    if _fetcher_instance is None:
        _fetcher_instance = tushare_fetcher()
    return _fetcher_instance


def is_enabled():
    """是否可用于调用（配置了 token 且库可用）"""
    return get_fetcher().enabled
