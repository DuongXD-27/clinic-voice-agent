FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 8000

# Một worker: session đang lưu trong bộ nhớ process (docs/core-logic-plan.md, M2)
CMD ["uvicorn", "callbot.transports.http.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
