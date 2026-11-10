FROM python:3.11-slim

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Cai dat thu vien Python va Chromium cung cac OS dependencies cho Playwright
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps --only-shell chromium \
    && rm -rf /var/lib/apt/lists/*

COPY . .

EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
