#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import re
import json
import random
import time
import logging
from pathlib import Path

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from instock.core.singleton_proxy import proxys

__author__ = 'myh '
__date__ = '2026/06/21 '

logger = logging.getLogger(__name__)

# -----------------------------------------------------------------
# 多 UA 轮换：模拟不同浏览器 / 客户端，降低指纹命中概率
# -----------------------------------------------------------------
USER_AGENTS = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 13; MI 13) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Mobile Safari/537.36 EastmoneyStock/8.8.5',
]

# 根据接口域名选择合适的 Referer，避免统一 Referer 导致命中风控
REFERER_MAP = {
    'push2his.eastmoney.com': 'https://quote.eastmoney.com/',
    'push2.eastmoney.com':    'https://quote.eastmoney.com/',
    '82.push2.eastmoney.com': 'https://quote.eastmoney.com/center/gridlist.html',
    '80.push2.eastmoney.com': 'https://quote.eastmoney.com/center/gridlist.html',
    '88.push2.eastmoney.com': 'https://quote.eastmoney.com/center/gridlist.html',
    'datacenter-web.eastmoney.com': 'https://data.eastmoney.com/',
    'data.eastmoney.com':           'https://data.eastmoney.com/',
    'emweb.securities.eastmoney.com': 'https://emweb.securities.eastmoney.com/',
    # 同花顺
    'zx.10jqka.com.cn': 'http://zx.10jqka.com.cn/',
    # 新浪财经
    'vip.stock.finance.sina.com.cn': 'https://vip.stock.finance.sina.com.cn/',
    'finance.sina.com.cn': 'https://finance.sina.com.cn/',
    # 通达信
    'excalc.icfqs.com': 'http://excalc.icfqs.com:7616/',
}

# 这些接口通过 token 参数鉴权，不需要 Cookie 会话
TOKEN_API_HOSTS = (
    'push2his.eastmoney.com',
    'push2.eastmoney.com',
    '82.push2.eastmoney.com',
    '80.push2.eastmoney.com',
    '88.push2.eastmoney.com',
)


class eastmoney_fetcher:
    """
    统一请求核心。
    - 直连为主（proxy.txt 为空时），随机延迟 + 多 UA 降低风控
    - 按需自动刷新 Cookie，不再依赖硬编码过期 Cookie
    - Referer 与接口域名自动匹配
    - JSONP / HTML 兜底解析
    - 代理可用时自动切换代理，失败则标记坏代理并回退直连
    """

    def __init__(self):
        self.base_dir = os.path.dirname(os.path.dirname(__file__))
        self._proxy_pool = proxys().get_data() or []
        self._bad_proxies = set()

        self._cookie_session = self._create_session(need_cookie=True)
        self._token_session = self._create_session(need_cookie=False)

        # 启动时尝试刷新一次 Cookie；失败不阻塞，走备用路径
        try:
            self._refresh_cookie()
        except Exception as e:
            logger.warning("初始化刷新 Cookie 失败，将走备用路径: %s", e)

    # -------------------------------------------------------------
    # Session 构造：单一重试机制（urllib3 Retry）
    # -------------------------------------------------------------
    def _create_session(self, need_cookie=True):
        session = requests.Session()

        retry_strategy = Retry(
            total=4,
            backoff_factor=1,      # 失败间 1, 2, 4, 8 秒退避
            status_forcelist=[403, 429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "OPTIONS"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=20,
            pool_maxsize=20,
            pool_block=False,
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        session.headers.update({
            'User-Agent': random.choice(USER_AGENTS),
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'zh-CN,zh;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        })

        if need_cookie:
            cookie = self._load_cookie_from_env_or_file()
            if cookie:
                for kv in cookie.split(';'):
                    if '=' in kv:
                        k, v = kv.strip().split('=', 1)
                        session.cookies.set(k, v, domain='.eastmoney.com')
        return session

    # -------------------------------------------------------------
    # Cookie 管理
    # -------------------------------------------------------------
    def _load_cookie_from_env_or_file(self):
        """
        从环境变量读取 Cookie（优先级最高）。
        当前东财公开接口均为 token 参数鉴权，一般不需要 Cookie，
        此处仅作预留——当东财开始要求登录态时，可通过环境变量注入。
        """
        cookie = os.environ.get('EAST_MONEY_COOKIE')
        if cookie and cookie.strip() and not cookie.strip().startswith('#'):
            return cookie.strip()
        return None

    def _refresh_cookie(self):
        """
        通过访问门户页面拿到新鲜 Cookie。
        当前使用直连模式，延迟适当加高。
        """
        urls = [
            'https://quote.eastmoney.com/',
            'https://data.eastmoney.com/',
            'https://data.eastmoney.com/xuangu/',
        ]
        last_err = None
        for url in urls:
            try:
                r = self._cookie_session.get(
                    url,
                    timeout=10,
                    proxies=self._pick_proxy(),
                    headers={
                        'Referer': 'https://www.eastmoney.com/',
                        'User-Agent': random.choice(USER_AGENTS),
                    },
                )
                if r.status_code == 200:
                    logger.debug("刷新 cookie 成功: %s", url)
                    return
            except Exception as e:
                last_err = e
                continue
        logger.warning("刷新 cookie 失败(可能被风控)：%s", last_err)

    def update_cookie(self, new_cookie):
        """手动注入新 cookie（比如从浏览器复制）"""
        session = self._cookie_session
        for cookie in list(session.cookies):
            if 'eastmoney.com' in getattr(cookie, 'domain', ''):
                session.cookies.clear(
                    domain=cookie.domain, path=cookie.path, name=cookie.name
                )
        if new_cookie:
            for kv in new_cookie.split(';'):
                if '=' in kv:
                    k, v = kv.strip().split('=', 1)
                    session.cookies.set(k, v, domain='.eastmoney.com')

    # -------------------------------------------------------------
    # 代理管理（直连为主，有代理才用）
    # -------------------------------------------------------------
    def _pick_proxy(self):
        if not self._proxy_pool:
            return None
        candidates = [p for p in self._proxy_pool if p not in self._bad_proxies]
        if not candidates:
            self._bad_proxies.clear()
            return None
        proxy = random.choice(candidates)
        return {"http": proxy, "https": proxy}

    def _mark_proxy_bad(self, proxies):
        if not proxies:
            return
        p = proxies.get('http') or proxies.get('https')
        if p:
            self._bad_proxies.add(p)

    # -------------------------------------------------------------
    # 会话选择 / Referer 选择
    # -------------------------------------------------------------
    def _decide_session(self, url):
        host = requests.utils.urlparse(url).hostname or ''
        if host in TOKEN_API_HOSTS:
            return self._token_session
        return self._cookie_session

    def _referer_for(self, url):
        host = requests.utils.urlparse(url).hostname or ''
        return REFERER_MAP.get(host, 'https://www.eastmoney.com/')

    # -------------------------------------------------------------
    # 对外主入口
    # -------------------------------------------------------------
    def make_request(self, url, params=None, timeout=15,
                     retry_switch_proxy=2):
        session = self._decide_session(url)
        session.headers['User-Agent'] = random.choice(USER_AGENTS)
        session.headers['Referer'] = self._referer_for(url)

        last_err = None
        proxies = self._pick_proxy()

        for attempt in range(1, retry_switch_proxy + 1):
            try:
                # 直连模式下，额外加一点随机延迟以降低请求密度
                if proxies is None:
                    time.sleep(random.uniform(0.8, 1.8))
                response = session.get(
                    url,
                    proxies=proxies,
                    params=params,
                    timeout=timeout,
                )
                response.raise_for_status()
                # 风控兜底：若返回 HTML（常见于登录跳转 / 风控页面），按失败处理
                if self._looks_like_json_api(url, params):
                    ctype = (response.headers.get('Content-Type') or '').lower()
                    text_start = (response.text or '').strip()[:50]
                    if 'html' in ctype or text_start.startswith(('<!DOC', '<!doc', '<html', '<HTML')):
                        raise requests.exceptions.HTTPError(
                            f"接口返回 HTML（可能被风控）: {url}", response=response
                        )
                return response
            except requests.exceptions.RequestException as e:
                last_err = e
                logger.warning("请求失败(%s/第%d次): %s -> %s",
                               type(e).__name__, attempt, url, e)
                self._mark_proxy_bad(proxies)
                proxies = self._pick_proxy()
                time.sleep(random.uniform(2.0, 4.0))

                if attempt == retry_switch_proxy and session is self._cookie_session:
                    try:
                        self._refresh_cookie()
                    except Exception as ce:
                        logger.warning("刷新 cookie 失败: %s", ce)

        # 最终回退：直连再试一次
        try:
            time.sleep(random.uniform(1.5, 3.0))
            response = session.get(url, proxies=None, params=params, timeout=timeout)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            logger.error("所有路径均失败: %s -> %s", url, e)
            raise last_err or e

    def make_post_request(self, url, data=None, json=None, params=None,
                          timeout=30):
        session = self._decide_session(url)
        session.headers['User-Agent'] = random.choice(USER_AGENTS)
        session.headers['Referer'] = self._referer_for(url)

        proxies = self._pick_proxy()
        try:
            response = session.post(
                url, data=data, json=json, params=params,
                proxies=proxies, timeout=timeout,
            )
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as e:
            self._mark_proxy_bad(proxies)
            logger.warning("POST 首次失败，切换/直连重试: %s", e)
            time.sleep(random.uniform(2.0, 4.0))
            response = session.post(
                url, data=data, json=json, params=params,
                proxies=self._pick_proxy(), timeout=timeout,
            )
            response.raise_for_status()
            return response

    # -------------------------------------------------------------
    # 工具方法
    # -------------------------------------------------------------
    @staticmethod
    def _looks_like_json_api(url, params):
        low = (url or '').lower()
        if '/api/' in low or 'json' in low:
            return True
        if params and any(k in params for k in ('ut', 'cb', 'secid', 'sty')):
            return True
        return False

    @staticmethod
    def parse_jsonp(text):
        """剥离 `jQuery183xxx( ... );` 这类 JSONP 包裹，返回 dict"""
        if not text:
            raise ValueError("empty response")
        t = text.strip()
        m = re.match(r'^[\w$.]+\s*\(\s*(.*?)\s*\)\s*;?\s*$', t, re.S)
        payload = m.group(1) if m else t
        payload = payload.rstrip().rstrip(';')
        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            # 兜底：尝试把单引号替换为双引号（尽量少用）
            try:
                return json.loads(payload.replace("'", '"'))
            except Exception:
                raise


# 全局单例：所有爬虫共享同一个 fetcher（共享同一个 cookie session）
_fetcher_instance = None


def get_fetcher():
    global _fetcher_instance
    if _fetcher_instance is None:
        _fetcher_instance = eastmoney_fetcher()
    return _fetcher_instance
