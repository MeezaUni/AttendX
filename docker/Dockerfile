# AttendX: one image serving the React SPA and the FastAPI API on a single origin.
# Model weights and the database are NOT baked in: models are mounted read-only at /models and
# all runtime data (SQLite DB, template key) lives in the /data volume.

# ---------------------------------------------------------------- frontend build
FROM node:24-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------- runtime
FROM python:3.12-slim
ARG TORCH_VARIANT=cu128
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    ATTENDX_DATA_DIR=/data ATTENDX_MODELS_DIR=/models ATTENDX_STATIC_DIR=/app/frontend/dist
# libGL/glib: OpenCV (pulled in by MediaPipe); libgomp: onnxruntime / torch CPU threads
RUN apt-get update \
 && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
 && rm -rf /var/lib/apt/lists/*
RUN pip install torch --index-url https://download.pytorch.org/whl/${TORCH_VARIANT}
WORKDIR /app/backend
COPY backend/pyproject.toml ./
COPY backend/attendx ./attendx
RUN pip install .
# MediaPipe's Linux wheel links EGL/GLES even when it runs on the CPU (kept in a late layer so
# the large torch layer above stays cached)
RUN apt-get update \
 && apt-get install -y --no-install-recommends libegl1 libgles2 \
 && rm -rf /var/lib/apt/lists/*
COPY --from=web /web/dist /app/frontend/dist
RUN useradd --system --uid 10001 --home /data attendx && mkdir -p /data /models && chown attendx /data
USER attendx
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["attendx", "serve", "--host", "0.0.0.0", "--port", "8000"]
