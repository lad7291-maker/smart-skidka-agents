# AGENTS.md — smart-skidka-agents

> Инструкции для AI-агентов, работающих с этим кодом.  
> Дополняет `README.md` (для людей) и `SKILL.md` (для внешнего использования).

---

## 1. Общие правила работы с кодом

### 1.1 Стиль и форматирование
- **Black** (`line-length = 120`) — автоформатирование перед коммитом.
- **isort** (`profile = "black"`) — сортировка импортов.
- **flake8** — критические ошибки (`E9,F63,F7,F82`) блокируют CI.
- Запускать перед коммитом:
  ```bash
  black scripts/ tests/
  isort scripts/ tests/
  flake8 scripts/ tests/ --select=E9,F63,F7,F82
  ```

### 1.2 Тесты
- Все изменения должны проходить существующие тесты.
- Новые функции — с новыми тестами.
- Запуск: `pytest tests/ -q --tb=short` (без `test_browser_actions.py` если нет Playwright).
- CI запускает полный набор: 623 теста.

### 1.3 Зависимости
- Добавлять в `requirements.txt` с минимальной версией.
- Устанавливать через `.venv/bin/pip install -r requirements.txt`.
- Не использовать системный Python (`pip install` без venv запрещён).

---

## 2. Архитектура системы

### 2.1 Основные компоненты

| Компонент | Файл | Ответственность |
|-----------|------|-----------------|
| Orchestrator | `scripts/orchestrator.py` | Цикл агентов, dispatch, validation, reporting |
| CycleManager | `scripts/services/cycle_manager.py` | Жизненный цикл: init, load, run_cycle |
| ActionExecutor | `scripts/services/action_executor.py` | Выполнение действий агентов |
| ActionDispatcher | `scripts/actions/action_registry.py` | Плагинная система действий |
| LLMClient | `scripts/orchestrator.py` | API к LLM (DeepSeek/RouterAI) с rate limiting |
| MemoryStore | `scripts/orchestrator.py` | PostgreSQL + Redis для данных и кэша |
| Dashboard | `scripts/dashboard.py` | Web UI (aiohttp) для мониторинга и управления |
| Telegram Bot | `scripts/telegram_bot.py` | Интерфейс управления через Telegram |
| SecretsManager | `scripts/secrets_manager.py` | AES-256-GCM шифрование секретов |

### 2.2 Поток данных

```
Cron Trigger → Orchestrator.run_cycle() → CycleManager
    → load_agents() → AgentConfig + LLMClient
    → asyncio.gather() + Semaphore → AgentRunner.run()
        → _build_prompt() → LLM API
        → _parse_result() → JSON
        → validate_by_type() → ValidationResult
        → ActionDispatcher.execute() → ActionResult
    → save_result() → PostgreSQL
    → TelegramReporter.send_report() → Telegram API
    → get_health_status() / get_metrics() → Dashboard
```

### 2.3 Типы агентов

| Тип | Конфиг | Действия | Валидация |
|-----|--------|----------|-----------|
| seo | `configs/seo-agent.json` | update_meta_tags, update_product_field | SEOValidator |
| smm | `configs/smm-agent.json` | post_to_channel, post_discount | SMMValidator |
| content | `configs/content-agent.json` | create_category_page, update_item_description | ContentValidator |
| performance | `configs/performance-agent.json` | add_badge, prioritize_products | PerformanceValidator |
| email | `configs/email-agent.json` | — | EmailValidator |
| analytics | `configs/analytics-agent.json` | — | AnalyticsValidator |
| trend | `configs/trend-agent.json` | gather_trend_data | TrendValidator |

---

## 3. Ключевые паттерны

### 3.1 Действия (Actions)

Все действия регистрируются через декоратор:

```python
from scripts.actions.action_registry import register_action

@register_action(agent_types=["seo"], name="update_meta_tags")
def update_meta_tags(title: str, description: str) -> bool:
    ...
```

### 3.2 Rate Limiting

- **LLM**: `TokenBucketRateLimiter` в `LLMClient` (RPM/TPM, динамическая подстройка).
- **Telegram**: `TelegramRateLimiter` (debounce 5 мин, дневной лимит 20 постов).
- **File creation**: `check_category_page_quota()` (дневной лимит 10 страниц).

### 3.3 Retry и Circuit Breaker

- `@with_retry()` — exponential backoff, настраиваемые exceptions.
- `CircuitBreaker` в `LLMClient` — 3 состояния (closed/open/half_open).
- Smart retry в `AgentRunner` — анализ ошибки + targeted correction.

### 3.4 Валидация

Три уровня:
1. **Rule-based** — `validator.py` (type-specific checks).
2. **Subgoal-based** — `subgoal_evaluator.py` (atomic checkers).
3. **LLM-as-a-Judge** — `llm_judge.py` (HeuristicJudge fallback).

### 3.5 Безопасность

- **Prompt injection**: `_sanitize_context_value()` — 12 regex-паттернов, zero-width char detection, base64 обфускация.
- **Path traversal**: `_resolve_within_site_root()` — `SITE_ROOT.resolve()` + `relative_to()`.
- **Products protection**: whitelist/blacklist полей в `file_utils.py`.
- **Secrets**: `SecretsManager` — AES-256-GCM, PBKDF2-HMAC-SHA256 (480K итераций), RBAC.

---

## 4. Работа с CI/CD

### 4.1 Workflow файлы

| Файл | Триггер | Что делает |
|------|---------|------------|
| `.github/workflows/ci.yml` | push/PR to master | Tests + Lint (flake8, black, isort) |
| `.github/workflows/deploy.yml` | push to master, tags | Docker build/push to GHCR |
| `.github/workflows/security.yml` | push/PR, weekly | Bandit + Safety scan |
| `.github/workflows/nightly.yml` | daily 2 AM UTC | Full integration tests |

### 4.2 Docker

- `assets/Dockerfile` — orchestrator image.
- `assets/Dockerfile.bot` — telegram bot image.
- `assets/docker-compose.yml` — full stack (postgres, redis, orchestrator, bot, pgadmin, redis-commander).

### 4.3 Переменные окружения (обязательные)

```bash
LLM_API_KEY=             # API ключ для LLM
DATABASE_URL=            # PostgreSQL connection string
REDIS_URL=               # Redis connection string
TELEGRAM_BOT_TOKEN=      # Telegram Bot API token
TELEGRAM_CHAT_ID=        # Telegram chat ID для отчётов
SECRETS_MASTER_KEY=      # 64 hex chars для SecretsManager
PROJECT_ROOT=            # Путь к сайту (default: /var/www/dealshub-miniapp)
```

---

## 5. Частые задачи для агентов

### 5.1 Добавить новый тип агента

1. Создать `configs/{name}-agent.json` с полями: `agent_name`, `version`, `system_prompt`, `schedule`, `llm_settings`, `validation_rules`, `actions`.
2. Добавить валидатор в `scripts/validator.py` — класс `{Name}Validator`.
3. Добавить subgoals в `scripts/subgoal_evaluator.py`.
4. Добавить тесты в `tests/test_validator.py` и `tests/test_subgoal_evaluator.py`.
5. Обновить `ActionDispatcher` если нужны новые действия.

### 5.2 Добавить новое действие (Action)

1. Реализовать функцию в `scripts/actions/{module}.py`.
2. Декорировать `@register_action(agent_types=[...], name="...")`.
3. Добавить retry: `@with_retry(max_retries=3)`.
4. Добавить тесты в `tests/test_action_registry.py` или новый файл.
5. Обновить конфиг агента — добавить в `actions` массив.

### 5.3 Добавить новый инструмент данных

1. Реализовать в `scripts/actions/data_tools.py`.
2. Добавить async функцию с `aiohttp`.
3. Добавить fallback/mock для тестов.
4. Добавить тесты в `tests/test_data_tools.py`.

### 5.4 Изменить схему БД

1. Изменить `init-scripts/01-schema.sql`.
2. Создать alembic миграцию: `alembic revision --autogenerate -m "description"`.
3. Обновить `MemoryStore.init_schema()` если нужно.
4. Обновить тесты в `tests/test_alembic.py`.

---

## 6. Отладка и troubleshooting

### 6.1 Локальный запуск

```bash
# Установка
python -m venv .venv
.venv/bin/pip install -r requirements.txt

# Тесты
.venv/bin/pytest tests/ -q --tb=short --ignore=tests/test_browser_actions.py

# Запуск оркестратора
.venv/bin/python -m scripts.orchestrator

# Запуск dashboard
.venv/bin/python -m scripts.dashboard

# Запуск telegram bot
.venv/bin/python -m scripts.telegram_bot
```

### 6.2 Docker

```bash
# Полный стек
docker-compose -f assets/docker-compose.yml up -d

# Только БД
docker-compose -f assets/docker-compose.yml up -d postgres redis

# Логи
docker-compose -f assets/docker-compose.yml logs -f orchestrator
```

### 6.3 Частые проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| `ModuleNotFoundError: playwright` | Не установлен Playwright | `.venv/bin/pip install playwright` + `playwright install chromium` |
| `Path traversal detected` | Симлинк + `Path.resolve()` | Использовать `SITE_ROOT.resolve()` в `_resolve_within_site_root` |
| `alembic: command not found` | Не установлен alembic | `.venv/bin/pip install alembic` |
| `psycopg2 not found` | Не установлен драйвер | `.venv/bin/pip install psycopg2-binary` |
| `jsonschema not available` | Не установлен jsonschema | `.venv/bin/pip install jsonschema` |
| `Logger._log() got unexpected keyword argument` | structlog vs logging | Использовать `structlog.get_logger()`, не `logging.getLogger()` |
| CI test failures с `FileNotFoundError` | Нет `PROJECT_ROOT` env | Установить `PROJECT_ROOT` и создать тестовую структуру |

---

## 7. История изменений (для агентов)

### 2026-06-17 — CI/CD стабилизация
- Все workflow (CI, Deploy, Security, Nightly) проходят успешно.
- Добавлены недостающие зависимости: `alembic`, `sqlalchemy`, `psycopg2-binary`, `jsonschema`, `defusedxml`, `pytest` + плагины.
- Создан `pyproject.toml` для black+isort совместимости.
- Исправлен `Dockerfile.bot` (telegram_reporter.py → telegram_bot.py).
- Deploy job skip если `DEPLOY_HOST` не настроен.

### 2026-05-30 — Аудит и рефакторинг
- P0-P3 задачи выполнены (см. `BACKLOG.md`).
- 360 тестов, покрытие ~11.5%.
- Bandit: 0 High, 0 Medium.

---

*Последнее обновление: 2026-06-17*
