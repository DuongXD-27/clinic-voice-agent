FROM python:3.12-slim

WORKDIR /app

# Layer dependency: chỉ build lại khi pyproject.toml đổi. Package stub để hatchling build được
# trước khi có src; code thật được cài đè ở bước sau với --no-deps.
COPY pyproject.toml ./
RUN mkdir -p src/callbot src/llm \
    && touch src/callbot/__init__.py src/llm/__init__.py \
    && pip install --no-cache-dir . \
    && rm -rf src

COPY src ./src

RUN pip install --no-cache-dir --no-deps --force-reinstall .

EXPOSE 8000

ENV WEB_CONCURRENCY=2
CMD ["sh", "-c", "exec uvicorn callbot.transports.http.main:app --host 0.0.0.0 --port 8000 --workers \"$WEB_CONCURRENCY\""]
