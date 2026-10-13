# SesKlon — tek imaj: React arayüzü + FastAPI + Chatterbox Multilingual V3.
#
#   GPU (NVIDIA):  docker compose up -d --build
#   Yalnız CPU:    docker compose -f docker-compose.cpu.yml up -d --build
#
# Build argümanları:
#   TORCH_INDEX    Boşsa PyTorch, Chatterbox'ın bağımlılığı olarak PyPI'dan gelir (Linux'ta CUDA'lı, ~2,5 GB+).
#                  CPU imajı için https://download.pytorch.org/whl/cpu verilir: CUDA kütüphaneleri inmez, imaj küçülür.
#   TORCH_VERSION  TORCH_INDEX kullanılırken kurulacak sürüm. Chatterbox'ın sabitlediği sürümle AYNI olmalı
#                  (şu an torch==2.6.0); farklı olursa pip, Chatterbox'ı kurarken PyTorch'u PyPI'dan yeniden indirir.

# ---- 1) Arayüzü derle ----
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
# Kaynaklar ayrı katmanda: yalnızca arayüz değişince yeniden derlenir. Host'tan gelebilecek node_modules/dist
# (başka platformun ikili dosyaları) kullanılmaz; bağımlılıklar yukarıdaki npm ci katmanından gelir.
COPY frontend/ /tmp/frontend/
RUN rm -rf /tmp/frontend/node_modules /tmp/frontend/dist \
    && cp -a /tmp/frontend/. ./ \
    && npm run build

# ---- 2) Backend + model çalışma zamanı ----
# NVIDIA GPU: host'ta nvidia-container-toolkit kurulu olmalı. CPU'da da çalışır (yavaş).
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DATA_DIR=/data FRONTEND_DIST=/app/frontend/dist \
    HF_HOME=/data/hf-cache
# ffmpeg: dönüştürme, MP3, tempo, mastering (loudnorm). Debian paketi rubberband filtresiyle derlidir
# (librubberband bağımlılık olarak gelir). libsndfile1: soundfile. git: Chatterbox V3 GitHub'dan kurulur.
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 git \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# PyTorch'u requirements'tan ÖNCE ve ayrı katmanda kur (requirements değişse de bu katman önbellekte kalır).
ARG TORCH_INDEX=""
ARG TORCH_VERSION=2.6.0
RUN if [ -n "$TORCH_INDEX" ]; then \
        pip install "torch==${TORCH_VERSION}" "torchaudio==${TORCH_VERSION}" --index-url "$TORCH_INDEX"; \
    fi

# Bağımlılıklar kaynak koddan önce: kod değişince pip katmanı yeniden çalışmaz.
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt

# Yalnızca uygulama kodu kopyalanır; backend/data (yerel sesler, çıktılar, veritabanı) imaja girmez.
COPY backend/app/ backend/app/
COPY --from=web /web/dist frontend/dist
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=120s --retries=5 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status==200 else 1)"
WORKDIR /app/backend
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
