# Руководство по деплою smart-skidka-agents

Полная пошаговая инструкция по развертыванию системы агентов автоматизации на собственном сервере. Читайте последовательно — каждый шаг проверен и содержит проверку результата.

---

## Содержание

1. [Требования к серверу](#1-Требования-к-серверу)
2. [Выбор хостинга](#2-Выбор-хостинга)
3. [Подготовка сервера](#3-Подготовка-сервера)
4. [Клонирование и настройка](#4-Клонирование-и-настройка)
5. [Полный .env файл с пояснениями](#5-Полный-env-файл-с-пояснениями)
6. [Запуск](#6-Запуск)
7. [Проверка работы](#7-Проверка-работы)
8. [Настройка Telegram бота](#8-Настройка-telegram-бота)
9. [Получение API ключей](#9-Получение-api-ключей)
10. [Мониторинг](#10-Мониторинг)
11. [Автозапуск при перезагрузке](#11-Автозапуск-при-перезагрузке)
12. [Обновление системы](#12-Обновление-системы)
13. [Troubleshooting](#13-troubleshooting)
14. [Безопасность](#14-Безопасность)

---

## 1. Требования к серверу

### Минимальные (для теста)

| Ресурс | Значение |
|--------|----------|
| CPU    | 2 ядра   |
| RAM    | 4 GB     |
| Диск   | 20 GB SSD|
| Сеть   | 100 Мбит/с|

### Рекомендуемые (для стабильной работы)

| Ресурс | Значение |
|--------|----------|
| CPU    | 4 ядра   |
| RAM    | 8 GB     |
| Диск   | 50 GB SSD|
| Сеть   | 200 Мбит/с|

### Операционная система

```
Ubuntu 22.04 LTS (Jammy Jellyfish)
```

> Почему именно 22.04 LTS: пятилетняя поддержка, стабильные пакеты, Docker работает без проблем. 24.04 тоже подойдет, но 22.04 проверена лично.

### Требуемые порты

| Порт  | Назначение           | Кто обращается     |
|-------|----------------------|--------------------|
| 22    | SSH (управление)     | Только вы          |
| 80    | HTTP (опционально)   | Внешний мир        |
| 443   | HTTPS (опционально)  | Внешний мир        |
| 5432  | PostgreSQL           | Только Docker      |
| 6379  | Redis                | Только Docker      |

> Все внутренние сервисы (PostgreSQL, Redis) работают только внутри Docker-сети и не доступны снаружи.

---

## 2. Выбор хостинга

| Хостинг | Цена/мес | Конфигурация | Плюсы | Минусы | Рекомендация |
|---------|----------|-------------|-------|--------|--------------|
| **Hetzner CX21** | ~€6.29 (~650₽) | 2 vCPU, 4GB, 40GB SSD | Дёшево, стабильно, немецкие дата-центры, простая панель | Не РФ, нужна карта для оплаты | Для бюджетного старта |
| **Hetzner CPX21** | ~€8.90 (~920₽) | 4 vCPU, 8GB, 80GB SSD | Лучшая цена за ресурсы, AMD EPYC | Не РФ | **Лучший выбор** |
| **Timeweb Cloud** | от 500₽ | 2 vCPU, 4GB, 30GB SSD | РФ компания, русская поддержка, оплата картой РФ | Меньше ресурсов за цену, новее на рынке | Для тех кто хочет РФ |
| **Yandex Cloud** | от 1200₽ | 2 vCPU, 4GB, 30GB SSD | Интеграция с Яндекс, 4000₽ стартовый грант | Сложнее настроить, обертки вокруг всего | Если уже используете Яндекс |
| **Selectel** | от 800₽ | 2 vCPU, 4GB, 30GB SSD | РФ, отличная сеть, надежный | Меньше документации для новичков | Для продакшена в РФ |

### Пошаговая покупка сервера (на примере Hetzner)

1. Перейдите на [hetzner.com/cloud](https://hetzner.com/cloud)
2. Зарегистрируйтесь (требуется email + карта)
3. Нажмите **Add Server**
4. Выберите: Location = Helsinki, Type = CPX21 (4 vCPU, 8GB)
5. Image = Ubuntu 22.04
6. SSH Key = добавьте свой публичный ключ (cat ~/.ssh/id_rsa.pub)
7. Нажмите **Create & Buy**
8. Через 30 секунд сервер готов — скопируйте IP адрес

### Подключение к серверу

```bash
ssh root@<IP_СЕРВЕРА>
```

Если используете ключ:
```bash
ssh -i ~/.ssh/id_rsa root@<IP_СЕРВЕРА>
```

**Проверка подключения — вы должны увидеть:**
```
Welcome to Ubuntu 22.04.5 LTS (GNU/Linux 5.15.0 x86_64)
root@ubuntu-2gb-hel1-1:~# 
```

---

## 3. Подготовка сервера

Выполняйте команды последовательно. После каждого блока — проверка.

### 3.1 Обновление системы

```bash
apt update && apt upgrade -y
```

**Проверка — последние строки вывода должны быть:**
```
0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded
```

### 3.2 Установка базовых утилит

```bash
apt install -y curl wget git vim htop mc ufw software-properties-common apt-transport-https ca-certificates gnupg lsb-release
```

**Проверка:**
```bash
git --version
curl --version
```

Ожидаемый вывод (версии могут отличаться):
```
git version 2.34.1
curl 7.81.0
```

### 3.3 Установка Docker

```bash
# Удаление старых версий (если есть)
apt remove -y docker docker-engine docker.io containerd runc 2>/dev/null || true

# Добавление официального GPG-ключа Docker
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

# Добавление репозитория
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list

# Обновление и установка
apt update
apt install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
```

**Проверка:**
```bash
docker --version
docker compose version
```

Ожидаемый вывод:
```
Docker version 27.x.x, build xxxxxxx
Docker Compose version v2.x.x
```

### 3.4 Запуск Docker и добавление пользователя

```bash
# Запуск и автозагрузка
systemctl start docker
systemctl enable docker

# Добавление текущего пользователя в группу docker (чтобы не писать sudo)
usermod -aG docker $USER
```

**Применение группы (без перелогина):**
```bash
newgrp docker
```

**Проверка — выполните без sudo:**
```bash
docker ps
```

Ожидаемый вывод:
```
CONTAINER ID   IMAGE   COMMAND   CREATED   STATUS   PORTS   NAMES
```
(пустая таблица — это нормально, главное что без ошибок)

### 3.5 Настройка часового пояса

```bash
timedatectl set-timezone Europe/Moscow
timedatectl status
```

Ожидаемый вывод:
```
Time zone: Europe/Moscow (MSK, +0300)
System clock synchronized: yes
NTP service: active
```

### 3.6 Настройка фаервола (UFW)

```bash
# Включение UFW
ufw default deny incoming
ufw default allow outgoing

# Разрешение SSH (иначе потеряете доступ!)
ufw allow 22/tcp

# Разрешение HTTP/HTTPS (если нужен веб)
ufw allow 80/tcp
ufw allow 443/tcp

# Включение
ufw --force enable
```

**Проверка:**
```bash
ufw status verbose
```

Ожидаемый вывод:
```
Status: active
Logging: on (low)
Default: deny (incoming), allow (outgoing), disabled (routed)
New profiles: skip

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW IN    Anywhere
80/tcp                     ALLOW IN    Anywhere
443/tcp                    ALLOW IN    Anywhere
```

---

## 4. Клонирование и настройка

### 4.1 Создание директории проекта

```bash
mkdir -p /opt/smart-skidka-agents
cd /opt/smart-skidka-agents
pwd
```

Ожидаемый вывод:
```
/opt/smart-skidka-agents
```

### 4.2 Размещение файлов проекта

Есть два способа получить файлы проекта:

**Способ A: Git clone (если репозиторий доступен)**

```bash
cd /opt/smart-skidka-agents
git clone <URL_РЕПОЗИТОРИЯ> .
```

**Способ B: Загрузка skill-файла (архива)**

```bash
cd /opt/smart-skidka-agents
# Загрузите архив на сервер (scp с локальной машины)
# scp smart-skidka-agents.zip root@<IP>:/opt/smart-skidka-agents/
apt install -y unzip
unzip smart-skidka-agents.zip -d .
```

**Способ C: Ручное создание структуры**

```bashncd /opt/smart-skidka-agents
mkdir -p src/agents src/tools src/db src/api logs data/postgres data/redis
```

### 4.3 Проверка структуры

```bash
tree -L 2 /opt/smart-skidka-agents 2>/dev/null || find /opt/smart-skidka-agents -maxdepth 2 -type f | head -30
```

Ожидаемая структура:
```
/opt/smart-skidka-agents/
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .env
├── src/
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── orchestrator.py
│   │   ├── discount_searcher.py
│   │   ├── report_generator.py
│   │   └── data_updater.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── llm_client.py
│   │   ├── scraper.py
│   │   └── telegram_notifier.py
│   ├── db/
│   │   ├── __init__.py
│   │   └── models.py
│   └── api/
│       ├── __init__.py
│       └── routes.py
├── logs/
└── data/
    ├── postgres/
    └── redis/
```

### 4.4 Создание docker-compose.yml

Если файла нет — создайте его:

```yaml
version: "3.8"

services:
  postgres:
    image: postgres:16-alpine
    container_name: skidka-postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-skidka}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-skidka_secret_123}
      POSTGRES_DB: ${POSTGRES_DB:-skidka_db}
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
    ports:
      - "127.0.0.1:5432:5432"
    networks:
      - skidka-network
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-skidka} -d ${POSTGRES_DB:-skidka_db}"]
      interval: 10s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: skidka-redis
    restart: unless-stopped
    command: redis-server --requirepass ${REDIS_PASSWORD:-redis_secret_123}
    volumes:
      - ./data/redis:/data
    ports:
      - "127.0.0.1:6379:6379"
    networks:
      - skidka-network
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5

  orchestrator:
    build: .
    container_name: skidka-orchestrator
    restart: unless-stopped
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - LLM_API_KEY=${LLM_API_KEY}
      - LLM_API_BASE=${LLM_API_BASE:-https://api.rrouter.ai/v1}
      - LLM_MODEL=${LLM_MODEL:-deepseek/deepseek-chat}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    volumes:
      - ./logs:/app/logs
    networks:
      - skidka-network
    command: python -m src.agents.orchestrator

  telegram-bot:
    build: .
    container_name: skidka-telegram-bot
    restart: unless-stopped
    depends_on:
      - postgres
      - redis
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    volumes:
      - ./logs:/app/logs
    networks:
      - skidka-network
    command: python -m src.tools.telegram_notifier

  discount-searcher:
    build: .
    container_name: skidka-discount-searcher
    restart: unless-stopped
    depends_on:
      - postgres
      - redis
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - LLM_API_KEY=${LLM_API_KEY}
      - LLM_API_BASE=${LLM_API_BASE:-https://api.rrouter.ai/v1}
      - LLM_MODEL=${LLM_MODEL:-deepseek/deepseek-chat}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    volumes:
      - ./logs:/app/logs
    networks:
      - skidka-network
    command: python -m src.agents.discount_searcher

  report-generator:
    build: .
    container_name: skidka-report-generator
    restart: unless-stopped
    depends_on:
      - postgres
      - redis
    environment:
      - DATABASE_URL=${DATABASE_URL}
      - REDIS_URL=${REDIS_URL}
      - LLM_API_KEY=${LLM_API_KEY}
      - LLM_API_BASE=${LLM_API_BASE:-https://api.rrouter.ai/v1}
      - LLM_MODEL=${LLM_MODEL:-deepseek/deepseek-chat}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - LOG_LEVEL=${LOG_LEVEL:-INFO}
    volumes:
      - ./logs:/app/logs
    networks:
      - skidka-network
    command: python -m src.agents.report_generator

networks:
  skidka-network:
    driver: bridge
```

Сохраните файл:
```bash
cat > /opt/smart-skidka-agents/docker-compose.yml << 'COMPOSE_EOF'
# Вставьте содержимое выше
COMPOSE_EOF
```

### 4.5 Создание Dockerfile

```dockerfile
FROM python:3.11-slim

WORKDIR /app

# Установка системных зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Копирование зависимостей
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование кода
COPY src/ ./src/

# Создание директории для логов
RUN mkdir -p /app/logs

# Переменные окружения
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.agents.orchestrator"]
```

Сохраните файл:
```bash
cat > /opt/smart-skidka-agents/Dockerfile << 'DOCKER_EOF'
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
RUN mkdir -p /app/logs

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

CMD ["python", "-m", "src.agents.orchestrator"]
DOCKER_EOF
```

### 4.6 Создание requirements.txt

```bash
cat > /opt/smart-skidka-agents/requirements.txt << 'REQ_EOF'
# Web
requests>=2.31.0
httpx>=0.27.0

# Telegram
python-telegram-bot>=21.0

# LLM / AI
openai>=1.30.0

# Database
SQLAlchemy>=2.0.0
psycopg2-binary>=2.9.9
alembic>=1.13.0

# Cache
redis>=5.0.0

# Environment
python-dotenv>=1.0.0

# Scheduling
APScheduler>=3.10.0

# Monitoring
prometheus-client>=0.20.0

# Utils
pydantic>=2.7.0
pydantic-settings>=2.2.0
tenacity>=8.3.0
beautifulsoup4>=4.12.0
lxml>=5.2.0
REQ_EOF
```

---

## 5. Полный .env файл с пояснениями

### 5.1 Создание файла

```bash
cd /opt/smart-skidka-agents
touch .env
chmod 600 .env  # Только владелец может читать
```

### 5.2 Полный пример .env

Скопируйте и заполните каждое значение:

```bash
cat > /opt/smart-skidka-agents/.env << 'ENV_EOF'
# ============================================================================
# ОСНОВНЫЕ НАСТРОЙКИ
# ============================================================================

# Уровень логирования: DEBUG | INFO | WARNING | ERROR
# DEBUG — все логи, много текста
# INFO — основные события (рекомендуется)
# WARNING | ERROR — только ошибки
LOG_LEVEL=INFO

# ============================================================================
# LLM (БОЛЬШАЯ ЯЗЫКОВАЯ МОДЕЛЬ) — ОБЯЗАТЕЛЬНО
# ============================================================================

# Ключ API для LLM
# Как получить: см. раздел 9.1 RouterAI или 9.2 DeepSeek
# Формат: sk-xxxxxxxx (для RouterAI) или sk-xxxxxxxx (для DeepSeek)
LLM_API_KEY=sk-or-v1-ВАШ_КЛЮЧ_СЮДА

# Базовый URL API
# Для RouterAI: https://api.rrouter.ai/v1
# Для DeepSeek: https://api.deepseek.com/v1
LLM_API_BASE=https://api.rrouter.ai/v1

# Название модели
# RouterAI: deepseek/deepseek-chat, anthropic/claude-3.5-sonnet, openai/gpt-4o
# DeepSeek: deepseek-chat
LLM_MODEL=deepseek/deepseek-chat

# ============================================================================
# TELEGRAM БОТ — ОБЯЗАТЕЛЬНО
# ============================================================================

# Токен бота от @BotFather
# Как получить: см. раздел 8.1
# Формат: 123456789:ABCdefGHIjklMNOpqrsTUVwxyz
TELEGRAM_BOT_TOKEN=123456789:ВАШ_ТОКЕН_СЮДА

# ID чата для уведомлений (это ваш личный ID)
# Как узнать: напишите @userinfobot, скопируйте число
# Формат: 123456789 (только цифры)
TELEGRAM_CHAT_ID=ВАШ_CHAT_ID_СЮДА

# ============================================================================
# БАЗА ДАННЫХ — Docker сам настраивает, но URL нужен для приложения
# ============================================================================

# PostgreSQL connection string
# Формат: postgresql://user:password@host:port/dbname
# В Docker используется имя сервиса вместо IP
POSTGRES_USER=skidka
POSTGRES_PASSWORD=skidka_secret_123
POSTGRES_DB=skidka_db
DATABASE_URL=postgresql://skidka:skidka_secret_123@postgres:5432/skidka_db

# ============================================================================
# REDIS — КЭШ И ОЧЕРЕДИ
# ============================================================================

# Redis connection string
# Формат: redis://:password@host:port/0
REDIS_PASSWORD=redis_secret_123
REDIS_URL=redis://:redis_secret_123@redis:6379/0

# ============================================================================
# ОПЦИОНАЛЬНЫЕ НАСТРОЙКИ
# ============================================================================

# Расписание запуска агентов (формат cron)
# Каждые 2 часа:
SCHEDULE_DISCOUNT_SEARCH=0 */2 * * *
# Каждые 4 часа:
SCHEDULE_REPORT_GENERATION=0 */4 * * *
# Каждый день в 9:00:
SCHEDULE_DAILY_DIGEST=0 9 * * *

# Таймауты запросов (секунды)
REQUEST_TIMEOUT=30
LLM_TIMEOUT=60

# Ограничения поиска
MAX_DISCOUNTS_PER_SEARCH=50
MAX_SEARCH_RESULTS=10

# Яндекс.Метрика (опционально, для аналитики)
# Как получить: см. раздел 9.3
YANDEX_METRIKA_TOKEN=
YANDEX_COUNTER_ID=
ENV_EOF
```

### 5.3 Критические переменные — что именно вписать

| Переменная | Куда вписать | Пример значения |
|------------|-------------|-----------------|
| `LLM_API_KEY` | Ключ от RouterAI или DeepSeek | `sk-a1b2c3d4e5f6...` |
| `TELEGRAM_BOT_TOKEN` | Токен от @BotFather | `123456789:AAHxxxyyyzzz...` |
| `TELEGRAM_CHAT_ID` | Ваш ID от @userinfobot | `123456789` |
| `POSTGRES_PASSWORD` | Придумайте пароль | `moY_par0l_2024!` |
| `REDIS_PASSWORD` | Придумайте пароль | `redis_moY_par0l!` |

> Все остальные переменные можно оставить как в примере.

### 5.4 Проверка файла .env

```bash
cd /opt/smart-skidka-agents
ls -la .env
```

Ожидаемый вывод (права доступа 600):
```
-rw------- 1 root root 2.4K Jan 15 12:00 .env
```

**Проверка что все переменные заполнены:**
```bash
grep -E "^(LLM_API_KEY|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)=" .env
```

Ожидаемый вывод (значения должны быть заполнены, не пустые):
```
LLM_API_KEY=sk-or-v1-ВАШ_КЛЮЧ_СЮДА
TELEGRAM_BOT_TOKEN=123456789:ВАШ_ТОКЕН_СЮДА
TELEGRAM_CHAT_ID=ВАШ_CHAT_ID_СЮДА
```

---

## 6. Запуск

### 6.1 Первая сборка и запуск

```bash
cd /opt/smart-skidka-agents

# Сборка Docker образов (первый раз — 3-5 минут)
docker compose build --no-cache

# Запуск в фоновом режиме
docker compose up -d
```

**Ожидаемый вывод сборки:**
```
[+] Building 45.2s (12/12) FINISHED
 => [orchestrator internal] load build definition from Dockerfile
 => => transferring dockerfile: 32B
 => [orchestrator internal] load .dockerignore
 => [orchestrator 1/6] FROM docker.io/library/python:3.11-slim
 => [orchestrator 2/6] RUN apt-get update && apt-get install -y ...
 => [orchestrator 3/6] COPY requirements.txt .
 => [orchestrator 4/6] RUN pip install --no-cache-dir -r requirements.txt
 => [orchestrator 5/6] COPY src/ ./src/
 => [orchestrator 6/6] RUN mkdir -p /app/logs
 => [orchestrator] exporting to image
 => => exporting layers
 => => writing image sha256:...
[+] Running 6/6
 ✔ Network skidka-network  Created
 ✔ Container skidka-postgres      Started
 ✔ Container skidka-redis         Started
 ✔ Container skidka-orchestrator  Started
 ✔ Container skidka-telegram-bot  Started
 ✔ Container skidka-discount-searcher  Started
 ✔ Container skidka-report-generator   Started
```

### 6.2 Проверка запуска

Подождите 30 секунд пока все контейнеры инициализируются, затем:

```bash
docker compose ps
```

**Все сервисы должны иметь статус `Up` или `Up (healthy)`:**
```
NAME                     IMAGE                       COMMAND                  SERVICE              CREATED          STATUS                    PORTS
skidka-postgres          postgres:16-alpine          "docker-entrypoint.s…"   postgres             45 seconds ago   Up 43 seconds (healthy)   127.0.0.1:5432->5432/tcp
skidka-redis             redis:7-alpine              "docker-entrypoint.s…"   redis                45 seconds ago   Up 43 seconds (healthy)   127.0.0.1:6379->6379/tcp
skidka-orchestrator      smart-skidka-agents-orchestrator   "python -m src.agent…"   orchestrator         45 seconds ago   Up 42 seconds
skidka-telegram-bot      smart-skidka-agents-telegram-bot   "python -m src.tools…"   telegram-bot         45 seconds ago   Up 41 seconds
skidka-discount-searcher smart-skidka-agents-discount-searcher "python -m src.agent…" discount-searcher    45 seconds ago   Up 40 seconds
skidka-report-generator  smart-skidka-agents-report-generator  "python -m src.agent…" report-generator     45 seconds ago   Up 39 seconds
```

---

## 7. Проверка работы

### 7.1 Общий статус контейнеров

```bash
docker compose ps
```

### 7.2 Просмотр логов

**Логи всех сервисов:**
```bash
docker compose logs --tail=50
```

**Логи конкретного сервиса (важные):**
```bash
# Основной оркестратор
docker compose logs -f --tail=50 orchestrator

# Telegram бот
docker compose logs -f --tail=50 telegram-bot

# Поиск скидок
docker compose logs -f --tail=50 discount-searcher

# Генератор отчётов
docker compose logs -f --tail=50 report-generator
```

**Логи баз данных (для отладки):**
```bash
docker compose logs -f --tail=20 postgres
docker compose logs -f --tail=20 redis
```

### 7.3 Проверка баз данных

**PostgreSQL:**
```bash
docker compose exec postgres psql -U skidka -d skidka_db -c "\dt"
```

Ожидаемый вывод (таблицы созданы):
```
         List of relations
 Schema | Name | Type  | Owner
--------+------+-------+-------
 public | ...  | table | skidka
```

**Redis:**
```bash
docker compose exec redis redis-cli -a redis_secret_123 ping
```

Ожидаемый вывод:
```
PONG
```

### 7.4 Проверка работы Telegram бота

Отправьте боту команду `/start`. Проверьте логи:

```bash
docker compose logs -f telegram-bot
```

Ожидаемый вывод при получении команды:
```
INFO - Получена команда /start от пользователя 123456789
INFO - Отправлено приветственное сообщение
```

### 7.5 Проверка API LLM

```bash
docker compose exec orchestrator python -c "
import os
from openai import OpenAI
client = OpenAI(api_key=os.getenv('LLM_API_KEY'), base_url=os.getenv('LLM_API_BASE'))
resp = client.chat.completions.create(model=os.getenv('LLM_MODEL'), messages=[{'role': 'user', 'content': 'Say OK'}])
print(resp.choices[0].message.content)
"
```

Ожидаемый вывод:
```
OK
```

---

## 8. Настройка Telegram бота

### 8.1 Создание бота через @BotFather

1. Откройте Telegram и найдите `@BotFather`
2. Нажмите **Start** или отправьте `/start`
3. Отправьте команду `/newbot`
4. Введите имя бота (например: `Smart Skidka Bot`)
5. Введите username бота — должен заканчиваться на `bot` (например: `smart_skidka_bot`)
6. **BotFather отправит токен** — сообщение вида:
   ```
   Use this token to access the HTTP API:
   123456789:AAHxxxyyyzzz1234567890abcdefgh
   Keep your token secure and store it safely, it can be used by anyone to control your bot.
   ```
7. Скопируйте токен (после `Use this token to access the HTTP API:`) — это ваш `TELEGRAM_BOT_TOKEN`

### 8.2 Узнаём свой chat_id

1. Найдите в Telegram `@userinfobot`
2. Нажмите **Start** или отправьте любое сообщение
3. Бот ответит:
   ```
   @YourUsername
   Id: 123456789
   First: Иван
   Last: Петров
   Lang: ru
   ```
4. Число после `Id:` — это ваш `TELEGRAM_CHAT_ID`

**Альтернативный способ:**
1. Отправьте сообщение созданному боту
2. Откройте в браузере:
   ```
   https://api.telegram.org/bot<ВАШ_ТОКЕН>/getUpdates
   ```
3. Найдите `"chat":{"id":123456789` — это ваш ID

### 8.3 Настройка команд меню

Отправьте `@BotFather` команду `/setcommands`, выберите своего бота, отправьте текст:

```
start - Запустить бота
status - Статус всех агентов
search - Поиск скидок вручную
report - Получить отчёт
settings - Настройки
help - Справка
```

### 8.4 Доступные команды бота

| Команда | Описание | Пример |
|---------|----------|--------|
| `/start` | Приветствие, начало работы | `/start` |
| `/status` | Показать статус всех агентов | `/status` |
| `/search [запрос]` | Ручной поиск скидок | `/search iPhone 15` |
| `/report` | Получить отчёт за сегодня | `/report` |
| `/settings` | Показать текущие настройки | `/settings` |
| `/help` | Справка по командам | `/help` |

---

## 9. Получение API ключей

### 9.1 RouterAI (рекомендуется)

**Зачем:** доступ к 200+ моделям (GPT-4, Claude, DeepSeek) через один API.

**Пошагово:**

1. Перейдите на [rrouter.ai](https://rrouter.ai)
2. Нажмите **Sign In** → авторизуйтесь через Google/GitHub
3. Перейдите в **Keys** → **Create Key**
4. Введите название: `smart-skidka-bot`
5. Нажмите **Create**
6. Скопируйте ключ (начинается с `sk-`)
7. Перейдите в **Credits** → пополните баланс (минимум $5)

**Цены на популярные модели:**

| Модель | Цена за 1M токенов (input) | Код для .env |
|--------|---------------------------|--------------|
| DeepSeek V3 | $0.14 | `deepseek/deepseek-chat` |
| Claude 3.5 Sonnet | $3.00 | `anthropic/claude-3.5-sonnet` |
| GPT-4o | $5.00 | `openai/gpt-4o` |
| DeepSeek R1 | $0.55 | `deepseek/deepseek-r1` |

> Для начала хватит DeepSeek V3 — дёшево и качественно.

### 9.2 DeepSeek API (альтернатива)

**Зачем:** прямой доступ к китайским моделям DeepSeek, дешевле чем через посредников.

**Пошагово:**

1. Перейдите на [platform.deepseek.com](https://platform.deepseek.com)
2. Зарегистрируйтесь по номеру телефона
3. Перейдите в **API Keys**
4. Нажмите **Create API Key**
5. Введите название: `skidka-bot`
6. Скопируйте ключ (начинается с `sk-`)
7. Пополните баланс (поддерживаются российские карты через некоторые сервисы)

**Настройка .env для DeepSeek:**
```env
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
LLM_API_BASE=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

### 9.3 Яндекс.Метрика (опционально)

**Зачем:** отслеживание посещаемости сайтов скидок.

**Пошагово:**

1. Перейдите на [metrika.yandex.ru](https://metrika.yandex.ru)
2. Войдите под Яндекс аккаунтом
3. Нажмите **Добавить счётчик**
4. Введите адрес сайта → **Создать счётчик**
5. Скопируйте номер счётчика (например: `98765432`) → `YANDEX_COUNTER_ID`
6. Перейдите в **Настройки** → **Счётчик** → скопируйте токен API

---

## 10. Мониторинг

### 10.1 Просмотр логов в реальном времени

```bash
cd /opt/smart-skidka-agents

# Все сервисы
docker compose logs -f

# Только ошибки
docker compose logs -f | grep ERROR

# Конкретный сервис
docker compose logs -f orchestrator
docker compose logs -f telegram-bot
docker compose logs -f discount-searcher
docker compose logs -f report-generator
```

### 10.2 Логи в файлах

```bash
# Логи сохраняются в директории logs/
ls -la /opt/smart-skidka-agents/logs/

# Просмотр
tail -f /opt/smart-skidka-agents/logs/orchestrator.log
tail -f /opt/smart-skidka-agents/logs/telegram-bot.log
```

### 10.3 Мониторинг ресурсов сервера

```bash
# CPU, RAM, диск
htop

# Дисковое пространство
df -h

# Использование памяти контейнерами
docker stats --no-stream
```

### 10.4 Перезапуск отдельных агентов

```bash
cd /opt/smart-skidka-agents

# Перезапуск одного сервиса
docker compose restart telegram-bot
docker compose restart discount-searcher
docker compose restart report-generator

# Перезапуск всего
docker compose restart

# Полный пересоздание (сброс состояния)
docker compose down
docker compose up -d
```

### 10.5 Бэкап данных

```bash
# Создание директории для бэкапов
mkdir -p /opt/backups

# Бэкап базы данных
docker compose exec postgres pg_dump -U skidka skidka_db > /opt/backups/skidka_db_$(date +%Y%m%d_%H%M%S).sql

# Бэкап Redis (копируем файл данных)
docker compose exec redis redis-cli -a redis_secret_123 SAVE
cp /opt/smart-skidka-agents/data/redis/dump.rdb /opt/backups/redis_$(date +%Y%m%d_%H%M%S).rdb

# Бэкап .env файла
cp /opt/smart-skidka-agents/.env /opt/backups/env_$(date +%Y%m%d_%H%M%S).bak
```

**Автоматический бэкап (cron):**

```bash
# Открыть crontab
crontab -e

# Добавить строку — бэкап каждый день в 3:00
0 3 * * * cd /opt/smart-skidka-agents && docker compose exec -T postgres pg_dump -U skidka skidka_db > /opt/backups/skidka_db_$(date +\%Y\%m\%d).sql 2>/dev/null && find /opt/backups -name "skidka_db_*.sql" -mtime +7 -delete
```

### 10.6 Восстановление из бэкапа

```bash
# Остановить сервисы
cd /opt/smart-skidka-agents
docker compose down

# Очистить старые данные
rm -rf /opt/smart-skidka-agents/data/postgres/*

# Запустить только БД
docker compose up -d postgres
sleep 10

# Восстановить из бэкапа
docker compose exec -T postgres psql -U skidka -d skidka_db < /opt/backups/skidka_db_20240115_030000.sql

# Запустить остальные сервисы
docker compose up -d
```

---

## 11. Автозапуск при перезагрузке

Docker Compose автоматически запускает контейнеры при перезагрузке сервера благодаря настройке:

```yaml
restart: unless-stopped
```

в каждом сервисе `docker-compose.yml`.

### Проверка

```bash
# Перезагрузка сервера
reboot
```

Подождите 2 минуты, подключитесь снова:

```bash
ssh root@<IP_СЕРВЕРА>
docker compose -f /opt/smart-skidka-agents/docker-compose.yml ps
```

Все контейнеры должны быть в статусе `Up`.

### Альтернатива: systemd сервис (если Docker не перезапускает)

```bash
cat > /etc/systemd/system/smart-skidka.service << 'SERVICE_EOF'
[Unit]
Description=Smart Skidka Agents
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/smart-skidka-agents
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down
TimeoutStartSec=0

[Install]
WantedBy=multi-user.target
SERVICE_EOF

systemctl daemon-reload
systemctl enable smart-skidka
systemctl start smart-skidka
```

**Проверка:**
```bash
systemctl status smart-skidka
```

Ожидаемый вывод:
```
● smart-skidka.service - Smart Skidka Agents
     Loaded: loaded (/etc/systemd/system/smart-skidka.service; enabled)
     Active: active (exited) since Mon 2024-01-15 12:00:00 MSK
```

---

## 12. Обновление системы

### 12.1 Полное обновление (код + контейнеры)

```bash
cd /opt/smart-skidka-agents

# 1. Бэкап перед обновлением
docker compose exec postgres pg_dump -U skidka skidka_db > /opt/backups/skidka_db_pre_update_$(date +%Y%m%d).sql

# 2. Обновление кода
git pull origin main  # если используете git
# или распакуйте новый архив

# 3. Остановка сервисов
docker compose down

# 4. Пересборка образов (без кэша)
docker compose build --no-cache

# 5. Запуск
docker compose up -d

# 6. Проверка
docker compose ps
docker compose logs --tail=20
```

### 12.2 Обновление только одного сервиса

```bash
cd /opt/smart-skidka-agents

# Пересборка и перезапуск только telegram-bot
docker compose up -d --build telegram-bot

# Проверка
docker compose logs -f telegram-bot
```

### 12.3 Обновление Docker образов (базовые)

```bash
cd /opt/smart-skidka-agents

# Скачать новые версии базовых образов
docker compose pull

# Пересобрать и перезапустить
docker compose up -d --build
```

### 12.4 Обновление системных пакетов

```bash
# Раз в месяц выполняйте
apt update && apt upgrade -y

# Перезагрузка если требуется
[ -f /var/run/reboot-required ] && reboot
```

---

## 13. Troubleshooting

### 13.1 Таблица проблем и решений

| Проблема | Причина | Решение |
|----------|---------|---------|
| **Агенты не запускаются** | Нет `LLM_API_KEY` в .env | Проверить `cat .env \| grep LLM_API_KEY`, заполнить |
| **Агенты не запускаются** | Неверный формат API ключа | Убедиться что ключ начинается с `sk-` (RouterAI) или `sk-` (DeepSeek) |
| **Нет отчётов в Telegram** | Неверный `TELEGRAM_CHAT_ID` | Проверить через @userinfobot, должен быть числом |
| **Нет отчётов в Telegram** | Бот не запущен / заблокирован | Написать `/start` боту, проверить логи `docker compose logs telegram-bot` |
| **PostgreSQL не стартует** | Порт 5432 занят другим процессом | `lsof -i :5432` → `kill <PID>` или изменить порт в docker-compose.yml |
| **PostgreSQL не стартует** | Повреждены данные | Удалить `data/postgres/` и перезапустить (данные потеряются!) |
| **Redis не стартует** | Поврежден файл данных | `rm data/redis/dump.rdb` и перезапустить |
| **Ошибка `permission denied`** | .env доступен всем | `chmod 600 .env` |
| **Ошибка `out of memory`** | Недостаточно RAM | Добавить swap: `fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile` |
| **Контейнер постоянно перезапускается** | Ошибка в коде приложения | `docker compose logs -f <сервис>` — найти ошибку, исправить, пересобрать |
| **Ошибка подключения к LLM API** | Нет интернета / блокировка | `curl -I https://api.rrouter.ai/v1` — проверить доступность |
| **Ошибка подключения к LLM API** | Закончился баланс | Проверить баланс на rrouter.ai или platform.deepseek.com |
| **Ошибка `ModuleNotFoundError`** | Не установлены зависимости | `docker compose build --no-cache` — пересобрать образ |
| **Docker не перезапускает контейнеры** | Нет restart: unless-stopped | Добавить в docker-compose.yml, выполнить `docker compose up -d` |
| **Закончилось место на диске** | Логи растут | `docker system prune -f` — очистить неиспользуемые образы |
| **Закончилось место на диске** | БД разрослась | `du -sh data/postgres/` — проверить размер, настроить ротацию |
| **Ошибка `bind: address already in use`** | Порт занят | `lsof -i :<порт>` → найти процесс → `kill <PID>` |
| **SSH не подключается** | UFW заблокировал порт 22 | Через консоль хостинга: `ufw allow 22/tcp` |
| **Медленные ответы от LLM** | Сетевая задержка | Попробовать другую модель в .env, проверить `ping api.rrouter.ai` |
| **Telegram бот не отвечает** | Вебхук не настроен (для webhook режима) | Использовать polling режим или настроить webhook URL |

### 13.2 Быстрые команды диагностики

```bash
# Все контейнеры и их статус
docker compose ps

# Использование ресурсов
docker stats --no-stream

# Свободное место
df -h

# Свободная память
free -h

# Процессы внутри контейнера
docker compose exec orchestrator ps aux

# Проверка сети
docker network ls
docker network inspect smart-skidka-agents_skidka-network

# Проверка связи между контейнерами
docker compose exec orchestrator ping -c 3 postgres
docker compose exec orchestrator ping -c 3 redis
```

### 13.3 Полный сброс (с потерей данных!)

```bash
cd /opt/smart-skidka-agents

# Остановка

docker compose down

# Удаление всех данных
rm -rf data/postgres/*
rm -rf data/redis/*
rm -rf logs/*

# Пересборка
docker compose build --no-cache

# Запуск
docker compose up -d
```

### 13.4 Сбор информации для поддержки

```bash
cd /opt/smart-skidka-agents

echo "=== Docker ===" > /tmp/debug.txt
docker --version >> /tmp/debug.txt
docker compose version >> /tmp/debug.txt

echo -e "\n=== Containers ===" >> /tmp/debug.txt
docker compose ps >> /tmp/debug.txt

echo -e "\n=== Logs (last 50) ===" >> /tmp/debug.txt
docker compose logs --tail=50 >> /tmp/debug.txt 2>&1

echo -e "\n=== Resources ===" >> /tmp/debug.txt
free -h >> /tmp/debug.txt
df -h >> /tmp/debug.txt

echo -e "\n=== .env (without secrets) ===" >> /tmp/debug.txt
grep -v "KEY\|TOKEN\|PASSWORD" .env >> /tmp/debug.txt

cat /tmp/debug.txt
```

---

## 14. Безопасность

### 14.1 Фаервол UFW (уже настроен в шаге 3.6)

Проверка текущих правил:
```bash
ufw status numbered
```

**Разрешение только нужных портов:**
```bash
# SSH (обязательно!)
ufw allow 22/tcp

# HTTP/HTTPS если нужен веб
ufw allow 80/tcp
ufw allow 443/tcp

# Запрет всего остального (уже сделано на шаге 3.6)
ufw default deny incoming
```

**Запрет конкретного IP:**
```bash
ufw deny from 192.168.1.100
```

### 14.2 SSH-ключи вместо пароля

На вашей **локальной** машине:

```bash
# Генерация ключа (если ещё нет)
ssh-keygen -t ed25519 -C "your_email@example.com"

# Копирование на сервер
ssh-copy-id -i ~/.ssh/id_ed25519.pub root@<IP_СЕРВЕРА>
```

На **сервере**:

```bash
# Отключение входа по паролю
sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/#PermitRootLogin prohibit-password/PermitRootLogin no/' /etc/ssh/sshd_config

# Перезапуск SSH
systemctl restart sshd
```

**Проверка:**
```bash
# С локальной машины — должно подключаться без пароля
ssh root@<IP_СЕРВЕРА>
```

### 14.3 Защита .env файла

```bash
cd /opt/smart-skidka-agents

# Только владелец может читать
chmod 600 .env

# Проверка
ls -la .env
# Должно быть: -rw------- (только владелец)
```

### 14.4 Автоматические обновления безопасности

```bash
apt install -y unattended-upgrades
dpkg-reconfigure -plow unattended-upgrades
# Выберите YES
```

### 14.5 Fail2ban (защита от брутфорса SSH)

```bash
apt install -y fail2ban

systemctl enable fail2ban
systemctl start fail2ban

# Проверка статуса
fail2ban-client status sshd
```

### 14.6 Не коммитить секреты

Если используете git, убедитесь что `.env` в `.gitignore`:

```bash
cat > /opt/smart-skidka-agents/.gitignore << 'GITIGNORE'
# Secrets
.env
*.pem
*.key

# Data
data/
logs/

# Python
__pycache__/
*.pyc
.venv/
venv/

# IDE
.idea/
.vscode/
*.swp
GITIGNORE
```

Проверка:
```bash
git status
# .env НЕ должен отображаться как неотслеживаемый для коммита
```

### 14.7 Чеклист безопасности

- [ ] UFW включен, только нужные порты открыты
- [ ] SSH работает по ключу, пароль отключен
- [ ] `.env` файл имеет права 600
- [ ] `.env` добавлен в `.gitignore`
- [ ] Пароли в `.env` — случайные, минимум 16 символов
- [ ] Fail2ban установлен и работает
- [ ] Автообновления безопасности включены
- [ ] Бэкапы настроены и проверены
- [ ] Не используется root для Docker (docker группа)
- [ ] PostgreSQL и Redis не доступны снаружи (bind 127.0.0.1)

---

## Быстрый старт (для тех кто всё знает)

```bash
# 1. Купить сервер (Hetzner CPX21 — 4CPU/8GB/€8.90)
# 2. Подключиться
ssh root@<IP>

# 3. Подготовка
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER && newgrp docker
apt install -y docker-compose-plugin git ufw

# 4. Проект
cd /opt && git clone <URL> smart-skidka-agents && cd smart-skidka-agents

# 5. Настройка .env (nano .env — заполнить LLM_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID)
nano .env

# 6. Запуск
docker compose up -d

# 7. Проверка
docker compose ps
docker compose logs -f
```

---

## Полезные ссылки

| Ресурс | Ссылка | Назначение |
|--------|--------|------------|
| RouterAI | [rrouter.ai](https://rrouter.ai) | API для LLM |
| DeepSeek | [platform.deepseek.com](https://platform.deepseek.com) | Альтернативный LLM API |
| BotFather | [@BotFather](https://t.me/BotFather) | Создание Telegram ботов |
| UserInfoBot | [@userinfobot](https://t.me/userinfobot) | Узнать свой chat_id |
| Docker Docs | [docs.docker.com](https://docs.docker.com) | Документация Docker |
| Hetzner Cloud | [hetzner.com/cloud](https://hetzner.com/cloud) | Европейский хостинг |
| Timeweb Cloud | [timeweb.cloud](https://timeweb.cloud) | РФ хостинг |

---

*Инструкция актуальна на январь 2025. При обнаружении неточностей — проверяйте официальную документацию соответствующих сервисов.*
