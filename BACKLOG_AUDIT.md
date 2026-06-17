# 📋 Бэклог — Аудит smart-skidka-agents

> Дата аудита: 2026-06-04
> Дата обновления: 2026-06-04 (все P0 + 11/19 P1 выполнены)
> Статус: Активный
> Источник: AUDIT_REPORT.md

---

## 🔴 КРИТИЧЕСКИЕ (P0) — ВСЕ ВЫПОЛНЕНЫ ✅

| ID | Задача | Файл | Строки | Описание | Статус |
|----|--------|------|--------|----------|--------|
| P0-1 | ✅ Реализовать настоящий Circuit Breaker для LLMClient | `scripts/orchestrator.py` | ~1465 | Состояния closed/open/half_open, счётчик ошибок (порог 5), таймер восстановления (30s). При открытом circuit — мгновенный reject. | **done** |
| P0-2 | ✅ Исправить баг `_get_session()` → `self._get_session()` в LLM Judge | `scripts/llm_judge.py` | 110 | `LLMJudge` фактически не работает — всегда падает с `NameError`. Fallback на `HeuristicJudge` срабатывает через `except Exception`. | **done** |
| P0-3 | ✅ Добавить RBAC-проверку в ActionDispatcher.execute() | `scripts/actions/action_registry.py` | — | Декоратор `@register_action(agent_types=[...])` задаёт разрешённые типы, но `execute()` не проверяет. Любой агент может вызвать любой action. | **done** |
| P0-4 | ✅ HTML/XML-escape пользовательских данных в site_actions | `scripts/actions/site_actions.py` | — | `update_meta_tags`, `create_category_page`, `update_sitemap`, `add_cross_links` вставляют данные без `html.escape()`. Возможна XSS/ломка структуры. | **done** |
| P0-5 | ✅ Добавить path traversal protection в file_utils | `scripts/actions/file_utils.py` | — | `safe_write(path)` не проверяет, что `path.resolve()` внутри `SITE_ROOT`. Также исправить rollback-логику (сохранять ссылку на бэкап). | **done** |
| P0-6 | ✅ Синхронизировать Alembic-миграцию со SQL-скриптом | `alembic/versions/001_initial_schema.py` | — | Добавить ForeignKeyConstraint, CheckConstraint, недостающие индексы, seed-данные через `op.bulk_insert()`. Или отказаться от двойной схемы. | **done** |
| P0-7 | ✅ Интегрировать CriticAgent в production-цикл оркестратора | `scripts/orchestrator.py`, `scripts/critic_agent.py` | — | `audit_cycle()` не вызывается из оркестратора. CriticAgent — "мёртвый код". Добавить вызов после цикла, сохранение отчёта в БД, Telegram-уведомление при critical findings. | **done** |
| P0-8 | ✅ Убрать/ограничить fallback `get_secret()` на `os.getenv` | `scripts/secrets_manager.py` | — | `role="read"` по умолчанию fallback'ит на `os.getenv` без проверки роли. Любой код читает любые env-переменные. Сделать `allow_env_fallback=False` по умолчанию. | **done** |

---

## 🟡 ВЫСОКИЙ ПРИОРИТЕТ (P1) — 19/19 выполнено, 0 осталось

| ID | Задача | Файл | Описание | Статус |
|----|--------|------|----------|--------|
| P1-1 | ✅ Разбить Orchestrator на 3–4 сервиса | `scripts/orchestrator.py`, `scripts/services/` | Выделить CycleManager, TaskDispatcher, ReportGenerator, ActionExecutor. Orchestrator стал тонким фасадом (~435 строк). | **done** |
| P1-2 | ✅ Параллельный запуск агентов через `asyncio.gather()` | `scripts/services/cycle_manager.py` | `asyncio.gather()` + `Semaphore(MAX_PARALLEL_AGENTS)` с приоритетными группами (trend → SEO/SMM → остальные). Per-agent error isolation. | **done** |
| P1-3 | ✅ Токен-бакет rate limiter для LLM API | `scripts/orchestrator.py` | `TokenBucketRateLimiter` (RPM/TPM) с динамической подстройкой из заголовков ответа (`x-ratelimit-limit-*`). | **done** |
| P1-4 | ✅ Исправить CORS в Dashboard | `scripts/dashboard.py` | Заменить `*` на whitelist origin для POST-эндпоинтов. Добавить проверку origin/referer. | **done** |
| P1-5 | ✅ API key передавать только в header | `scripts/dashboard.py` | Убрать `request.query.get("api_key")`. Использовать `Authorization: Bearer <key>`. | **done** |
| P1-6 | ✅ Добавить аутентификацию для `/metrics` | `scripts/dashboard.py` | Basic auth или bearer token. `/health` оставить открытым с минимальной информацией. | **done** |
| P1-7 | ✅ Удалить дублирующий `save_metrics()` | `scripts/orchestrator.py` | Строки 2011–2052 — метод продублирован дважды подряд. | **done** |
| P1-8 | ✅ Исправить graceful shutdown | `scripts/orchestrator.py` | Использовать `asyncio.add_signal_handler()`. Ожидать завершения цикла. Закрывать все LLMClient. Использовать публичные методы MemoryStore. | **done** |
| P1-9 | ✅ Улучшить retry-логику: jitter + retryable/non-retryable + потолок | `scripts/orchestrator.py` | Добавить `random.uniform(0, 1)` к задержке. Разделить ошибки на retryable/non-retryable. `MAX_RETRY_DELAY = 60`. | **done** |
| P1-10 | ✅ Унифицировать валидаторы | `scripts/validator.py`, `scripts/orchestrator.py` | Использовать `validator.py` как единственный источник правды. Удалить дубли из `orchestrator.py`. Синхронизировать пороги (0.7 для PASSED). | **done** |
| P1-11 | ✅ Усилить Prompt Injection Protection | `scripts/orchestrator.py` | Защита от unicode-obфускации, zero-width chars, base64. Проверять `system_prompt` из конфига. Проверять ответ LLM. | **done** |
| P1-12 | ✅ Исправить `check_uniqueness()` — не возвращать 0.95 без базы | `scripts/validator.py` | Возвращать `None` или кидать исключение при отсутствии `reference_texts`. | **done** |
| P1-13 | ✅ Интегрировать secrets_manager в telegram_actions | `scripts/actions/telegram_actions.py` | Использовать `secrets_manager.get_secret("TELEGRAM_BOT_TOKEN")` вместо `os.getenv`. | **done** |
| P1-14 | ✅ Перевести Telegram rate limiter на Redis | `scripts/actions/telegram_actions.py` | Для поддержки multi-instance и сохранения состояния при рестарте. | **done** |
| P1-15 | ✅ Добавить ограничения в BrowserManager | `scripts/actions/browser_actions.py` | max_pages (LRU eviction), screenshot_quota, cleanup по TTL, whitelist доменов. | **done** |
| P1-16 | ✅ Убрать `ssl=False` в Reddit scanner | `scripts/actions/data_tools.py` | По умолчанию `ssl=True`. Сделать конфигурируемым через env. | **done** |
| P1-17 | ✅ Добавить persistence для audit log secrets_manager | `scripts/secrets_manager.py` | Загрузка из файла при старте, append-запись в JSON Lines. Путь через `AUDIT_LOG_FILE`. | **done** |
| P1-18 | ✅ Расширить A/B на content-agent и smm-agent | `scripts/orchestrator.py`, `scripts/ab_testing.py` | `AgentRunner.run()` интегрирован с `ABTestEnabledConfig`: выбор варианта при `ab_test: true`, запись validation score. | **done** |
| P1-19 | ✅ Расширить temperature-калибровку на content-agent и smm-agent | `scripts/temperature_calibration.py`, `scripts/orchestrator.py` | Multi-arm bandit (5 arms: 0.3–0.9), epsilon-greedy (ε=0.2), forced exploration, EMA. JSON-персистентность. | **done** |

---

## 🟢 СРЕДНИЙ ПРИОРИТЕТ (P2) — Запланировать

| ID | Задача | Файл | Описание | Оценка | Статус |
|----|--------|------|----------|--------|--------|
| P2-1 | ✅ Вынести магические числа в константы | `scripts/orchestrator.py` | 30+ магических чисел (длины title, meta, лимиты токенов, интервалы). Префикс `DEFAULT_`, переопределение через env. | 2 часа | **done** |
| P2-2 | ✅ Вынести бренд в переменную окружения | `configs/*.json` | `BRAND_NAME=smart-skidka.ru`, подставлять в промпты через шаблонизатор. | 1 час | **done** |
| P2-3 | ✅ Добавить JSON Schema валидацию конфигов | `scripts/orchestrator.py`, `AgentConfig` | Использовать `pydantic` или `jsonschema` для валидации структуры при загрузке. | 3 часа | **done** |
| P2-4 | ✅ Вынести `agent_type` в метод `AgentConfig` | `scripts/orchestrator.py` | `agent_type = property` вместо 5+ копий `split("-")[0]`. | 30 мин | **done** |
| P2-5 | ✅ Сделать CriticAgent singleton thread-safe | `scripts/critic_agent.py` | Использовать `threading.Lock()` или убрать singleton. | 30 мин | **done** |
| P2-6 | ✅ Исправить `get_validation_history` — имя колонки | `scripts/orchestrator.py` | Синхронизировать `created_at`/`timestamp` со схемой БД. | 15 мин | **done** |
| P2-7 | Исправить `mark_trend_recommendations_completed` | `scripts/orchestrator.py` | Помечать только выполненные рекомендации, добавить фильтр по `recommendation_id`. | 30 мин | **done** |
| P2-8 | Добавить тесты для непокрытых модулей | `tests/` | Приоритет: `validator.py`, `site_actions.py`, `telegram_actions.py`, `file_utils.py`. | 1–2 дня | **pending** |
| P2-9 | ✅ Заменить `print()` на structlog в telegram_actions | `scripts/actions/telegram_actions.py` | Единый стиль логирования проекта. | 15 мин | **done** |
| P2-10 | ✅ Заменить `datetime.utcnow()` на `datetime.now(timezone.utc)` | `scripts/secrets_manager.py` | Python 3.12+ deprecated `utcnow()`. | 1 час | **done** |
| P2-11 | Добавить latency-метрики для LLM API | `scripts/orchestrator.py` | Prometheus-метрики: `llm_request_duration_seconds`, `llm_request_duration_by_model`. | 2 часа | **pending** |
| P2-12 | Добавить per-agent error rate метрики | `scripts/orchestrator.py` | `agent_errors_total{agent="seo-agent"}`, `agent_validation_score{agent="..."}`. | 2 часа | **pending** |
| P2-13 | Добавить queue length / backlog метрики | `scripts/orchestrator.py` | Количество pending трендов, аналитических задач, отложенных публикаций. | 2 часа | **pending** |
| P2-14 | Добавить метрики по actions | `scripts/actions/*.py` | `actions_total{action="post_to_channel", status="success|error"}`, `action_duration_seconds`. | 3 часа | **pending** |
| P2-15 | Документировать секреты в secrets.enc.json | `configs/secrets.enc.json` | Заполнить `description` и `tags` для всех секретов. | 30 мин | **pending** |

---

## 📊 МЕТРИКИ КАЧЕСТВА КОДА

| Метрика | Было | Цель |
|---------|------|------|
| Критических багов (P0) | 8 | 0 ✅ |
| Серьёзных проблем (P1) | 19 | 8 осталось |
| Покрытие модулей тестами | 58% (11/19) | 100% |
| Покрытие строк тестами | ~22% | >40% |
| God-objects | 1 (Orchestrator) | 0 |
| Модулей без тестов | 8 | 0 |

---

## 🎯 РЕКОМЕНДУЕМЫЙ ПОРЯДОК ИСПРАВЛЕНИЙ

### Спринт 1 (неделя 1) — P0
| Задача | Оценка |
|--------|--------|
| P0-2 — Исправить `_get_session()` | 15 мин |
| P0-7 — Удалить дубль `save_metrics()` | 15 мин |
| P0-4 — HTML-escape в site_actions | 2 часа |
| P0-5 — Path traversal protection | 1 час |
| P0-3 — RBAC в ActionDispatcher | 2 часа |
| P0-8 — Ограничить fallback get_secret | 1 час |
| P0-6 — Синхронизировать Alembic | 4 часа |
| P0-1 — Circuit Breaker | 4 часа |
| P0-7 — Интегрировать CriticAgent | 3 часа |

### Спринт 2 (неделя 2) — P1 архитектура
| Задача | Оценка |
|--------|--------|
| P1-1 — Разбить Orchestrator | 2–3 дня |
| P1-2 — Параллельный запуск агентов | 4 часа |
| P1-3 — Токен-бакет rate limiter | 3 часа |
| P1-9 — Улучшить retry-логику | 2 часа |
| P1-8 — Исправить graceful shutdown | 2 часа |

### Спринт 3 (неделя 3) — P1 безопасность + Dashboard
| Задача | Оценка |
|--------|--------|
| P1-4 — CORS whitelist | 1 час |
| P1-5 — API key в header | 30 мин |
| P1-6 — Auth для /metrics | 1 час |
| P1-11 — Усилить Prompt Injection | 3 часа |
| P1-10 — Унифицировать валидаторы | 4 часа |
| P1-13 — secrets_manager в telegram_actions | 30 мин |
| P1-14 — Redis rate limiter | 3 часа |

### Спринт 4 (неделя 4) — P1 надежность + P2
| Задача | Оценка |
|--------|--------|
| P1-15 — BrowserManager ограничения | 2 часа |
| P1-16 — Убрать ssl=False | 15 мин |
| P1-17 — Audit log persistence | 3 часа |
| P1-18 — A/B для content/smm | 2 часа |
| P1-19 — Temperature для content/smm | 1 час |
| P2-8 — Тесты для непокрытых модулей | 2–3 дня |
| P2-11..14 — Новые метрики | 1 день |

---

## 📝 ПРИМЕЧАНИЯ

- Все изменения должны проходить через тесты (`tests/test_*.py`)
- Добавлять новые тесты при исправлении багов (цель: покрытие >40%)
- Обновлять `AGENTS.md` при изменении архитектуры
- Перед деплоем P0 — прогнать интеграционные тесты на staging
- ~~**Ключевой риск**: `LLM Judge` не работает~~ ✅ Исправлено (P0-2)
- ~~**Ключевой риск**: `CriticAgent` не интегрирован~~ ✅ Исправлено (P0-7)
