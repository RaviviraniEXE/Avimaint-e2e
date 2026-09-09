FROM node:22-bookworm-slim AS frontend-build
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.11-slim AS runtime
RUN useradd --create-home --uid 1000 appuser
RUN mkdir -p /data && chown appuser:appuser /data
WORKDIR /app
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r /app/backend/requirements.txt
COPY --chown=appuser:appuser backend/ /app/backend/
COPY --chown=appuser:appuser data/ /app/data/
COPY --chown=appuser:appuser models/ /app/models/
COPY --chown=appuser:appuser config/ /app/config/
COPY --from=frontend-build --chown=appuser:appuser /build/dist/ /app/frontend/dist/
ENV PYTHONPATH=/app/backend \
    AVIMAINT_RUNTIME_PROFILE=frozen_artifacts \
    AVIMAINT_FEEDBACK_PATH=/data/feedback.jsonl \
    PYTHONUNBUFFERED=1
EXPOSE 7860
USER appuser
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/api/v1/health', timeout=5).read()"]
CMD ["uvicorn", "app.main:app", "--app-dir", "/app/backend", "--host", "0.0.0.0", "--port", "7860", "--workers", "1"]
