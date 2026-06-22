# 基础镜像：python 3.11 (debian bullseye)
# https://hub.docker.com/_/python/tags?page=1&name=3.11-slim-bullseye
FROM docker.io/python:3.11-slim-bullseye

LABEL maintainer="myh"

# 语言 / 时区 / 工作目录
ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PYTHONPATH=/data/InStock \
    TZ=Asia/Shanghai

EXPOSE 9988 9001

# ---------- 1) 换国内 apt 源（加速 debian 包下载） ----------
# 同时安装系统依赖：cron、gcc、make、pkg-config、ta-lib 编译环境等
RUN sed -i "s@http://\(deb\|security\).debian.org@https://mirrors.aliyun.com@g" /etc/apt/sources.list && \
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime && \
    echo "Asia/Shanghai" > /etc/timezone && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
        cron gcc g++ make python3-dev default-libmysqlclient-dev \
        build-essential pkg-config curl ca-certificates supervisor \
        libglib2.0-0 libsm6 libxrender1 libxext6 && \
    pip3 install --no-cache-dir --upgrade pip setuptools wheel && \
    pip3 config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip3 config set install.trusted-host mirrors.aliyun.com

# ---------- 2) 安装 TA-Lib（C 库 + Python 绑定） ----------
# 注意：ta-lib 的 tools/gen_code 在并行 make 下存在竞态（.Tpo/.Po 文件同时被两个进程操作），
# 所以这里先并行构建库，再用 make -C 手动单线程完成 tools 目录，最后安装。
RUN mkdir -p /tmp/ta-lib-src && \
    cd /tmp/ta-lib-src && \
    (curl -fsSL -o ta-lib.tar.gz "https://udomain.dl.sourceforge.net/project/ta-lib/ta-lib/0.4.0/ta-lib-0.4.0-src.tar.gz" || \
     curl -fsSL -o ta-lib.tar.gz "https://sourceforge.net/projects/ta-lib/files/ta-lib/0.4.0/ta-lib-0.4.0-src.tar.gz/download" -L -A "curl/8") && \
    tar -xzf ta-lib.tar.gz --strip-components=1 && \
    ./configure --prefix=/usr --build=$(dpkg-architecture -qDEB_BUILD_GNU_TYPE) || \
    ./configure --prefix=/usr && \
    # 先并行构建 lib（ta_common / ta_abstract / ta_func，这些是并行安全的）
    make -C ta_common -j"$(nproc)" && \
    make -C ta_abstract -j"$(nproc)" && \
    make -C ta_func -j"$(nproc)" && \
    # 顶层 make install 会自动完成剩余目标（tools 单线程构建）并安装
    make install && \
    ldconfig && \
    rm -rf /tmp/ta-lib-src /tmp/*.tar.gz 2>/dev/null; true

# ---------- 3) 先 COPY requirements，单独安装依赖，最大化 Docker 缓存 ----------
WORKDIR /data
COPY requirements.txt /data/requirements.txt

# 先装除 TA-Lib 以外的依赖；TA-Lib 单独装可避免前面失败后重新下载全部依赖。
# 注意：pycryptodome 与 Crypto 二选一，不重复装；requirements.txt 中用 pycryptodome。
RUN pip3 install --no-cache-dir -r /data/requirements.txt

# ---------- 4) 把项目源码复制进来 ----------
# docker 目录放的是镜像构建脚本，项目根目录的 instock/、supervisor/、cron/ 是真正的软件。
# Docker 构建时需把整个项目目录（除去 .git/、__pycache__/ 等）复制到 /data/InStock。
COPY . /data/InStock/

# supervisor 配置 + 启动脚本权限
RUN rm -f /etc/supervisor/conf.d/*.conf && \
    mkdir -p /data/InStock/instock/log /data/InStock/instock/cache && \
    chmod 755 /data/InStock/instock/bin/run_*.sh && \
    if [ -d /data/InStock/cron/cron.hourly ]; then chmod 755 /data/InStock/cron/cron.hourly/*; fi && \
    if [ -d /data/InStock/cron/cron.workdayly ]; then chmod 755 /data/InStock/cron/cron.workdayly/*; fi && \
    if [ -d /data/InStock/cron/cron.monthly ]; then chmod 755 /data/InStock/cron/cron.monthly/*; fi

# ---------- 5) 配置 cron 计划任务 ----------
RUN mkdir -p /etc/cron.hourly /etc/cron.workdayly /etc/cron.monthly && \
    if [ -d /data/InStock/cron/cron.hourly ]; then cp -f /data/InStock/cron/cron.hourly/* /etc/cron.hourly/; fi && \
    if [ -d /data/InStock/cron/cron.workdayly ]; then cp -f /data/InStock/cron/cron.workdayly/* /etc/cron.workdayly/; fi && \
    if [ -d /data/InStock/cron/cron.monthly ]; then cp -f /data/InStock/cron/cron.monthly/* /etc/cron.monthly/; fi && \
    chmod 755 /etc/cron.hourly/* 2>/dev/null; chmod 755 /etc/cron.workdayly/* 2>/dev/null; chmod 755 /etc/cron.monthly/* 2>/dev/null && \
    printf 'SHELL=/bin/sh\n\
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin\n\
# min hour day month weekday command\n\
*/30 9,10,11,13,14,15 * * 1-5 /bin/run-parts /etc/cron.hourly\n\
30 17 * * 1-5 /bin/run-parts /etc/cron.workdayly\n\
30 10 * * 3,6 /bin/run-parts /etc/cron.monthly\n' > /var/spool/cron/crontabs/root && \
    chmod 600 /var/spool/cron/crontabs/root

# 清理 apt 缓存，减小镜像体积
RUN apt-get --purge remove -y curl 2>/dev/null; \
    rm -rf /root/.cache/* /var/lib/apt/lists/* && apt-get clean -y && apt-get autoclean -y 2>/dev/null

ENTRYPOINT ["supervisord", "-n", "-c", "/data/InStock/supervisor/supervisord.conf"]
