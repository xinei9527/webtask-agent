FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV WEBTASK_HEADLESS=true
ENV WEBTASK_DB_PATH=/app/data/webtask_agent.db

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
