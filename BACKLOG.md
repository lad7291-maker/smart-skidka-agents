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
| ~~P3-1~~ | ~~Плагинная система для actions~~ | ✅ **ИСПРАВЛЕНО** — `@register_action` декоратор с маппингом на типы агентов. `ActionRegistry` (глобальный `_REGISTRY`) + `ActionDispatcher` (выполнение по JSON-конфигу с `input_map`, `condition`, вложенные ключи). `discover_actions()` для авто-импорта модулей. Orchestrator использует плагинную диспетчеризацию с fallback на legacy. Конфиги агентов обновлены (seo, smm, content). 19 тестов проходят. | **Готово** |
| ~~P3-2~~ | ~~Web UI для мониторинга агентов~~ | ✅ **ИСПРАВЛЕНО** — `scripts/dashboard.py` (aiohttp.web): `/health`, `/metrics` (Prometheus), `/api/agents`, `/api/cycles`, `/api/validations`, `/api/errors`, `/api/trends`. Control: `POST /api/agents/{name}/pause|resume|run_now` (те же Redis keys что и telegram_bot). API key middleware, CORS, HTML landing page. 12 тестов проходят. | **Готово** |
| ~~P3-3~~ | ~~A/B тестирование промптов~~ | ✅ **ИСПРАВЛЕНО** — `PromptVariant` (dataclass) + `PromptVariantRegistry` (JSON-файлы): добавление, round-robin выбор, 80/20 exploitation/exploration. `ABTestEvaluator`: сравнение по avg validation_score, promotion победителя при достижении `AB_TEST_MIN_RUNS` (default 10) и `AB_TEST_CONFIDENCE_THRESHOLD`. `ABTestEnabledConfig`: обертка для `AgentConfig` с инжекцией варианта. 15 тестов проходят. | **Готово** |
| ~~P3-4~~ | ~~Автоматическая калибровка temperature~~ | ✅ **ИСПРАВЛЕНО** — `TemperatureArm` (EMA score tracking) + `AgentCalibration` (ε-greedy bandit): 5 дискретных arms [0.5..0.9], forced exploration до `min_runs` (default 5), 15% ε-exploration / 85% exploitation лучшего EMA. `TemperatureCalibrator`: JSON-персистентность per-agent, enable/disable/reset. Конфигурируется через env vars. 18 тестов проходят. | **Готово** |
| ~~P3-5~~ | ~~Миграции БД~~ | ✅ **ИСПРАВЛЕНО** — `alembic init` выполнен, `alembic.ini` настроен для PostgreSQL. Начальная миграция `001_initial_schema.py` создаёт все таблицы из `init-scripts/01-schema.sql` (orchestrator_cycles, agent_results, metrics, agent_errors, agent_memory, generated_content, agent_tasks, trend_detections, trend_data_sources, trend_recommendations, agent_trend_context, agent_pages, content_registry) + индексы + начальные данные. `downgrade()` удаляет все таблицы. 10 тестов проходят. | **Готово** |
| ~~P3-6~~ | ~~Локализация~~ | ✅ **ИСПРАВЛЕНО** — Полноценная gettext-style i18n система в `scripts/i18n.py`: `_()` (gettext), `n_()` (plural forms с CLDR-правилами для ru/en), `p_()` (context-aware), `np_()` (context + plural), `lazy_()`/`lazy_n_()` (отложенные переводы). JSON-хранилище `configs/i18n/{ru,en}.json` с pipe-разделёнными plural forms. Поддержка `.mo`/`.po` (gettext binary/text). `I18nProcessor` для structlog (автоперевод `i18n:`-префиксных строк). `Extractor` для сканирования `_()`, `n_()`, `p_()`, `np_()` из Python-кода и генерации `.pot`. Зависимость: `Babel`. 30 тестов проходят. | **Готово** |
| ~~P3-7~~ | ~~Оптимизация памяти контекста~~ | ✅ **ИСПРАВЛЕНО** — `ContextCache` (двухуровневый: local + Redis): кэш `last_results` из Redis (уже писался в `save_result`), кэш `trend_recs`/`analytics_tasks` (TTL 60s), кэш `project_context` по хэшу mtime файлов (TTL 300s). Файловый I/O перенесён в `asyncio.to_thread()`. Инвалидация при записи результата. 12 тестов проходят. | **Готово** |
| ~~P3-8~~ | ~~Добавить subgoal-based evaluation~~ | ✅ **ИСПРАВЛЕНО** — `SubgoalEvaluator` с атомарными чекерами (`Checkers`): `field_exists`, `string_length`, `contains_any`, `list_size`, `no_duplicates`, `fields_differ`, `has_structure`, `word_count_range`. Subgoal-определения для 7 типов агентов (seo: 13 subgoals, smm: 7, content: 9, performance: 7, email: 6, analytics: 6, trend: 5) с весами. Бинарные и градуированные оценки (0.0–1.0). `SubgoalEvaluation`: overall_score, per-subgoal breakdown, summary. Интеграция с `ValidationResult` через `merge_with_validation()` → combined_score. Runtime добавление subgoals. 43 теста проходят. | **Готово** |
| ~~P3-9~~ | ~~Интеграция с secrets manager~~ | ✅ **ИСПРАВЛЕНО** — `SecretsManager` с AES-256-GCM шифрованием и PBKDF2-HMAC-SHA256 (480K итераций, OWASP). Master key из env (`SECRETS_MASTER_KEY`) или файла (`configs/.master.key`, auto-generated с `chmod 600`). Ролевая модель: READ (standard secrets), WRITE (standard+sensitive), ADMIN (all + key rotation). `SecretLevel`: STANDARD / SENSITIVE / CRITICAL. Audit log с фильтрацией. Функции: `get_secret()` (drop-in замена `os.getenv()`), `set_secret()`, `delete_secret()`, `list_secrets()`, `rotate_master_key()`, `migrate_env_secrets()`. Интеграция с `.env` через fallback. Зависимость: `cryptography`. 41 тест проходит. | **Готово** |
| **P3-10** | Добавить Critic Agent | Вторичный агент для аудита логов основного: проверка приверженности плану, обнаружение галлюцинаций аргументов, оценка качества эскалации. | 3–5 дней |

---

## 📊 МЕТРИКИ КАЧЕСТВА КОДА

| Метрика | Было | Стало | Цель |
|---------|------|-------|------|
| Всего строк кода (Python) | ~8,982 | ~16,000 | — |
| Покрытие тестами | ~2.3% (57 тестов) | ~10.3% (206 тестов) | > 60% |
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
| `tests/test_action_registry.py` | 19 | Plugin system for actions (registry, dispatcher) |
| `tests/test_dashboard.py` | 12 | Web UI dashboard (aiohttp, health, metrics, control) |
| `tests/test_ab_testing.py` | 15 | A/B testing for prompts (registry, evaluator) |
| `tests/test_temperature_calibration.py` | 18 | Auto temperature calibration (ε-greedy bandit, EMA) |
| `tests/test_alembic.py` | 10 | Alembic migrations (setup, syntax, tables, indexes) |
| `tests/test_i18n.py` | 30 | i18n: gettext, plural, context, lazy, extractor, structlog |
| `tests/test_subgoal_evaluator.py` | 43 | Subgoal-based evaluation (SEO/SMM/content/performance/email/analytics/trend) |
| `tests/test_secrets_manager.py` | 41 | Secrets manager (AES-256-GCM, RBAC, audit, rotation) |
| **ИТОГО** | **330** | — |

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
| P3-1 — Плагинная система actions | ✅ | 3–5 дней |
| P3-2 — Web UI дашборд | ✅ | 5–7 дней |
| P3-3 — A/B тестирование промптов | ✅ | 3–5 дней |
| P3-4 — Автокалибровка temperature | ✅ | 2–3 дня |
| P3-5 — Миграции БД (alembic) | ✅ | 2 дня |
| P3-6 — Локализация (i18n) | ✅ | 3–5 дней |
| P3-7 — Оптимизация памяти контекста | ✅ | 1–2 дня |
| P3-8 — Subgoal-based evaluation | ✅ | 2–3 дня |
| P3-9 — Secrets manager | ✅ | 1–2 дня |
| P3-10 — Critic Agent | 📋 | 3–5 дней |

---

## 📝 ПРИМЕЧАНИЯ

- Все изменения должны проходить через тесты (`tests/test_*.py`)
- Добавлять новые тесты при исправлении багов (цель: покрытие >60%)
- Обновлять `AGENTS.md` при изменении архитектуры
- Перед деплоем P0 — прогнать интеграционные тесты на staging
- **Ключевой риск продукта (частично снят)**: система теперь имеет реальные источники данных (RSS, API), но marketplace_trends требует дополнительной настройки (прокси/задержки) для стабильной работы с Wildberries.
