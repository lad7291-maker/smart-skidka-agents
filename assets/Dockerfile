# Dockerfile для Оркестратора smart-skidka-agents
FROM python:3.12-slim-bookworm

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Python-зависимости
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Приложение
COPY scripts/ ./scripts/
COPY references/ ./references/
COPY configs/ ./configs/

# Логи
RUN mkdir -p /app/logs

# Запуск
CMD ["python", "-m", "scripts.orchestrator"]
