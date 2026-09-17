FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 8000

# Phiên nằm trong PostgreSQL (SESSION_DATABASE_URL) nên chạy được nhiều worker.
# Migration chạy MỘT lần trước khi khởi động worker: `python -m callbot.engine.session.postgres.migrate`
# (service `migrate` trong docker-compose).
ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "exec uvicorn callbot.transports.http.main:app --host 0.0.0.0 --port 8000 --workers ${WEB_CONCURRENCY}"]
