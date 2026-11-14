# The Telegram bot of one kitchen (#1330). Build context is the repo root:
#   docker build -f bot/Dockerfile .
# It is a client of the gateway API: it has no database and no model. Keys come from the
# server's .env at run time (TELEGRAM_BOT, BOT_KITCHEN_TOKEN), never from the image.
FROM docker.io/library/python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BOT_DATA_DIR=/data
RUN pip install --no-cache-dir "httpx>=0.28,<1" "python-dotenv>=1,<2" "tzdata>=2025.2" \
    && useradd --system --uid 10001 --create-home app \
    && mkdir /data && chown app /data
COPY bot/__init__.py bot/app.py bot/clients.py bot/links.py bot/render.py ./bot/
USER app
CMD ["python", "-m", "bot.app"]
