FROM python:3.11-slim

# 设置工作目录
WORKDIR /app

# 设置Docker日志配置
ENV DOCKER_LOG_MAX_SIZE=10m
ENV DOCKER_LOG_MAX_FILE=3

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    tzdata \
    && ln -fs /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && apt-get install -y \
    ffmpeg \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 创建临时文件目录
RUN mkdir -p /app/temp

# 复制应用代码
COPY . .

# 设置环境变量
ENV PYTHONUNBUFFERED=1

# 启动命令
CMD ["python", "main.py"]
