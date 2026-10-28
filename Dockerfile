# syntax=docker/dockerfile:1

# ---- Frontend: Vite/React production bundle -------------------------------
FROM node:22-slim AS frontend

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- Runtime: FastAPI API plus the built SPA ------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HUB_DISABLE_TELEMETRY=1 \
    HF_HOME=/app/data/.cache/huggingface \
    XDG_CACHE_HOME=/app/data/.cache \
    PYTHONPATH=/app \
    ENVIRONMENT=production \
    DATA_DIR=/app/data \
    SEEDS_DIR=/app/seeds \
    FRONTEND_DIST=/app/frontend/dist \
    PORT=8000

RUN apt-get update \
    && apt-get install -y --no-install-recommends gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 atlas \
    && useradd --uid 10001 --gid atlas --no-create-home \
       --shell /usr/sbin/nologin atlas \
    && mkdir -p /app/data/auth /app/data/.cache/huggingface /app/frontend

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/app /app/app
# Curated outlet/subreddit seeds are tracked in git and required at runtime by
# /v1/outlets. Keep seeds/ out of .dockerignore or the endpoint returns empty.
COPY seeds /app/seeds
COPY --from=frontend /build/frontend/dist /app/frontend/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod 0755 /usr/local/bin/docker-entrypoint.sh \
    && chown -R atlas:atlas /app/data

EXPOSE 8000

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
# Never enable Uvicorn --proxy-headers / --forwarded-allow-ips: trusting a
# client-supplied X-Forwarded-For lets anyone spoof the client IP. Uvicorn
# defaults proxy headers to on, so disable them explicitly. Render/Cloudflare
# metadata is handled in app/client_ip.py, gated by TRUST_PROXY_HEADERS, which
# reads only the platform-set CF-Connecting-IP header.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --http h11 --no-proxy-headers"]
