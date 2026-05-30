# 📋 Бэклог — Аудит Multi-Agent System smart-skidka

> Дата аудита: 2026-05-30
> Дата обновления: 2026-05-30
> Статус: Активный

---

## 🔴 КРИТИЧЕСКИЕ (P0) — Исправить немедленно

| ID | Задача | Файл | Строки | Описание | Критичность |
|----|--------|------|--------|----------|-------------|
| ~~P0-1~~ | ~~Исправить неопределённую переменную `redis`~~ | `scripts/orchestrator.py` | 2516, 2534 | ✅ **ИСПРАВЛЕНО** — добавлено `redis = await self.memory._get_redis()` перед обоими вызовами. Синтаксис и 33 тестов пройдены. | **Готово** |
| ~~P0-2~~ | ~~Удалить дублирование метода `save_metrics`~~ | `scripts/orchestrator.py` | 1796–1837 | ✅ **ИСПРАВЛЕНО** — удалён дублирующий блок (был unreachable из-за docstring посреди метода). Синтаксис и 33 тестов пройдены. | **Готово** |
| ~~P0-3~~ | ~~Привести схему БД к единому виду~~ | `scripts/orchestrator.py` + `init-scripts/01-schema.sql` | — | ✅ **ИСПРАВЛЕНО** — `init_schema()` синхронизирована с `01-schema.sql` (UUID, JSONB, индексы). `save_result()` и `update_validation_status()` обновлены под новую схему. Добавлены UNIQUE constraints для `trend_recommendations(trend_id, target_agent)` и `agent_tasks(agent_name, task_name)`. `ON CONFLICT` теперь работает корректно. | **Готово** |
| ~~P0-4~~ | ~~Исправить неопределённую переменную `redis` (регрессия)~~ | `scripts/orchestrator.py` | 2516, 2534 | ✅ **ИСПРАВЛЕНО** — добавлено `redis = await self.memory._get_redis()` перед `await redis.get(...)` и `await redis.delete(...)`. Все 57 тестов проходят. | **Готово** |
| ~~P0-5~~ | ~~Реализовать реальные инструменты сбора данных~~ | `scripts/actions/data_tools.py` (новый) | — | ✅ **ИСПРАВЛЕНО** — создан `scripts/actions/data_tools.py` (611 строк) с реализацией 6 инструментов: `google_trends` (RSS), `news_monitor` (RSS-агрегатор VC.ru/РБК/Хабр), `yandex_wordstat` (подсказки), `forum_scanner` (HackerNews API), `marketplace_trends` (Wildberries API), `gather_trend_data` (комбинированный). Все протестированы, 12 тестов проходят. | **Готово** |

### Детали P0-5 — Реализованные инструменты
| Инструмент | Источник | Статус | Покрытие тестами |
|------------|----------|--------|-----------------|
| `google_trends` | Google Trends RSS | ✅ Работает | `test_google_trends_*` |
| `news_monitor` | VC.ru, TJournal, РБК, Хабр (RSS) | ✅ Работает | `test_news_monitor_*` |
| `yandex_wordstat` | Яндекс подсказки | ✅ Работает | `test_yandex_wordstat_*` |
| `forum_scanner` | HackerNews API | ✅ Работает | `test_forum_scanner_*` |
| `marketplace_trends` | Wildberries API | ⚠️ 429 (нужны прокси) | `test_marketplace_*` |
| `gather_trend_data` | Комбинированный | ✅ Работает | `test_gather_trend_*` |

---

## 🟡 ВЫСОКИЙ ПРИОРИТЕТ (P1) — Исправить в текущем спринте

| ID | Задача | Файл | Описание | Приоритет |
|----|--------|------|----------|-----------|
| ~~P1-1~~ | ~~Включить или удалить `TelegramReporter`~~ | `scripts/orchestrator.py` | ✅ **ИСПРАВЛЕНО** — репортёр теперь включается автоматически при наличии `TELEGRAM_BOT_TOKEN` и `TELEGRAM_CHAT_ID`. Если переменные не заданы — логирует informational сообщение и отключается gracefully. | Готово |
| ~~P1-2~~ | ~~Исправить graceful shutdown для Redis~~ | `scripts/orchestrator.py` | ✅ **ИСПРАВЛЕНО** — `await self._redis.close()` заменено на `await self._redis.aclose()` (актуальный API redis-py 5.0+). | Готово |
| ~~P1-3~~ | ~~Добавить обработку отсутствия `.env`~~ | `scripts/orchestrator.py`, `scripts/content_generator.py`, `scripts/validator.py` | ✅ **ИСПРАВЛЕНО** — добавлена проверка `load_dotenv()` + `os.getenv("LLM_API_KEY")`. Если `.env` не найден и ключевые переменные не заданы — выдаётся `RuntimeWarning` с понятным описанием проблемы. | Готово |
| ~~P1-4~~ | ~~Вынести жёстко зашитые пути в конфигурацию~~ | `scripts/project_context.py`, `scripts/safe_project_context.py`, `scripts/actions/file_utils.py`, `scripts/actions/site_actions.py` | ✅ **ИСПРАВЛЕНО** — все 4 файла обновлены: `PROJECT_ROOT = os.getenv("PROJECT_ROOT", "/var/www/dealshub-miniapp")`. Путь можно переопределить через env. | Готово |
| ~~P1-5~~ | ~~Добавить retry для действий агентов~~ | `scripts/actions/*.py` | ✅ **ИСПРАВЛЕНО** — создан универсальный декоратор `with_retry()` в `actions/__init__.py` (поддерживает sync/async, exponential backoff, настраиваемые exceptions). Применён ко всем действиям: `post_to_channel`, `post_discount`, `update_meta_tags`, `prioritize_products`, `update_product_field`, `create_category_page`, `update_item_description`, `add_badge`. | Готово |
| ~~P1-6~~ | ~~Исправить утечку соединений Redis в Telegram Bot~~ | `scripts/telegram_bot.py` | ✅ **ИСПРАВЛЕНО** — Redis-подключение теперь singleton (`_get_redis()`). Создаётся один раз при первом вызове, закрывается через `redis_close()`. Убраны `aioredis.from_url()` + `aclose()` из каждой функции. | Готово |
| ~~P1-7~~ | ~~Внедрить LLM-as-a-Judge для валидации контента~~ | `scripts/llm_judge.py` (новый) | ✅ **ИСПРАВЛЕНО** — создан `scripts/llm_judge.py` (500+ строк) с `LLMJudge` (через LLM API) и `HeuristicJudge` (fallback без LLM). Критерии: relevance, readability, structure, usefulness, no_hallucinations. Есть `combined_validate()` для объединения rule-based + judge. 8 тестов проходят. | Готово |
| ~~P1-8~~ | ~~Добавить browser-based агент для веб-навигации~~ | `scripts/actions/browser_actions.py` (новый) | ✅ **ИСПРАВЛЕНО** — создан `scripts/actions/browser_actions.py` (563 строки) с `BrowserManager` (singleton Playwright), `check_page_render()` (meta, headings, structured data), `measure_core_vitals()` (LCP/CLS/load ratings + recommendations), `screenshot_product()`, `check_competitor()` (auto-detect selectors), batch-операции с semaphore. 10 тестов проходят. | **Готово** |
| ~~P1-9~~ | ~~Защитить `products.json` от перезаписи~~ | `scripts/actions/file_utils.py`, `scripts/actions/site_actions.py` | ✅ **ИСПРАВЛЕНО** — добавлен whitelist полей: `PRODUCTS_ALLOWED_FIELDS = {description, badge, priority, discount, promo_code, expires_at}` и `PRODUCTS_PROTECTED_FIELDS = {id, name, price, original_price, image, category, link, rating, reviews}`. Все actions (`update_item_description`, `add_badge`, `update_product_field`) проверяют поля перед записью. 10 тестов проходят. | Готово |

---

## 🟢 СРЕДНИЙ ПРИОРИТЕТ (P2) — Запланировать

| ID | Задача | Описание | Оценка |
|----|--------|----------|--------|
| ~~P2-1~~ | ~~Объединить дублирующие валидаторы~~ | ✅ **ИСПРАВЛЕНО** — класс `ResultValidator` (~540 строк) полностью удалён из `orchestrator.py`. Вся валидация теперь через `validator.py`: добавлен `validate_trend_result()`, обновлён `validate_by_type()` с поддержкой trend. `orchestrator.py` уменьшился с ~3200 до ~2685 строк. Импорт `validate_by_type` работает, все типы агентов валидаются корректно. | Готово |
| ~~P2-2~~ | ~~Добавить rate limiting для LLM API~~ | ✅ **ИСПРАВЛЕНО** — добавлен токен-бакет rate limiter в `LLMClient`. Лимит `LLM_RATE_LIMIT_RPS` (default 10 запросов/сек). Работает совместно с `asyncio.Semaphore` для ограничения concurrency. | Готово |
| ~~P2-3~~ | ~~Добавить health-check endpoint~~ | ✅ **ИСПРАВЛЕНО** — добавлен метод `Orchestrator.get_health_status()` возвращающий JSON с: status, running, agents_total/paused, cycle_count, total_errors, uptime_seconds, memory_connected, llm_client_ready. | Готово |
| ~~P2-4~~ | ~~Вынести магические числа в константы~~ | ✅ **ИСПРАВЛЕНО** — все магические числа вынесены в константы с префиксом `DEFAULT_` и возможностью переопределения через env: `AGENT_MAX_RETRIES`, `AGENT_RETRY_DELAY`, `AGENT_RETRY_BACKOFF`, `CYCLE_INTERVAL`, `DEFAULT_LLM_MODEL`, `DEFAULT_LLM_TEMPERATURE`, `DEFAULT_LLM_MAX_TOKENS`, `DEFAULT_LLM_TIMEOUT`, `DEFAULT_LLM_MAX_CONCURRENCY`, `LLM_RATE_LIMIT_RPS`. | Готово |
| ~~P2-5~~ | ~~Добавить circuit breaker для LLM API~~ | ✅ **ИСПРАВЛЕНО** — добавлен встроенный circuit breaker в `LLMClient` (3 состояния: closed/open/half_open). Порог: `LLM_CB_FAILURE_THRESHOLD` (default 5 ошибок), таймаут восстановления: `LLM_CB_RECOVERY_TIMEOUT` (default 30 сек). При открытом circuit breaker запросы мгновенно отклоняются с понятной ошибкой, предотвращая каскадные сбои. | Готово |
| ~~P2-6~~ | ~~Улучшить логирование ошибок валидации~~ | ✅ **ИСПРАВЛЕНО** — добавлен метод `Orchestrator.get_validation_history(agent_name, limit, min_score)` возвращающий историю валидации из БД с фильтрами и сводкой (avg_score, failed/warning/passed_count). | Готово |
| ~~P2-7~~ | ~~Добавить мониторинг метрик~~ | ✅ **ИСПРАВЛЕНО** — добавлен метод `Orchestrator.get_metrics()` возвращающий метрики в Prometheus-формате: cycles_total, errors_total, uptime_seconds, agents_total/paused/running, llm_circuit_breaker_state, orchestrator_running, memory_connected, llm_client_ready, reporter_enabled. | Готово |
| ~~P2-8~~ | ~~Добавить rate limiting для Telegram-постинга~~ | `scripts/actions/telegram_actions.py` | ✅ **ИСПРАВЛЕНО** — `TelegramRateLimiter` (singleton): debounce 5 мин между постами, дневной лимит 20 постов, per-agent cooldown. `post_to_channel()` проверяет лимиты перед отправкой. 7 тестов проходят. | **Готово** |
| ~~P2-9~~ | ~~Добавить квоты на создание файлов~~ | `scripts/actions/site_actions.py` | ✅ **ИСПРАВЛЕНО** — `check_category_page_quota()` (дневной лимит 10 страниц, auto-cleanup >24ч), `record_category_page_creation()` (JSON tracker), `get_quota_status()` (remaining info). 7 тестов проходят. | **Готово** |
| ~~P2-10~~ | ~~Улучшить self-correction (не blind retry)~~ | `scripts/orchestrator.py` — `AgentRunner.retry()` | ✅ **ИСПРАВЛЕНО** — `_analyze_error()` детектирует 5 типов ошибок (JSON/timeout/validation/empty/API) и возвращает targeted corrections. `retry()` адаптирует стратегию: при timeout уменьшает max_tokens вдвое, при JSON error инжектирует правила чистого JSON. 8 тестов проходят. | **Готово** |
| ~~P2-11~~ | ~~Добавить prompt injection защиту~~ | `scripts/orchestrator.py` — `AgentRunner._build_prompt()` | ✅ **ИСПРАВЛЕНО** — `_sanitize_context_value()`: 12 regex-паттернов для блокировки injection, ограничение длины (2000 символов), экранирование ```, рекурсивная санитизация list/dict. `_build_prompt()`: разделители контекста (BEGIN/END), предупреждение о нелегитимных инструкциях. 11 тестов проходят. | **Готово** |

---

## 🔵 НИЗКИЙ ПРИОРИТЕТ (P3) — В бэклог

| ID | Задача | Описание | Оценка |
|----|--------|----------|--------|
| **P3-1** | Плагинная система для actions | Сейчас actions захардкожены в `orchestrator.py`. Сделать динамическую загрузку actions по типу агента. | 3–5 дней |
| **P3-2** | Web UI для мониторинга агентов | Вместо Telegram — полноценный дашборд (Grafana / кастомный). | 5–7 дней |
| **P3-3** | A/B тестирование промптов | Сравнивать разные system_prompt и выбирать лучший по validation_score. | 3–5 дней |
| **P3-4** | Автоматическая калибровка temperature | Подбирать temperature динамически на основе истории успешности. | 2–3 дня |
| **P3-5** | Миграции БД | Сейчас схема создаётся `init_schema()`. Добавить `alembic` для версионирования. | 2 дня |
| **P3-6** | Локализация | Система заточена под русский. Добавить i18n для мультиязычности. | 3–5 дней |
| **P3-7** | Оптимизация памяти контекста | `get_context_for_agent()` читает большие файлы целиком. Добавить кэширование и lazy loading. | 1–2 дня |
| **P3-8** | Добавить subgoal-based evaluation | Валидация сейчас бинарная (passed/failed/warning). Добавить оценку выполнения подцелей (например, для SEO: title ✓, meta ✓, h1 ✗, schema ✓ → score 0.75). | 2–3 дня |
| **P3-9** | Интеграция с secrets manager | API-ключи (`LLM_API_KEY`, `TELEGRAM_BOT_TOKEN`) хранятся в `.env` plaintext. Перейти на Vault / AWS Secrets Manager / хотя бы зашифрованный `.env`. | 1–2 дня |
| **P3-10** | Добавить Critic Agent | Вторичный агент для аудита логов основного: проверка приверженности плану, обнаружение галлюцинаций аргументов, оценка качества эскалации. | 3–5 дней |

---

## 📊 МЕТРИКИ КАЧЕСТВА КОДА

| Метрика | Было | Стало | Цель |
|---------|------|-------|------|
| Всего строк кода (Python) | ~8,982 | ~12,000 | — |
| Покрытие тестами | ~2.3% (57 тестов) | ~7.1% (142 теста) | > 60% |
| Критических багов | 2 (P0-4, P0-5) | **0** | 0 |
| Серьёзных проблем | 2 | **0** | 0 |
| Дублирование кода | 0 | 0 | 0 |
| Жёстко зашитых путей | 0 | 0 | 0 |

### Распределение тестов по файлам
| Файл тестов | Количество | Что покрывает |
|-------------|-----------|---------------|
| `tests/test_agents.py` | 33 | ProjectContext, SafeProjectContext, safe zones |
| `tests/test_orchestrator.py` | 24 | Orchestrator с моками (cycle, validation, feedback) |
| `tests/test_data_tools.py` | 12 | Реальные инструменты сбора данных |
| `tests/test_llm_judge.py` | 8 | HeuristicJudge, критерии оценки |
| `tests/test_products_protection.py` | 10 | Whitelist/blacklist полей products.json |
| `tests/test_telegram_rate_limit.py` | 7 | Telegram rate limiting (debounce, daily limit) |
| `tests/test_file_quotas.py` | 7 | File creation quotas (daily limits) |
| `tests/test_smart_retry.py` | 19 | Smart retry + prompt injection protection |
| `tests/test_browser_actions.py` | 10 | Browser-based agent (Playwright) |
| `tests/test_context_cache.py` | 12 | Context cache (local + Redis, mtime invalidation) |
| **ИТОГО** | **142** | — |

---

## 🎯 РЕКОМЕНДУЕМЫЙ ПОРЯДОК ИСПРАВЛЕНИЙ

### ✅ Выполнено (P0 + P1 + P2)
| Задача | Статус | Оценка |
|--------|--------|--------|
| P0-1 — Исправить `redis` → `self.memory._get_redis()` | ✅ | 15 мин |
| P0-2 — Удалить дубль `save_metrics` | ✅ | 15 мин |
| P0-3 — Унифицировать схему БД (VARCHAR ↔ UUID) | ✅ | 1 час |
| P0-4 — Исправить `redis` NameError (регрессия) | ✅ | 15 мин |
| P0-5 — Реализовать 6 реальных инструментов данных | ✅ | 4 часа |
| P1-1 — Включить TelegramReporter | ✅ | 30 мин |
| P1-2 — Исправить `close()` → `aclose()` | ✅ | 15 мин |
| P1-3 — Валидация env-переменных | ✅ | 30 мин |
| P1-4 — Вынести пути в env | ✅ | 30 мин |
| P1-5 — Retry для actions | ✅ | 1 час |
| P1-6 — Оптимизировать Redis в telegram_bot | ✅ | 30 мин |
| P1-7 — LLM-as-a-Judge + HeuristicJudge | ✅ | 3 часа |
| P1-9 — Защита `products.json` (whitelist) | ✅ | 1 час |
| P2-1 — Объединить валидаторы | ✅ | 2 часа |
| P2-2 — Rate limiting LLM | ✅ | 1 час |
| P2-3 — Health-check endpoint | ✅ | 30 мин |
| P2-4 — Константы в конфиг | ✅ | 1 час |
| P2-5 — Circuit breaker | ✅ | 1 час |
| P2-6 — История ошибок валидации | ✅ | 1 час |
| P2-7 — Prometheus metrics | ✅ | 1 час |

### 📋 В бэклоге (P1 + P2 + P3)
| Задача | Статус | Оценка |
|--------|--------|--------|
| P1-8 — Browser-based агент (Playwright) | ✅ | 3–5 дней |
| P2-8 — Rate limiting Telegram | ✅ | 1 день |
| P2-9 — Квоты на создание файлов | ✅ | 1 день |
| P2-10 — Умный retry (не blind) | ✅ | 2–3 дня |
| P2-11 — Prompt injection защита | ✅ | 1–2 дня |
| P3-1 — Плагинная система actions | 📋 | 3–5 дней |
| P3-2 — Web UI дашборд | 📋 | 5–7 дней |
| P3-3 — A/B тестирование промптов | 📋 | 3–5 дней |
| P3-4 — Автокалибровка temperature | 📋 | 2–3 дня |
| P3-5 — Миграции БД (alembic) | 📋 | 2 дня |
| P3-6 — Локализация (i18n) | 📋 | 3–5 дней |
| P3-7 — Оптимизация памяти контекста | ✅ | 1–2 дня |
| P3-8 — Subgoal-based evaluation | 📋 | 2–3 дня |
| P3-9 — Secrets manager | 📋 | 1–2 дня |
| P3-10 — Critic Agent | 📋 | 3–5 дней |

---

## 📝 ПРИМЕЧАНИЯ

- Все изменения должны проходить через тесты (`tests/test_*.py`)
- Добавлять новые тесты при исправлении багов (цель: покрытие >60%)
- Обновлять `AGENTS.md` при изменении архитектуры
- Перед деплоем P0 — прогнать интеграционные тесты на staging
- **Ключевой риск продукта (частично снят)**: система теперь имеет реальные источники данных (RSS, API), но marketplace_trends требует дополнительной настройки (прокси/задержки) для стабильной работы с Wildberries.
