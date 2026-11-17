
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VIDEO_MIXER_DATA_DIR=/data \
    OMP_NUM_THREADS=4 \
    MKL_NUM_THREADS=4 \
    TORCH_HOME=/root/.cache/torch \
    CMAKE_POLICY_VERSION_MINIMUM=3.5

WORKDIR /app

COPY requirements.txt .

# 安装系统依赖
RUN set -eux; \
    sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
        /etc/apt/sources.list.d/debian.sources; \
    apt-get update -o Acquire::Retries=5; \
    apt-get install -y \
        -o Acquire::Retries=5 \
        --no-install-recommends \
        ffmpeg \
        ca-certificates \
        libgomp1 \
        libopus-dev \
        build-essential \
        pkg-config \
        cmake; \
    \
    echo "===== Opus 检查 ====="; \
    pkg-config --modversion opus; \
    \
    echo "===== 安装 PyTorch CPU 版本 ====="; \
    pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        torch; \
    \
    echo "===== 安装 Demucs ====="; \
    pip install --no-cache-dir -r requirements.txt; \
    \
    rm -rf /var/lib/apt/lists/*

COPY main.py .

ENTRYPOINT ["python", "main.py"]
