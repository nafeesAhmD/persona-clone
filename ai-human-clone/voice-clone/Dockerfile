FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_DEFAULT_TIMEOUT=300 \
    PIP_RETRIES=10 \
    HF_HOME=/root/.cache/huggingface \
    HF_HUB_DISABLE_TELEMETRY=1 \
    VOICE_DATA_DIR=/data/voices

WORKDIR /app

COPY requirements.txt .
# Dependencies first (cached layer), then chatterbox-tts without its deps so
# the gradio demo UI it pins is not installed. The BuildKit cache mount keeps
# already-downloaded wheels across retries on slow networks without adding
# them to the image.
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt \
    && pip install --no-deps chatterbox-tts==0.1.7

COPY app.py model.py audio.py ./

RUN mkdir -p /data/voices

EXPOSE 8100

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=4)" || exit 1

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8100", "--workers", "1", "--no-access-log"]
