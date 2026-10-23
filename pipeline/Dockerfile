FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HF_HUB_DISABLE_TELEMETRY=1 \
    DATA_DIR=/app/data \
    SEEDS_DIR=/app/seeds

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pipeline/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY pipeline ./pipeline
COPY seeds ./seeds

CMD ["python", "-m", "pipeline.orchestration.flows"]
