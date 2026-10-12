FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set Docker log configuration
ENV DOCKER_LOG_MAX_SIZE=10m
ENV DOCKER_LOG_MAX_FILE=3

# Install system dependencies
RUN apt-get update && apt-get install -y \
    tzdata \
    && ln -fs /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && dpkg-reconfigure -f noninteractive tzdata \
    && apt-get install -y \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create temp directory
RUN mkdir -p /app/temp

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Start command
CMD ["python", "main.py"]
