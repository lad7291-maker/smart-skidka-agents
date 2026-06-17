# Системный аудит smart-skidka-agents

**Дата аудита:** 2026-06-04  
**Аудитор:** Kimi Code CLI (автоматизированный аудит на основе статического анализа)  
**Объём кодовой базы:** ~19,100 строк Python (scripts/ + tests/)  
**Тесты:** 362 теста, ~4,230 строк  

---

## Краткий вывод

Архитектура smart-skidka-agents демонстрирует продуманный подход к мульти-агентной оркестрации с хорошим разделением ответственности на уровне мелких классов (AgentConfig, LLMClient, TelegramReporter) и богатым набором вспомогательных систем (A/B-тестирование, temperature-калибровка, i18n, secrets manager, critic agent). Однако центральный `Orchestrator` (~1,100 строк) стал классическим god-object, нарушающим SRP. Критические проблемы: **отсутствие реального Circuit Breaker** (есть только упоминание в строке обработки ошибок), **последовательный запуск агентов** вместо параллельного, **критический баг в LLM Judge** (`_get_session()` вызывается без `self.`), **несогласованность Alembic-миграции со SQL-скриптом** (нет FOREIGN KEY, CHECK constraints, части индексов). Безопасность: RBAC в ActionRegistry не проверяется при выполнении, HTML/XML-контент в site_actions не экранируется, path traversal в file_utils не защищён. Наблюдаемость: базовые Prometheus-метрики есть, но нет latency-метрик, метрик по очередям и per-agent error rate. CriticAgent реализован, но **не интегрирован в production-цикл** оркестратора — "мёртвый код". Покрытие тестами ~11.5%, при этом 8 ключевых модулей (content_generator, validator, telegram_bot, site_actions, telegram_actions, file_utils, project_context, safe_project_context) вообще не имеют тестов.

---

## Ключевые проблемы и риски

### 🔴 P0 — Критично

– **[P0] Отсутствует реальный Circuit Breaker для LLM API.**  
В `orchestrator.py` есть только упоминание circuit breaker в строке обработки ошибок (`"circuit" in error_lower`), но нет реализации состояний closed/open/half_open, счётчика ошибок, таймера восстановления. При сбое LLM API система будет бесконечно retry-ить без глобальной защиты. Файл: `scripts/orchestrator.py`, строка ~1465.

– **[P0] Критический баг в LLM Judge: `_get_session()` вызывается без `self.`.**  
В `scripts/llm_judge.py`, строка 110: `session = await _get_session()` — глобальная функция не определена, должен быть `self._get_session()`. Это означает, что `LLMJudge` фактически **не работает** — всегда падает с `NameError`, и fallback на `HeuristicJudge` срабатывает через `except Exception`. Валидация через LLM Judge — фикция.

– **[P0] RBAC в ActionRegistry не проверяется при выполнении.**  
Декоратор `@register_action(agent_types=["smm"])` задаёт разрешённые типы агентов, но `ActionDispatcher.execute()` и `execute_agent_actions()` **не проверяют** `agent_types`. Любой агент может вызвать любой action, зная его имя. Файл: `scripts/actions/action_registry.py`.

– **[P0] HTML/XML-инъекция в site_actions.**  
`update_meta_tags`, `create_category_page`, `update_sitemap`, `add_cross_links` вставляют пользовательские данные (`title`, `description`, `category_name`, `item.get('title')`, `item.get('link')`) в HTML/XML через `re.sub` **без escape**. Возможна XSS-атака или ломка структуры сайта. Файл: `scripts/actions/site_actions.py`.

– **[P0] Path traversal в file_utils.**  
`safe_write(path, content)` принимает `path` как `Path`, но **не проверяет**, что он находится внутри `SITE_ROOT`. Любой action может записать файл в любое место файловой системы. Файл: `scripts/actions/file_utils.py`.

– **[P0] Alembic-миграция не синхронизирована со SQL-скриптом.**  
`alembic/versions/001_initial_schema.py` не содержит: FOREIGN KEY constraints, CHECK constraints (enum-валидация, confidence range), части индексов (`idx_trend_detections_peak_date`, `idx_trend_recommendations_priority` и др.), seed-данные. БД, созданная через `alembic upgrade`, будет иметь другую схему, чем через `init-scripts/01-schema.sql`.

– **[P0] CriticAgent не интегрирован в production-цикл.**  
`scripts/critic_agent.py` реализован (~540 строк, 30 тестов), но **не вызывается** из `orchestrator.py`. Поиск по `critic_agent`, `CriticAgent`, `audit_cycle` в оркестраторе не даёт результатов. Это "мёртвый код" — задача P3-10 из BACKLOG выполнена формально, но не приносит ценности.

– **[P0] Fallback `get_secret()` на `os.getenv` обходит RBAC.**  
`secrets_manager.get_secret()` с `role="read"` по умолчанию fallback'ит на `os.getenv(key, default)` без проверки роли. Любой код может читать любые env-переменные. Файл: `scripts/secrets_manager.py`.

### 🟡 P1 — Важно

– **[P1] Orchestrator — god-object (~1,100 строк).**  
`Orchestrator` (строки 2378–3482) содержит: управление жизненным циклом, диспетчеризацию трендов/аналитики, выполнение legacy actions, генерацию отчётов, feedback loop, health status, валидацию, обработку ошибок. Нарушает SRP, затрудняет тестирование и поддержку.

– **[P1] Агенты запускаются последовательно, не параллельно.**  
В `orchestrator.py`, строка ~2722: `for config in self.agents:` — цикл по агентам без `asyncio.gather()`. При 7 агентах и таймауте 120s цикл может занять >14 минут. Нет приоритезации, нет backpressure.

– **[P1] Rate limiting только через Semaphore(5), нет токен-бакета.**  
`LLMClient` использует `asyncio.Semaphore(5)` для ограничения параллельных HTTP-запросов, но нет ограничения RPM/TPM, нет динамического регулирования на основе заголовков `X-RateLimit-Remaining`.

– **[P1] CORS `*` на POST-эндпоинтах Dashboard.**  
`scripts/dashboard.py` разрешает `Access-Control-Allow-Origin: *` для всех запросов, включая POST `/api/agents/{name}/pause|resume|run_now`. Злоумышленник может вызвать control endpoints с вредоносного сайта, если жертва авторизована.

– **[P1] API key передаётся в query string.**  
Dashboard проверяет `request.query.get("api_key")` — API key попадает в логи прокси/серверов. Должен передаваться только в header.

– **[P1] /metrics и /health доступны без аутентификации.**  
Любой может получить операционную информацию: статус БД, Redis, количество циклов, ошибки, средний validation score. Риск инфраструктурной разведки.

– **[P1] Дублирование `save_metrics()` в orchestrator.py.**  
Строки 2011–2052: метод `save_metrics()` полностью продублирован (дважды подряд). Будет выполнен дважды — явный баг copy-paste.

– **[P1] Graceful shutdown с багами.**  
Сигнальный обработчик синхронный в async-контексте (риск гонки). Нет ожидания завершения текущего цикла. Не закрываются индивидуальные `LLMClient` агентов. `MemoryStore.close()` использует приватный атрибут `_closed` asyncpg.

– **[P1] Retry-логика без jitter и без различия retryable/non-retryable.**  
Exponential backoff есть, но фиксированные интервалы создают риск thundering herd. Retry делается на ЛЮБУЮ ошибку, включая логические. Нет потолка задержки.

– **[P1] Несогласованные пороги валидации между validator.py и orchestrator.py.**  
SEO в orchestrator требует `final_score >= 0.7` для PASSED, в `validator.py` — `final_score < 0.5` для FAILED. Разные списки spam keywords. Дублирование логики валидации.

– **[P1] Prompt Injection Protection — базовая, с пробелами.**  
14 regex-паттернов, но нет защиты от unicode-обфускации, zero-width chars, base64-кодирования. `system_prompt` из конфига не проверяется. Нет проверки ответа LLM на инъекции.

– **[P1] `check_uniqueness()` возвращает 0.95 при отсутствии reference_texts.**  
Фиктивная уникальность — ложное чувство безопасности. Файл: `scripts/validator.py`.

– **[P1] Telegram actions не используют secrets_manager.**  
`BOT_TOKEN` и `CHANNEL_ID` берутся из `os.getenv` напрямую, обходя шифрованное хранилище. Файл: `scripts/actions/telegram_actions.py`.

– **[P1] Rate limiter Telegram in-memory — не работает в multi-instance.**  
`TelegramRateLimiter` хранит состояние в памяти процесса. При рестарте или горизонтальном масштабировании лимиты сбрасываются.

– **[P1] BrowserManager — singleton без ограничения страниц, утечка ресурсов.**  
Может привести исчерпанию памяти при массовых вызовах. Скриншоты сохраняются в `/tmp` без квоты диска. Файл: `scripts/actions/browser_actions.py`.

– **[P1] `ssl=False` в Reddit scanner.**  
Отключена проверка SSL-сертификатов — MITM-уязвимость. Файл: `scripts/actions/data_tools.py`, строка 558.

– **[P1] Audit log secrets_manager только in-memory.**  
При рестарте процесса вся история аудита теряется. Нет защиты от tampering. Файл: `scripts/secrets_manager.py`.

– **[P1] A/B-варианты и temperature-калибровка только для seo-agent.**  
Content-agent и smm-agent не покрыты. Система оптимизирует только один из семи агентов.

### 🟢 P2 — Средний/Низкий приоритет

– **[P2] Магические числа не вынесены в константы.**  
30+ магических чисел в `orchestrator.py` (длины title, meta, лимиты токенов, интервалы). Часть вынесена в env, но большинство захардкожено.

– **[P2] Жёстко закодированный бренд `smart-skidka.ru` во всех промптах.**  
При смене проекта требуется редактировать все конфиги. Должен быть вынесен в переменную.

– **[P2] Нет JSON Schema валидации конфигов агентов.**  
`AgentConfig.load_config()` использует `dict.get()` с дефолтами — некорректный конфиг загрузится без ошибки.

– **[P2] `agent_name.split("-")[0]` повторяется 5+ раз.**  
Хрупкая логика извлечения типа агента. Должна быть вынесена в метод `AgentConfig`.

– **[P2] CriticAgent — singleton не thread-safe.**  
Глобальная переменная `_critic_singleton` без блокировок.

– **[P2] `get_validation_history` использует `created_at`, но в схеме колонка `timestamp`.**  
Потенциальный баг при запросе истории. Файл: `scripts/orchestrator.py`, строки 3376–3383.

– **[P2] `mark_trend_recommendations_completed` помечает ВСЕ pending рекомендации как completed.**  
А не только выполненные действия. Файл: `scripts/orchestrator.py`, строки 2893–2907.

– **[P2] Нет тестов для 8 ключевых модулей.**  
`content_generator.py`, `validator.py`, `telegram_bot.py`, `site_actions.py`, `telegram_actions.py`, `file_utils.py`, `project_context.py`, `safe_project_context.py` — нет тестовых файлов.

– **[P2] `print()` вместо structured logging в telegram_actions.**  
Нарушает единый стиль логирования проекта.

– **[P2] `datetime.utcnow()` deprecated в Python 3.12+.**  
Используется в `secrets_manager.py` и других модулях. Рекомендуется `datetime.now(timezone.utc)`.

---

## Рекомендации по улучшению

### P0 — критично

1. **Реализовать настоящий Circuit Breaker для LLMClient.**  
   Добавить состояния closed/open/half_open, счётчик ошибок (порог 5), таймер восстановления (30s). При открытом circuit — мгновенный reject с понятной ошибкой. Файлы: `scripts/orchestrator.py` (LLMClient), константы в env.

2. **Исправить баг `_get_session()` → `self._get_session()` в LLM Judge.**  
   Однострочное исправление в `scripts/llm_judge.py`, строка 110. Добавить retry с exponential backoff для LLM Judge API. Добавить валидацию score (0.0–1.0).

3. **Добавить RBAC-проверку в ActionDispatcher.execute().**  
   Перед выполнением action сверять тип вызывающего агента со списком `agent_types` из `ActionDef`. При несовпадении — логировать security warning и отклонять. Файл: `scripts/actions/action_registry.py`.

4. **HTML/XML-escape всех пользовательских данных в site_actions.**  
   Использовать `html.escape()` перед вставкой в HTML/XML. Валидировать URL в `item.get('link')` и `image`. Ограничить длину `category_name`. Файл: `scripts/actions/site_actions.py`.

5. **Добавить path traversal protection в file_utils.**  
   Проверять, что `path.resolve()` находится внутри `SITE_ROOT`. Исправить rollback-логику (сохранять ссылку на бэкап). Сделать `validate=True` по умолчанию в `write_products()`. Файл: `scripts/actions/file_utils.py`.

6. **Синхронизировать Alembic-миграцию со SQL-скриптом.**  
   Добавить в `001_initial_schema.py`: `ForeignKeyConstraint`, `CheckConstraint`, недостающие индексы, seed-данные через `op.bulk_insert()`. Или отказаться от двойной схемы — использовать только Alembic.

7. **Интегрировать CriticAgent в production-цикл оркестратора.**  
   Вызывать `audit_cycle()` после завершения каждого цикла. Сохранять `CriticReport` в БД (`agent_results` или новая таблица `critic_reports`). Добавить Telegram-уведомление при critical findings. Файлы: `scripts/orchestrator.py`, `scripts/critic_agent.py`.

8. **Убрать или ограничить fallback `get_secret()` на `os.getenv`.**  
   Сделать параметр `allow_env_fallback=False` по умолчанию. Добавить отдельную функцию `get_secret_or_env()` для явного opt-in. Файл: `scripts/secrets_manager.py`.

### P1 — важно

9. **Разбить Orchestrator на 3–4 отдельных сервиса.**  
   Выделить: `CycleManager` (циклы и планирование), `TaskDispatcher` (диспетчеризация агентов), `ReportGenerator` (отчёты), `ActionExecutor` (выполнение actions). Уменьшит `orchestrator.py` с ~3500 до <1500 строк.

10. **Параллельный запуск агентов через `asyncio.gather()` с `Semaphore`.**  
    Добавить `asyncio.Semaphore(N)` на уровне Orchestrator для ограничения concurrency. Сохранить возможность приоритезации (trend_agent → SEO/SMM → остальные). Файл: `scripts/orchestrator.py`, метод `run_cycle()`.

11. **Добавить токен-бакет rate limiter для LLM API.**  
    RPM/TPM лимиты с динамическим регулированием на основе заголовков ответа. Файл: `scripts/orchestrator.py`, класс `LLMClient`.

12. **Исправить CORS в Dashboard: заменить `*` на whitelist.**  
    Для POST-эндпоинтов проверять origin/referer. API key передавать только в header (`Authorization: Bearer <key>`). Добавить rate limiting. Файл: `scripts/dashboard.py`.

13. **Добавить аутентификацию для `/metrics`.**  
    Basic auth или bearer token. `/health` можно оставить открытым, но с минимальной информацией.

14. **Удалить дублирующий `save_metrics()` в orchestrator.py.**  
    Строки 2011–2052 — удалить вторую копию метода.

15. **Исправить graceful shutdown.**  
    Использовать `asyncio.get_event_loop().add_signal_handler()`. Добавить таймаут на ожидание завершения текущего цикла. Закрывать все индивидуальные `LLMClient` агентов. Использовать публичные методы `MemoryStore`. Файл: `scripts/orchestrator.py`.

16. **Улучшить retry-логику: jitter + retryable/non-retryable + потолок.**  
    Добавить `random.uniform(0, 1)` к задержке. Разделить ошибки на retryable (timeout, 5xx, rate limit) и non-retryable (4xx, validation, auth). Добавить `MAX_RETRY_DELAY = 60`. Файл: `scripts/orchestrator.py`, `AgentRunner.retry()`.

17. **Унифицировать валидаторы: удалить дубли из orchestrator.py.**  
    Использовать `scripts/validator.py` как единственный источник правды. Синхронизировать пороги (0.7 для PASSED во всех модулях). Файлы: `scripts/validator.py`, `scripts/orchestrator.py`.

18. **Усилить Prompt Injection Protection.**  
    Добавить защиту от unicode-obfuscation, zero-width chars, base64. Проверять `system_prompt` из конфига. Проверять ответ LLM на инъекции перед парсингом. Файл: `scripts/orchestrator.py`, `AgentRunner._sanitize_context_value()`.

19. **Исправить `check_uniqueness()` — возвращать `None` при отсутствии базы.**  
    Или кидать исключение. Не возвращать фиктивный 0.95. Файл: `scripts/validator.py`.

20. **Интегрировать secrets_manager в telegram_actions.**  
    Использовать `secrets_manager.get_secret("TELEGRAM_BOT_TOKEN")` вместо `os.getenv`. Файл: `scripts/actions/telegram_actions.py`.

21. **Перевести Telegram rate limiter на Redis.**  
    Для поддержки multi-instance и сохранения состояния при рестарте. Файл: `scripts/actions/telegram_actions.py`.

22. **Добавить ограничения в BrowserManager.**  
    Макс. количество страниц, квота на скриншоты (количество/размер), cleanup по TTL, whitelist доменов для `check_competitor`. Файл: `scripts/actions/browser_actions.py`.

23. **Убрать `ssl=False` в Reddit scanner или сделать конфигурируемым.**  
    По умолчанию `ssl=True`. Файл: `scripts/actions/data_tools.py`.

24. **Добавить persistence для audit log secrets_manager.**  
    Писать в append-only файл или отправлять в SIEM. Добавить HMAC файла для tamper detection. Файл: `scripts/secrets_manager.py`.

25. **Расширить A/B и temperature на content-agent и smm-agent.**  
    Создать `configs/variants/content-agent.variants.json`, `configs/variants/smm-agent.variants.json`, аналогично для temperatures. Файлы: `configs/`, `scripts/ab_testing.py`, `scripts/temperature_calibration.py`.

### P2 — желательно

26. **Вынести магические числа в константы с префиксом `DEFAULT_`.**  
    С возможностью переопределения через env. Файл: `scripts/orchestrator.py`.

27. **Вынести бренд в переменную окружения.**  
    `BRAND_NAME=smart-skidka.ru`, подставлять в промпты через шаблонизатор. Файлы: `configs/*.json`.

28. **Добавить JSON Schema валидацию конфигов.**  
    Использовать `pydantic` или `jsonschema` для валидации структуры конфига при загрузке. Файл: `scripts/orchestrator.py`, `AgentConfig`.

29. **Вынести `agent_type` из `agent_name` в метод `AgentConfig`.**  
    `agent_type = property` или `get_agent_type()` — вместо 5+ копий `split("-")[0]`. Файл: `scripts/orchestrator.py`.

30. **Сделать CriticAgent singleton thread-safe.**  
    Использовать `threading.Lock()` или убрать singleton в пользу явного создания. Файл: `scripts/critic_agent.py`.

31. **Исправить `get_validation_history` — использовать правильное имя колонки.**  
    Проверить схему БД и синхронизировать с кодом. Файл: `scripts/orchestrator.py`.

32. **Исправить `mark_trend_recommendations_completed` — помечать только выполненные.**  
    Добавить фильтр по `recommendation_id`. Файл: `scripts/orchestrator.py`.

33. **Добавить тесты для непокрытых модулей.**  
    Приоритет: `validator.py`, `site_actions.py`, `telegram_actions.py`, `file_utils.py`. Файлы: `tests/test_validator.py`, `tests/test_site_actions.py` и т.д.

34. **Заменить `print()` на structlog в telegram_actions.**  
    Файл: `scripts/actions/telegram_actions.py`.

35. **Заменить `datetime.utcnow()` на `datetime.now(timezone.utc)`.**  
    Во всех модулях. Файлы: `scripts/secrets_manager.py`, `scripts/orchestrator.py` и др.

---

## Проверочный чек-лист

1. [ ] Реализован Circuit Breaker для LLMClient с состояниями closed/open/half_open
2. [ ] Исправлен баг `_get_session()` → `self._get_session()` в LLM Judge
3. [ ] RBAC проверяет `agent_types` перед выполнением action в ActionDispatcher
4. [ ] HTML/XML-escape применяется ко всем пользовательским данным в site_actions
5. [ ] Path traversal protection проверяет `path.resolve()` внутри `SITE_ROOT`
6. [ ] Alembic-миграция синхронизирована с SQL-скриптом (FK, CHECK, индексы, seed)
7. [ ] CriticAgent интегрирован в production-цикл и вызывается после каждого цикла
8. [ ] `get_secret()` не fallback'ит на `os.getenv` без явного разрешения
9. [ ] Orchestrator разбит на 3–4 отдельных сервиса (CycleManager, TaskDispatcher, ReportGenerator, ActionExecutor)
10. [ ] Агенты запускаются параллельно через `asyncio.gather()` с `Semaphore`
11. [ ] Токен-бакет rate limiter ограничивает RPM/TPM для LLM API
12. [ ] CORS в Dashboard разрешает только whitelist origin для POST-запросов
13. [ ] API key передаётся только в header, не в query string
14. [ ] `/metrics` защищён аутентификацией
15. [ ] Удалено дублирование `save_metrics()` в orchestrator.py
16. [ ] Graceful shutdown использует `add_signal_handler()`, ожидает завершения цикла, закрывает все LLMClient
17. [ ] Retry-логика включает jitter, различие retryable/non-retryable, потолок задержки
18. [ ] Валидаторы унифицированы: `validator.py` — единственный источник правды
19. [ ] Prompt Injection Protection включает защиту от unicode-обфускации и zero-width chars
20. [ ] `check_uniqueness()` не возвращает фиктивный 0.95 при отсутствии базы
21. [ ] Telegram actions используют `secrets_manager.get_secret()` для токена
22. [ ] Telegram rate limiter работает через Redis (multi-instance)
23. [ ] BrowserManager ограничивает количество страниц и квоту скриншотов
24. [ ] `ssl=False` удалён из Reddit scanner
25. [ ] Audit log secrets_manager пишется в append-only файл
26. [ ] A/B-варианты созданы для content-agent и smm-agent
27. [ ] Temperature-калибровка создана для content-agent и smm-agent
28. [ ] Бренд вынесен в переменную окружения, не захардкожен в промптах
29. [ ] JSON Schema валидация применяется к конфигам агентов
30. [ ] Добавлены тесты для validator.py, site_actions.py, telegram_actions.py, file_utils.py
31. [ ] Все `datetime.utcnow()` заменены на `datetime.now(timezone.utc)`
32. [ ] `agent_type` извлекается через метод `AgentConfig`, не через `split("-")[0]`

---

## Метрики качества кода

| Метрика | Значение | Цель |
|---------|----------|------|
| Всего строк Python | ~19,100 | — |
| Строк тестов | ~4,230 (22%) | >40% |
| Количество тестов | 362 | >500 |
| Покрытие модулей тестами | 11 из 19 (58%) | 100% |
| Критических багов (P0) | 8 | 0 |
| Серьёзных проблем (P1) | 17 | 0 |
| God-objects | 1 (Orchestrator) | 0 |
| Модули без тестов | 8 | 0 |

---

*Отчёт сгенерирован автоматически на основе статического анализа кодовой базы. Для уточнения поведения в runtime рекомендуется провести нагрузочное тестирование и интеграционные тесты с реальными LLM API.*
