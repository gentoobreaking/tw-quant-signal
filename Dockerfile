# === Stage 1: Build Frontend ===
FROM node:20-alpine AS frontend-builder

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# === Stage 2: Build tw-quant-mcp ===
FROM golang:1.22-alpine AS mcp-builder

WORKDIR /app/tw-quant-mcp
COPY tw-quant-mcp/go.mod tw-quant-mcp/go.sum ./
RUN go mod download
COPY tw-quant-mcp/ ./
RUN CGO_ENABLED=0 go build -ldflags "-X main.version=docker" -o /tw-quant-mcp ./cmd/mcp-server

# === Stage 3: Python API + Serve Static ===
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates && \
    update-ca-certificates && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --force-reinstall urllib3 requests certifi

WORKDIR /app

COPY pyproject.toml ./
COPY src/ ./src/
COPY configs/ ./configs/
COPY config.json ./
COPY scripts/ ./scripts/
RUN pip install --no-cache-dir -e .

COPY --from=frontend-builder /app/frontend/dist/ ./frontend/dist/
COPY --from=mcp-builder /tw-quant-mcp /app/tw-quant-mcp

EXPOSE 8000

CMD ["uvicorn", "tw_quant_signal.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
