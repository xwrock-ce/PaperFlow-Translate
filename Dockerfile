FROM node:20-bookworm-slim AS frontend-builder

WORKDIR /frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

EXPOSE 7860

ENV PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install --no-install-recommends -y \
        build-essential \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 && \
    rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md uv.lock ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY . .
COPY --from=frontend-builder /frontend/dist ./frontend/dist

RUN uv pip install --system --no-cache . && \
    uv pip install --system --no-cache --compile-bytecode -U babeldoc "pymupdf<1.25.3" && \
    babeldoc --version && \
    babeldoc --warmup

RUN pdf2zh --version

CMD ["pdf2zh", "--gui", "--server-host", "0.0.0.0"]
