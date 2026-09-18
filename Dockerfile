FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 8000

ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "exec uvicorn callbot.transports.http.main:app --host 0.0.0.0 --port 8000 --workers \"$WEB_CONCURRENCY\""]
