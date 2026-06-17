# smart-skidka-agents

**Multi-Agent Система Автономного Маркетинга** для агрегатора скидок [smart-skidka.ru](https://smart-skidka.ru).

Система из 7 специализированных AI-агентов автономно выполняет полный цикл маркетинговых операций: SEO-оптимизацию, SMM-продвижение, генерацию контента, performance-маркетинг, email-рассылки, аналитику и исследование трендов. Работает по расписанию, самовалилирует результаты и отправляет отчёты в Telegram.

---

## 📋 Содержание

- [Архитектура](#-архитектура)
- [Агенты](#-агенты)
- [Быстрый старт](#-быстрый-старт)
- [Конфигурация](#-конфигурация)
- [Команды управления](#-команды-управления)
- [Структура проекта](#-структура-проекта)
- [Тестирование](#-тестирование)
- [Мониторинг](#-мониторинг)
- [Лицензия](#-лицензия)

---

## 🏗 Архитектура

```
┌─────────────────────────────────────────────────────────────────┐
│                        ORCHESTRATOR                             │
│                     (scripts/orchestrator.py)                   │
│  ┌─────────┐  ┌─────────────┐  ┌──────────┐  ┌─────────────┐   │
│  │  Cron   │→ │ Dispatcher  │→ │ Validator│→ │  Telegram   │   │
│  │ Trigger │  │ (плагинная) │  │ (judge)  │  │  Reporter   │   │
│  └─────────┘  └──────┬──────┘  └────┬─────┘  └─────────────┘   │
│                      │              │                           │
│  ┌───────────────────┘              └───────────────────┐      │
│  ▼                                                      ▼      │
│  ┌──────────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │   SEO Agent  │  │ SMM Agent│  │Perf.Agent│  │EmailAgent│   │
│  └──────────────┘  └──────────┘  └──────────┘  └──────────┘   │
│  ┌──────────────┐  ┌──────────┐  ┌──────────┐                 │
│  │ Content Agent│  │Analytics │  │  Trends  │                 │
│  └──────────────┘  └──────────┘  └──────────┘                 │
└─────────────────────────────────────────────────────────────────┘
         │
    ┌────┴────┐
    ▼         ▼
┌────────┐ ┌────────┐
│PostgreSQL│ │ Redis  │
│(данные) │ │(кэш)   │
└────────┘ └────────┘
```

### Ключевые компоненты

| Компонент | Описание |
|-----------|----------|
| **Orchestrator** | Центральный оркестратор — координирует запуск агентов, валидацию, retry-логику, отчётность |
| **AgentRunner** | Запускает агентов через LLM API с поддержкой circuit breaker и rate limiting |
| **ResultValidator** | Валидирует результаты (rule-based + LLM-as-a-Judge + subgoal evaluation) |
| **MemoryStore** | Двухуровневое хранилище памяти: PostgreSQL (персистентность) + Redis (кэш) |
| **ActionRegistry** | Плагинная система действий агентов с динамической регистрацией |
| **TelegramReporter** | Отправка отчётов и уведомлений в Telegram |
| **Dashboard** | Web UI для мониторинга и управления агентами (aiohttp) |
| **CriticAgent** | Аудит качества работы агентов (plan adherence, hallucination detection) |

---

## 🤖 Агенты

| Агент | Назначение | Модель (по умолчанию) |
|-------|-----------|----------------------|
| **SEO Agent** | Генерация мета-тегов, ключевых слов, SEO-страниц | `qwen/qwen-2.5-7b-instruct` |
| **SMM Agent** | Посты для соцсетей, вирусные тексты | `qwen/qwen-2.5-7b-instruct` |
| **Content Agent** | Длинные гайды, сравнения товаров, описания | `qwen/qwen-plus-2025-07-28` |
| **Performance Agent** | Приоритизация товаров, бейджи скидок | `nvidia/nemotron-nano-9b-v2` |
| **Email Agent** | Email-рассылки, короткие письма | `nvidia/nemotron-nano-9b-v2` |
| **Analytics Agent** | Сбор метрик, дашборды, отчёты | `nvidia/nemotron-nano-9b-v2` |
| **Trend Agent** | Анализ трендов интернета, рекомендации | `qwen/qwen3-30b-a3b-thinking-2507` |

Каждый агент конфигурируется через JSON-файл в `configs/` и может иметь:
- Персональную LLM-модель
- Собственную temperature (с автокалибровкой)
- A/B-варианты промптов
- Плагинные actions для выполнения реальных операций

---

## 🚀 Быстрый старт

### Требования

- Ubuntu 22.04 LTS (рекомендуется)
- Docker 20.10+ и Docker Compose 2.0+
- 4 vCPU, 8 GB RAM, 50 GB SSD (для стабильной работы)

### Автоматическая установка

```bash
sudo bash setup.sh
```

Скрипт выполнит:
1. Обновление системы
2. Установку Docker и зависимостей
3. Настройку фаервола (UFW)
4. Запуск PostgreSQL, Redis и сервисов агентов

### Ручная установка

```bash
# 1. Клонирование
cd /opt
git clone <URL> smart-skidka-agents
cd smart-skidka-agents

# 2. Настройка окружения
cp .env.example .env
nano .env  # заполните LLM_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

# 3. Запуск
cd assets
docker compose up -d

# 4. Проверка
docker compose ps
docker compose logs -f orchestrator
```

### Получение API-ключей

- **LLM API**: [routerai.ru](https://routerai.ru) — единый доступ к 200+ моделям
- **Telegram Bot**: @BotFather → `/newbot` → скопируйте токен
- **Chat ID**: @userinfobot → скопируйте число после `Id:`

---

## ⚙ Конфигурация

### Переменные окружения (`.env`)

```bash
# LLM API
LLM_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
LLM_API_URL=https://routerai.ru/api/v1/chat/completions
DEFAULT_LLM_MODEL=nvidia/nemotron-nano-9b-v2

# Персональные модели для агентов
TREND_AGENT_MODEL=qwen/qwen3-30b-a3b-thinking-2507
CONTENT_AGENT_MODEL=qwen/qwen-plus-2025-07-28
SMM_AGENT_MODEL=qwen/qwen-2.5-7b-instruct
SEO_AGENT_MODEL=qwen/qwen-2.5-7b-instruct

# Telegram
TELEGRAM_BOT_TOKEN=123456789:AAHxxxyyyzzz...
TELEGRAM_CHAT_ID=123456789
TELEGRAM_CHANNEL_ID=-100xxxxxxxxxx

# База данных
DATABASE_URL=postgresql://user:pass@localhost:5432/smartskidka
REDIS_URL=redis://localhost:6379

# Расписание (в секундах)
CYCLE_INTERVAL=43200  # 12 часов между циклами
```

### Конфиги агентов (`configs/`)

```
configs/
├── content-agent.json   # Конфиг Content Agent
├── seo-agent.json       # Конфиг SEO Agent
├── smm-agent.json       # Конфиг SMM Agent
├── secrets.enc.json     # Зашифрованные секреты (AES-256-GCM)
├── variants/            # A/B-варианты промптов
│   └── seo-agent.variants.json
├── temperatures/        # Калибровка temperature
│   └── seo-agent.temperature.json
└── i18n/                # Локализация
    ├── ru.json
    └── en.json
```

---

## 💬 Команды управления

### Telegram Bot

Отправьте боту команды для управления агентами:

| Команда | Описание |
|---------|----------|
| `/start` | Приветствие и справка |
| `/status` | Статус всех агентов |
| `/agents` | Список агентов с состоянием |
| `/pause <agent>` | Приостановить агента |
| `/resume <agent>` | Возобновить агента |
| `/run_now <agent>` | Запустить агента вне очереди |
| `/logs [n]` | Последние n строк логов |
| `/help` | Справка по командам |

### Web Dashboard

После запуска оркестратора доступен веб-интерфейс:

```
GET  /health              # Health-check
GET  /metrics             # Prometheus-метрики
GET  /api/agents          # Список агентов
GET  /api/cycles          # История циклов
GET  /api/validations     # История валидаций
GET  /api/errors          # Ошибки
POST /api/agents/{name}/pause   # Приостановить
POST /api/agents/{name}/resume  # Возобновить
POST /api/agents/{name}/run_now # Запустить
```

### Docker Compose

```bash
cd assets

# Статус
docker compose ps

# Логи
docker compose logs -f orchestrator
docker compose logs -f telegram-bot

# Перезапуск
docker compose restart

# Остановка
docker compose down

# Полный сброс (данные БД сохранятся в volumes)
docker compose down -v
```

---

## 📁 Структура проекта

```
smart-skidka-agents/
├── scripts/                    # Исходный код
│   ├── orchestrator.py         # Главный оркестратор (~3500 строк)
│   ├── content_generator.py    # Генератор контента
│   ├── telegram_bot.py         # Telegram-бот управления
│   ├── validator.py            # Валидатор результатов
│   ├── llm_judge.py            # LLM-as-a-Judge
│   ├── critic_agent.py         # Аудит качества
│   ├── dashboard.py            # Web UI мониторинг
│   ├── subgoal_evaluator.py    # Subgoal-based evaluation
│   ├── ab_testing.py           # A/B тестирование промптов
│   ├── temperature_calibration.py  # Автокалибровка temperature
│   ├── secrets_manager.py      # Шифрование секретов
│   ├── i18n.py                 # Локализация (gettext-style)
│   ├── project_context.py      # Контекст проекта
│   └── actions/                # Плагинные действия агентов
│       ├── action_registry.py  # Реестр действий
│       ├── telegram_actions.py # Постинг в Telegram
│       ├── site_actions.py     # Операции с сайтом
│       ├── browser_actions.py  # Browser-based агент (Playwright)
│       ├── data_tools.py       # Инструменты сбора данных
│       ├── context_cache.py    # Кэширование контекста
│       └── file_utils.py       # Утилиты работы с файлами
│
├── tests/                      # Тесты (360+ тестов)
│   ├── test_orchestrator.py
│   ├── test_critic_agent.py
│   ├── test_secrets_manager.py
│   ├── test_subgoal_evaluator.py
│   ├── test_i18n.py
│   └── ...
│
├── configs/                    # Конфигурации
│   ├── *.json                  # Конфиги агентов
│   ├── secrets.enc.json        # Зашифрованные секреты
│   ├── variants/               # A/B-варианты
│   ├── temperatures/           # Калибровка temperature
│   └── i18n/                   # Переводы
│
├── assets/                     # Docker и деплой
│   ├── Dockerfile              # Образ оркестратора
│   ├── Dockerfile.bot          # Образ Telegram-бота
│   └── docker-compose.yml      # Compose-конфиг
│
├── alembic/                    # Миграции БД
│   └── versions/
│
├── init-scripts/               # Инициализация PostgreSQL
│   └── 01-schema.sql
│
├── references/                 # Референсные материалы для агентов
│   └── agents/
│
├── setup.sh                    # Автоматический установщик
├── requirements.txt            # Python-зависимости
├── alembic.ini                 # Конфиг Alembic
├── .env                        # Переменные окружения
├── DEPLOY.md                   # Подробное руководство по деплою
├── BACKLOG.md                  # Бэклог и аудит качества
└── SKILL.md                    # Подробная документация по архитектуре
```

---

## 🧪 Тестирование

```bash
# Установка зависимостей для тестов
pip install pytest pytest-asyncio pytest-aiohttp

# Запуск всех тестов
pytest tests/ -v

# Запуск конкретного модуля
pytest tests/test_orchestrator.py -v
pytest tests/test_critic_agent.py -v
pytest tests/test_secrets_manager.py -v

# Покрытие
pytest tests/ --cov=scripts --cov-report=html
```

### Покрытие тестами

| Модуль | Тестов | Покрытие |
|--------|--------|----------|
| Orchestrator | 24 | Циклы, валидация, feedback |
| Critic Agent | 30 | Plan adherence, hallucination |
| Secrets Manager | 41 | AES-256-GCM, RBAC, rotation |
| Subgoal Evaluator | 43 | 7 типов агентов |
| i18n | 30 | gettext, plural, context, lazy |
| Data Tools | 12 | RSS, API, тренды |
| Browser Actions | 10 | Playwright, Core Web Vitals |
| **Итого** | **360+** | **~11.5%** (цель: >60%) |

---

## 📊 Мониторинг

### Prometheus-метрики

```
orchestrator_cycles_total
orchestrator_errors_total
orchestrator_uptime_seconds
orchestrator_agents_total
orchestrator_agents_paused
orchestrator_agents_running
orchestrator_llm_circuit_breaker_state
orchestrator_memory_connected
orchestrator_llm_client_ready
orchestrator_reporter_enabled
```

### Health-check

```bash
curl http://localhost:8080/health
```

Ответ:
```json
{
  "status": "healthy",
  "running": true,
  "agents_total": 7,
  "agents_paused": 0,
  "cycle_count": 42,
  "total_errors": 3,
  "uptime_seconds": 86400,
  "memory_connected": true,
  "llm_client_ready": true
}
```

### Утилиты мониторинга

- **pgAdmin**: `http://localhost:5050` — управление PostgreSQL
- **Redis Commander**: `http://localhost:8081` — просмотр Redis

---

## 🔒 Безопасность

- **Шифрование секретов**: AES-256-GCM с PBKDF2-HMAC-SHA256 (480K итераций)
- **RBAC**: Ролевая модель доступа (READ/WRITE/ADMIN)
- **Prompt Injection Protection**: 12 regex-паттернов + санитизация контекста
- **Защита данных**: `products.json` защищён от перезаписи (whitelist полей)
- **Rate Limiting**: Токен-бакет для LLM API, debounce для Telegram
- **Circuit Breaker**: Предотвращение каскадных сбоев LLM API
- **File Quotas**: Дневные лимиты на создание страниц (10/день)

---

## 📚 Дополнительная документация

| Документ | Содержание |
|----------|-----------|
| [DEPLOY.md](DEPLOY.md) | Пошаговое руководство по деплою на сервер |
| [BACKLOG.md](BACKLOG.md) | Аудит качества, бэклог задач, метрики |
| [SKILL.md](SKILL.md) | Подробная архитектурная документация |

---

## 📄 Лицензия

Проприетарное ПО. Все права защищены.

---

<p align="center">
  <b>smart-skidka-agents</b> — автономный маркетинг на автопилоте 🤖
</p>
