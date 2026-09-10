FROM node:22-bookworm-slim AS contract-runtime
FROM python:3.12-slim-bookworm

# Runs the bundled Zod validator locally; no npm install or second service.
COPY --from=contract-runtime /usr/local/bin/node /usr/local/bin/node

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=4s --retries=10 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)" || exit 1
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
