#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
from instock.lib.singleton_type import singleton_type

# 临时将项目路径加入环境变量，便于脚本方式运行
cpath_current = os.path.dirname(os.path.dirname(__file__))
cpath = os.path.abspath(os.path.join(cpath_current, os.pardir))
sys.path.append(cpath)
proxy_filename = os.path.join(cpath_current, 'config', 'proxy.txt')

__author__ = 'myh '
__date__ = '2026/06/21 '


class proxys(metaclass=singleton_type):
    """
    代理池管理。
    - 从 config/proxy.txt 读取代理；留空即走直连
    - 不做健康检查（上层调用方会在失败时标记坏代理）
    """

    def __init__(self):
        self.data = []
        try:
            with open(proxy_filename, "r") as file:
                for line in file:
                    line = line.strip()
                    # 空行 / 注释 行 跳过
                    if not line or line.startswith('#'):
                        continue
                    self.data.append(line)
        except Exception:
            # 文件不存在也属于"直连模式"，无需报错
            pass
        self.data = list(set(self.data))  # 去重

    def get_data(self):
        return self.data

    def get_proxies(self):
        """返回 requests 可用的 proxies dict；无代理时返回 None"""
        if not self.data:
            return None
        return {"http": self.data[0], "https": self.data[0]}
