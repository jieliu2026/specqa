# syntax=docker/dockerfile:1
# specqa 容器化（T2.3，20261118）——两阶段：前端构建 → 运行时
# 无 key 起测试态（health ok/界面可看）；有 key 传 BAILIAN_TOKEN_PLAN_API_KEY 全功能
FROM node:22-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --registry=https://registry.npmmirror.com --silent
COPY frontend/ .
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
COPY . .
COPY --from=frontend /app/frontend/dist ./frontend/dist
EXPOSE 8000
CMD ["python", "serve.py"]
