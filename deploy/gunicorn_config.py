# -*- coding: utf-8 -*-
"""Gunicorn 生产环境配置"""

import multiprocessing
import os

# 绑定地址（Nginx 反向代理，只监听本地）
bind = "127.0.0.1:5000"

# 工作进程数 = CPU核心数 * 2 + 1
workers = multiprocessing.cpu_count() * 2 + 1

# 工作模式（gevent 适合 IO 密集型）
worker_class = "gthread"
threads = 4

# 超时设置（研判接口可能耗时较长）
timeout = 120
graceful_timeout = 30
keepalive = 5

# 最大请求数后重启 worker（防内存泄漏）
max_requests = 2000
max_requests_jitter = 200

# 日志
accesslog = "/var/log/sanfang/access.log"
errorlog = "/var/log/sanfang/error.log"
loglevel = "info"

# 进程名
proc_name = "sanfang"

# 预加载应用（节省内存）
preload_app = True

# 环境变量
raw_env = [
    "FLASK_ENV=production",
]
