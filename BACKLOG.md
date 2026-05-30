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
| **P0-4** | **Исправить неопределённую переменную `redis` (регрессия)** | `scripts/orchestrator.py` | 2516, 2534 | 🐛 **АКТИВНЫЙ БАГ** — переменная `redis` используется без определения в `run_cycle()`. BACKLOG.md помечает P0-1 как исправленный, но в актуальном коде `redis = await self.memory._get_redis()` отсутствует перед `await redis.get(...)`. Вызывает `NameError` при проверке паузы и срочного запуска. | **Критический** |
| **P0-5** | **Реализовать реальные инструменты сбора данных** | `references/agents/*.json`, `scripts/actions/` | — | 🔴 **КРИТИЧЕСКИЙ ДЕФИЦИТ** — все агенты декларируют ~15 инструментов (`google_trends`, `marketplace_analytics`, `news_monitor`, `forum_scanner` и др.), но **ни один не реализован**. Trend Agent генерирует "тренды" на основе знаний LLM (галлюцинации), а не из реальных источников. Система "слепа" к реальному интернету. | **Критический** |

### Детали P0-4
```python
# СЕЙЧАС (баг в актуальном коде):
try:
    pause_key = f"agent:pause:{agent_name}"
    paused = await redis.get(pause_key)  # ← NameError: name 'redis' is not defined
    ...

try:
    run_now_key = f"agent:run_now:{agent_name}"
    run_now = await redis.get(run_now_key)  # ← NameError
    if run_now:
        await redis.delete(run_now_key)  # ← NameError

# ДОЛЖНО БЫТЬ:
try:
    redis = await self.memory._get_redis()
    pause_key = f"agent:pause:{agent_name}"
    paused = await redis.get(pause_key)
    ...
```

### Детали P0-5
| Инструмент | Статус | Риск |
|------------|--------|------|
| `google_trends` | ❌ Не реализован | Агент генерирует фейковые тренды |
| `yandex_wordstat` | ❌ Не реализован | SEO-агент работает вслепую |
| `marketplace_analytics` (Wildberries, Ozon) | ❌ Не реализован | Нет реальных данных о товарах |
| `social_trends` (TikTok, Telegram, VK) | ❌ Не реализован | SMM-агент не знает реальные тренды |
| `news_monitor` | ❌ Не реализован | Контент устаревает |
| `forum_scanner` (Пикабу, Reddit, Отзовик) | ❌ Не реализован | Нет социального слуха |
| `competitor_monitor` | ❌ Не реализован | Нет анализа конкурентов |
| `mshtools-web_search` | ❌ Не реализован | Нет поиска в интернете |
| `mshtools-ipython` | ❌ Не реализован | Нет Python-интерпретатора для агентов |

**Минимальный план реализации (MVP):**
1. `google_trends` — интеграция через `pytrends` или SerpAPI
2. `marketplace_analytics` — базовый скрейпинг Wildberries/Ozon через `aiohttp` + `BeautifulSoup`
3. `news_monitor` — RSS-агрегатор (Яндекс.Новости, VC.ru, РБК)

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
| **P1-7** | **Внедрить LLM-as-a-Judge для валидации контента** | `scripts/validator.py`, `scripts/orchestrator.py` | Валидация сейчас только rule-based (длина полей, обязательность, спам-скор). Нет оценки качества текста, релевантности, читаемости. Добавить вторичный LLM-вызов (или локальную модель) для оценки качества контента по шкале 1–10. Ожидаемый эффект: повышение TCR с ~55% до ~75%. | Высокий |
| **P1-8** | **Добавить browser-based агент для веб-навигации** | `scripts/actions/` (новый файл) | Система не может проверять реальные страницы, собирать данные с конкурентов, тестировать формы. Интегрировать Playwright для SEO-агента (проверка рендера страниц, Core Web Vitals) и Trend-агента (скриншоты трендовых товаров). | Высокий |
| **P1-9** | **Защитить `products.json` от перезаписи** | `scripts/safe_project_context.py` | `products.json` сейчас не в `PROTECTED_PATHS`, но является ядром сайта. Агенты могут перезаписывать его через `update_product_field`, `prioritize_products`, `add_badge`. Нужно либо добавить в PROTECTED_PATHS с whitelist-операциями, либо добавить бэкап перед каждой записью. | Высокий |

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
| **P2-8** | **Добавить rate limiting для Telegram-постинга** | `scripts/actions/telegram_actions.py` | Сейчас нет ограничений на частоту постинга в Telegram. Агент может спамить канал при каждом цикле. Добавить debounce: не чаще 1 поста в N минут на агента. | 1 день |
| **P2-9** | **Добавить квоты на создание файлов** | `scripts/actions/site_actions.py` | Нет лимита на количество создаваемых страниц через `create_category_page()`. Агент может исчерпать диск. Добавить дневную квоту (например, max 10 страниц/день). | 1 день |
| **P2-10** | **Улучшить self-correction (не blind retry)** | `scripts/orchestrator.py` — `AgentRunner.retry()` | Сейчас retry — это просто повторный запрос с тем же промптом. Добавить анализ причины ошибки (JSON parse → попросить без markdown; validation failed → передать правила валидации в контекст; timeout → уменьшить max_tokens). | 2–3 дня |
| **P2-11** | **Добавить prompt injection защиту** | `scripts/orchestrator.py` — `AgentRunner._build_prompt()` | Контекст от Trend Agent и Analytics Agent инжектируется в prompt без санитизации. Вредоносные данные в БД могут манипулировать LLM. Добавить фильтрацию спец-символов, ограничение длины, разделители. | 1–2 дня |

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

| Метрика | Значение | Цель |
|---------|----------|------|
| Всего строк кода (Python) | ~8,982 | — |
| Покрытие тестами | ~2.3% (57 тестов: 33 project_context + 24 orchestrator mocks) | > 60% |
| Критических багов | 1 (P0-4: redis NameError) | 0 |
| Серьёзных проблем | 1 (P0-5: фейковые тренды) | 0 |
| Дублирование кода | 0 | 0 |
| Жёстко зашитых путей | 0 | 0 |

---

## 🎯 РЕКОМЕНДУЕМЫЙ ПОРЯДОК ИСПРАВЛЕНИЙ

### 🔴 Срочно (P0)
| Задача | Статус | Оценка |
|--------|--------|--------|
| P0-4 — Исправить `redis` NameError (регрессия) | 🐛 Активен | 15 мин |
| P0-5 — Реализовать минимум 2–3 реальных инструмента данных | 🐛 Активен | 3–5 дней |

### 🟡 Высокий (P1)
| Задача | Статус | Оценка |
|--------|--------|--------|
| P1-7 — LLM-as-a-Judge для валидации | 📋 В бэклоге | 2–3 дня |
| P1-8 — Browser-based агент (Playwright) | 📋 В бэклоге | 3–5 дней |
| P1-9 — Защита `products.json` | 📋 В бэклоге | 2–4 часа |

### 🟢 Средний (P2)
| Задача | Статус | Оценка |
|--------|--------|--------|
| P2-8 — Rate limiting Telegram | 📋 В бэклоге | 1 день |
| P2-9 — Квоты на создание файлов | 📋 В бэклоге | 1 день |
| P2-10 — Умный retry (не blind) | 📋 В бэклоге | 2–3 дня |
| P2-11 — Prompt injection защита | 📋 В бэклоге | 1–2 дня |

### 🔵 Низкий (P3)
| Задача | Статус | Оценка |
|--------|--------|--------|
| P3-1 — Плагинная система actions | 📋 В бэклоге | 3–5 дней |
| P3-2 — Web UI дашборд | 📋 В бэклоге | 5–7 дней |
| P3-3 — A/B тестирование промптов | 📋 В бэклоге | 3–5 дней |
| P3-4 — Автокалибровка temperature | 📋 В бэклоге | 2–3 дня |
| P3-5 — Миграции БД (alembic) | 📋 В бэклоге | 2 дня |
| P3-6 — Локализация (i18n) | 📋 В бэклоге | 3–5 дней |
| P3-7 — Оптимизация памяти контекста | 📋 В бэклоге | 1–2 дня |
| P3-8 — Subgoal-based evaluation | 📋 В бэклоге | 2–3 дня |
| P3-9 — Secrets manager | 📋 В бэклоге | 1–2 дня |
| P3-10 — Critic Agent | 📋 В бэклоге | 3–5 дней |

---

## 📝 ПРИМЕЧАНИЯ

- Все изменения должны проходить через тесты (`tests/test_agents.py`, `tests/test_orchestrator.py`)
- Добавлять новые тесты при исправлении багов (цель: покрытие >60%)
- Обновлять `AGENTS.md` при изменении архитектуры
- Перед деплоем P0 — прогнать интеграционные тесты на staging
- **Ключевой риск продукта**: система генерирует контент на основе LLM-галлюцинаций вместо реальных данных. Это может привести к публикации нерелевантных трендов, устаревших промокодов и бессмысленного SEO-контента.
