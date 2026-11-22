FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 RAG_DB_PATH=/app/data/flipper_rag.sqlite3
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY sources.json ./
COPY knowledge ./knowledge
COPY benchmarks ./benchmarks
RUN mkdir -p data
EXPOSE 8000
CMD ["uvicorn", "flipper_rag.api:app", "--host", "0.0.0.0", "--port", "8000"]
