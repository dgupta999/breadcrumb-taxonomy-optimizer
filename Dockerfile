# ---------- 1. build the React frontend ----------
FROM node:20-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 2. Python API + worker + crawler ----------
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    DATA_DIR=/app/backend/data
WORKDIR /app/backend
COPY backend/requirements.txt ./
# Competitor data comes from uploaded CSVs, so no headless browser is installed
# (keeps the image small for Render's free plan).
RUN pip install -r requirements.txt
COPY backend/app ./app
COPY sample_data /app/sample_data
COPY --from=web /web/dist /app/frontend/dist
EXPOSE 8000
# Render/Railway/Fly inject $PORT
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
