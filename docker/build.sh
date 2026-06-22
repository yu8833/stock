#!/usr/bin/env bash
# 构建 instock 镜像
# 用法：
#   cd /path/to/InStock          # 进入项目根目录
#   ./docker/build.sh [TAG]
#
# 说明：
#   - 默认 TAG=latest；可显式指定，例如：./docker/build.sh 2025.01
#   - 不会自动 docker push，需要时可手动：docker push <image>:<tag>
#   - 构建上下文 = 项目根目录；Dockerfile = docker/Dockerfile
#
# 常见问题：
#   1) "ta-lib 下载失败 / configure 失败"：检查网络，必要时在 Dockerfile 第 2 步
#      把下载源改成 ta-lib-0.4.0-src.tar.gz 的备用直链。
#   2) "docker: 命令不存在"：先安装 Docker Desktop / Docker Engine。

set -euo pipefail

cd "$(dirname "$0")/.." || exit 1
PROJECT_ROOT="$(pwd)"
echo "项目根目录: ${PROJECT_ROOT}"

IMAGE_NAME="${IMAGE_NAME:-instock}"
TAG="${1:-latest}"

echo "开始构建镜像: ${IMAGE_NAME}:${TAG}  (上下文=${PROJECT_ROOT})"
docker build -f docker/Dockerfile \
    -t "${IMAGE_NAME}:${TAG}" \
    -t "${IMAGE_NAME}:latest" \
    "${PROJECT_ROOT}"

echo
echo "构建完成！"
echo "   镜像: ${IMAGE_NAME}:${TAG}"
echo "   启动: docker compose -f docker/docker-compose.yml up -d --build"
echo "   推送（可选）: docker push ${IMAGE_NAME}:${TAG}"
