# Dockerfile — API DockDB-CNPJ
# Author: Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>
FROM python:3.12-slim

LABEL org.opencontainers.image.authors="Matheus Cavalcanti Pestana <matheus.pestana@fgv.br>"
LABEL org.opencontainers.image.title="DockDB-CNPJ API"
LABEL org.opencontainers.image.description="API de consulta CNPJ sobre DuckDB"

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

COPY src/ ./src/
COPY api/ ./api/

ENV PYTHONPATH=/app/src
ENV CNPJ_DB_PATH=/data/cnpj.duckdb

EXPOSE 8000

# Bind interno do container; o host decide a exposição (compose usa 127.0.0.1)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
