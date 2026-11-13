# Gateway image. Build context is the repo root (it needs engine/ and store/):
#   docker build -f gateway/Dockerfile .
FROM docker.io/library/python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY pyproject.toml README.md ./
COPY gateway ./gateway
COPY engine ./engine
COPY store ./store
COPY agent ./agent
COPY signals ./signals
RUN pip install --no-cache-dir . && useradd --system --uid 10001 app
USER app
EXPOSE 8000
# Keys come from the server's .env at run time (VALIO_API_KEY, MONGODB_URI,
# GATEWAY_AGENT_TOKEN, GATEWAY_HUMAN_TOKEN), never from the image.
CMD ["two-brothers-gateway"]
