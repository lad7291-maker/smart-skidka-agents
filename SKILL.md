---
name: smart-skidka-agents
description: >
  Multi-agent система автономного маркетинга для агрегатора скидок smart-skidka.ru.
  Использовать при необходимости автоматизировать маркетинговые процессы: SEO-оптимизация,
  SMM-продвижение, performance-маркетинг, email-рассылки, аналитика и генерация контента.
  Система работает по расписанию через оркестратора, самовалидирует результаты и отправляет
  отчёты в Telegram. Подходит для автономного запуска маркетинговых кампаний,
  публикации контента, сбора метрик и оптимизации воронки конверсии.
---

# smart-skidka-agents: Автономная маркетинговая система

## Содержание

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Core Agents](#core-agents)
4. [Orchestrator](#orchestrator)
5. [Workflow](#workflow)
6. [Validation](#validation)
7. [Deployment](#deployment)
8. [Configuration](#configuration)
9. [Directory Structure](#directory-structure)
10. [Quick Start](#quick-start)
11. [Troubleshooting](#troubleshooting)

---

## Overview

`smart-skidka-agents` — это multi-agent система автономного маркетинга, разработанная для агрегатора скидок и промокодов **smart-skidka.ru**. Система состоит из **6 специализированных агентов**, **центрального оркестратора** и **механизма валидации**.

### Зачем нужна система

Агрегатор скидок требует постоянного привлечения трафика, генерации контента, SEO-оптимизации, SMM-активности и аналитики. Ручное выполнение этих задач требует большой команды. Данная система **автономно** выполняет весь цикл маркетинговых операций:

- **SEO** — оптимизация страниц под поисковые системы
- **SMM** — публикации в социальных сетях
- **Performance** — управление рекламными кампаниями
- **Email** — рассылки пользователям
- **Analytics** — сбор и анализ метрик
- **Content** — генерация текстов, описаний, постов

### Ключевые особенности

| Особенность | Описание |
|-------------|----------|
| Автономность | Агенты работают по расписанию без вмешательства человека |
| Самовалидация | Каждый результат проходит проверку перед применением |
| Retry-логика | Автоматические повторные попытки при сбоях |
| Telegram-отчёты | Ежедневные сводки о работе всех агентов |
| JSON-конфиги | Простая настройка каждого агента через файл |
| Docker-ready | Полный docker-compose для быстрого деплоя |

---

## Architecture

### Общая схема взаимодействия

```
                    ┌─────────────────────────────────────┐
                    │           ORCHESTRATOR              │
                    │         (orchestrator.py)           │
                    │                                     │
                    │  ┌─────────┐    ┌──────────────┐   │
                    │  │ Cron    │───>│ Dispatcher   │   │
                    │  │ Trigger │    │ (распредел.) │   │
                    │  └─────────┘    └──────┬───────┘   │
                    │                        │           │
                    │  ┌─────────┐    ┌──────▼───────┐   │
                    │  │ Retry   │<───│ Validator    │   │
                    │  │ Manager │    │ (validator)  │   │
                    │  └─────────┘    └──────────────┘   │
                    │                        │           │
                    │  ┌─────────┐    ┌──────▼───────┐   │
                    │  │ Report  │<───│ Telegram     │   │
                    │  │ Builder │    │ Reporter     │   │
                    │  └─────────┘    └──────────────┘   │
                    └─────────────────────────────────────┘
                                       │
          ┌──────────┬──────────┬──────┼──────┬──────────┬──────────┐
          ▼          ▼          ▼      ▼      ▼          ▼          ▼
   ┌──────────┐ ┌──────────┐ ┌──────────────┐ ┌──────────┐ ┌──────────┐
   │  SEO     │ │  SMM     │ │ Performance  │ │  Email   │ │ Content  │
   │  Agent   │ │  Agent   │ │   Agent      │ │  Agent   │ │  Agent   │
   └──────────┘ └──────────┘ └──────────────┘ └──────────┘ └──────────┘
          ▲            ▲               ▲               ▲            ▲
          │            │               │               │            │
          └────────────┴───────┬───────┴───────────────┴──────┬─────┘
                               │                                │
                               ▼                                ▼
                   ┌──────────────────────┐      ┌──────────────────────┐
                   │   Analytics Agent    │      │   Trend Research     │
                   │  (метрики сайта)     │      │   Agent (тренды      │
                   └──────────────────────┘      │    интернета)        │
                                                 └──────────────────────┘
```

### Потоки данных

1. **Управляющий поток**: Оркестратор -> Агенты (команды запуска)
2. **Поток результатов**: Агенты -> Валидатор (проверка качества)
3. **Поток метрик**: Агенты -> Analytics Agent -> Оркестратор
4. **Поток трендов**: Trend Agent -> SEO/SMM/Content/Perf Agents (рекомендации на основе внешних трендов)
5. **Поток отчётов**: Оркестратор -> Telegram Reporter

### Компоненты системы

| Компонент | Файл | Назначение |
|-----------|------|------------|
| Оркестратор | `scripts/orchestrator.py` | Центральный планировщик и диспетчер |
| Валидатор | `scripts/validator.py` | Проверка корректности результатов |
| Telegram Reporter | `scripts/telegram_reporter.py` | Отправка отчётов в Telegram |
| Content Generator | `scripts/content_generator.py` | Генерация текстового контента |
| Trend Research Agent | `references/agents/trend_agent.json` | Мониторинг трендов интернета и рекомендации |
| Конфиги агентов | `references/agents/*.json` | Индивидуальные настройки 7 агентов |
| Docker Compose | `assets/docker-compose.yml` | Инфраструктура для деплоя |

---

## Core Agents

### 1. SEO Agent

**Файл конфигурации:** `references/agents/seo_agent.json`

**Назначение:** Оптимизация страниц агрегатора под поисковые системы (Яндекс, Google). Генерация мета-тегов, заголовков, описаний, структурированных данных.

**Ключевые задачи:**
- Генерация `<title>` и `<meta name="description">` для страниц категорий
- Создание SEO-описаний для магазинов-партнёров
- Генерация `schema.org` разметки (AggregateOffer, Organization)
- Подбор семантического ядра (ключевые слова)
- Мониторинг позиций в поисковой выдаче

**Входные данные:** Список URL страниц, список магазинов, статистика по категориям
**Выходные данные:** Оптимизированные мета-теги, SEO-тексты, JSON-LD разметка

---

### 2. SMM Agent

**Файл конфигурации:** `references/agents/smm_agent.json`

**Назначение:** Публикация контента в социальных сетях: VK, Telegram-канал, ОК. Привлечение органического трафика.

**Ключевые задачи:**
- Составление постов о лучших скидках дня
- Публикация в VK-группе с картинками
- Отправка постов в Telegram-канал `@smart_skidka`
- Генерация хештегов и призывов к действию
- Планирование контент-календаря

**Входные данные:** Топ скидок, промокоды, новые магазины
**Выходные данные:** Опубликованные посты, ссылки на публикации

---

### 3. Performance Agent

**Файл конфигурации:** `references/agents/performance_agent.json`

**Назначение:** Управление рекламными кампаниями: Яндекс Директ, VK Реклама, таргет в Telegram. Оптимизация бюджета и ставок.

**Ключевые задачи:**
- Создание объявлений для топовых категорий
- Управление ставками на основе конверсии
- A/B тестирование креативов
- Ретаргетинг посетителей
- Остановка неэффективных кампаний

**Входные данные:** Бюджет, целевые CPA, список категорий
**Выходные данные:** Запущенные кампании, отчёты по расходу

---

### 4. Email Agent

**Файл конфигурации:** `references/agents/email_agent.json`

**Назначение:** Email-маркетинг: рассылка подписчикам о новых скидках, персонализированные подборки, триггерные письма.

**Ключевые задачи:**
- Ежедневная дайджест-рассылка топ-10 скидок
- Персонализированные подборки по интересам
- Триггерные письма (брошенная корзина, просмотренный товар)
- A/B тестирование тем писем
- Управление сегментами подписчиков

**Входные данные:** База подписчиков, история кликов, новые промокоды
**Выходные данные:** Отправленные письма, статистика открытий/кликов

---

### 5. Analytics Agent

**Файл конфигурации:** `references/agents/analytics_agent.json`

**Назначение:** Сбор, агрегация и анализ всех маркетинговых метрик. Формирование отчётов для принятия решений.

**Ключевые задачи:**
- Сбор метрик из Яндекс.Метрики / Google Analytics
- Расчёт ROI по каждому маркетинговому каналу
- Отслеживание конверсии по воронке
- Анализ LTV пользователей
- Построение когортного анализа

**Входные данные:** API-ключи метрик, данные из других агентов
**Выходные данные:** Сводные отчёты, рекомендации по оптимизации

---

### 6. Content Agent

**Файл конфигурации:** `references/agents/content_agent.json`

**Назначение:** Генерация текстового контента: описания магазинов, обзоры категорий, посты для блога, тексты рассылок.

**Ключевые задачи:**
- Генерация уникальных описаний для карточек магазинов
- Написание обзоров категорий ("Топ-10 кэшбэков", "Лучшие промокоды")
- Создание контента для email-писем
- Адаптация текстов под разные каналы (SEO, SMM, Email)
- Проверка на уникальность и читаемость

**Входные данные:** Данные о магазинах, скидках, промокодах
**Выходные данные:** Готовые тексты, адаптированные под канал

---

### 7. Trend Research Agent

**Файл конфигурации:** `references/agents/trend_agent.json`

**Назначение:** Мониторинг внешних трендов интернета — что люди ищут, обсуждают, покупают. Раннее обнаружение вирусных товаров и категорий. Даёт рекомендации другим агентам что продвигать прямо сейчас.

**Ключевые задачи:**
- Мониторинг поисковых трендов (Google Trends, Яндекс.Вордстат)
- Анализ трендов соцсетей (Telegram, VK, TikTok)
- Отслеживание бестселлеров на маркетплейсах (Wildberries, Ozon)
- Мониторинг новостей и анонсов продуктов
- Сканирование форумов (Пикабу, Reddit-аналоги)
- Сезонный анализ (праздники, распродажи, погода)
- Конкурентный анализ (что продвигают другие агрегаторы)

**Формат рекомендаций:**
```json
{
  "trend_type": "product|category|event|viral|seasonal",
  "confidence": 0.85,
  "title": "Тренд: переносные кондиционеры из Китая",
  "metrics": {"search_growth": "+240%", "sales_growth": "+340%"},
  "recommended_actions": [
    {"agent": "seo_agent", "action": "Создать SEO-страницу...", "priority": "high"},
    {"agent": "smm_agent", "action": "Пост в Telegram...", "priority": "high"},
    {"agent": "content_agent", "action": "Сравнение товаров...", "priority": "medium"}
  ],
  "peak_date": "2026-06-15",
  "status": "rising"
}
```

**Входные данные:** API трендовых сервисов, парсинг соцсетей и маркетплейсов
**Выходные данные:** JSON с трендами и рекомендациями для других агентов

---

## Orchestrator

### Назначение

`scripts/orchestrator.py` — центральный компонент системы. Управляет жизненным циклом всех агентов: планирование, запуск, валидация, retry, формирование отчётов.

### Основные функции

#### 1. Распределение задач (Dispatcher)

Оркестратор читает расписание из конфигурации и запускает агентов в нужное время:

```python
# Пример расписания (cron-подобное)
SCHEDULE = {
    "seo_agent":         "0 3 * * *",    # 03:00 ежедневно
    "smm_agent":         "0 9,15,21 * * *", # 9:00, 15:00, 21:00
    "performance_agent": "0 */4 * * *",  # каждые 4 часа
    "email_agent":       "0 8 * * 1-5",  # 8:00 по будням
    "analytics_agent":   "0 6 * * *",    # 06:00 ежедневно
    "content_agent":     "0 4 * * *",    # 04:00 ежедневно
}
```

**Приоритеты агентов:**
| Приоритет | Агент | Обоснование |
|-----------|-------|-------------|
| P0 (критичный) | analytics_agent | Метрики нужны для принятия решений |
| P1 (высокий) | seo_agent, content_agent | Контент формируется до публикации |
| P2 (средний) | smm_agent, email_agent | Зависит от контента |
| P3 (по расписанию) | performance_agent | Требует актуальных метрик |

#### 2. Валидация результатов

Каждый агент после выполнения возвращает результат, который проходит проверку:

```
Агент -> Выполнение -> Результат -> Validator -> [OK / FAIL]
                                          │
                                    OK -> Сохранение
                                    FAIL -> Retry (max 3)
                                          -> Если FAIL после 3 попыток -> Уведомление админу
```

См. подробнее в разделе [Validation](#validation).

#### 3. Retry-логика

```python
MAX_RETRIES = 3
RETRY_DELAY = [60, 300, 900]  # секунды: 1 мин, 5 мин, 15 мин

# Экспоненциальная задержка с джиттером
def get_retry_delay(attempt: int) -> int:
    base = RETRY_DELAY[min(attempt, len(RETRY_DELAY) - 1)]
    jitter = random.randint(0, base // 2)
    return base + jitter
```

Условия retry:
- Ошибка API (timeout, 5xx)
- Невалидный результат (не прошёл проверку)
- Недоступность внешнего сервиса

Retry **НЕ выполняется** при:
- Ошибке аутентификации (неверный API-ключ)
- Ошибке валидации входных данных
- Исчерпании лимита запросов (rate limit)

#### 4. Telegram-отчёты

Оркестратор формирует ежедневный отчёт и отправляет через `telegram_reporter.py`:

**Формат отчёта:**
```
📊 Smart-Skidka Agents — Отчёт за 15.01.2025

✅ SEO Agent        — 12 страниц оптимизировано
✅ SMM Agent        — 3 поста опубликовано (VK, TG, OK)
✅ Performance      — 2 кампании обновлены (CTR +12%)
✅ Email Agent      — 15,420 писем отправлено (OR 22%)
✅ Analytics        — Метрики собраны
✅ Content Agent    — 8 текстов сгенерировано

⚠️ Предупреждения:
   • Performance Agent: CPA в категории "Электроника" вырос на 18%

📈 Ключевые метрики:
   • Посетители: 45,230 (+5.2%)
   • Конверсия: 3.8% (+0.3%)
   • Доход: ₽847,500 (+8.1%)
```

---

## Workflow

### Полный цикл работы агентов

```
┌─────────────────────────────────────────────────────────────────┐
│                    DAILY WORKFLOW CYCLE                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  03:00  ┌──────────────┐                                        │
│         │  SEO Agent   │ ──> Генерация мета-тегов               │
│         └──────┬───────┘     SEO-текстов                        │
│                │          schema.org разметки                    │
│                ▼                                                 │
│  04:00  ┌──────────────┐                                        │
│         │ Content Agent│ ──> Генерация контента на основе        │
│         └──────┬───────┘     SEO-данных                         │
│                │          Адаптация под каналы                   │
│                ▼                                                 │
│  05:00  ┌──────────────┐                                        │
│         │ Trend Agent  │ ──> Сканирование трендов интернета      │
│         └──────┬───────┘     Раннее обнаружение вирусных товаров │
│                │          Рекомендации другим агентам            │
│                ▼                                                 │
│  06:00  ┌──────────────┐                                        │
│         │Analytics Agent│ ──> Сбор метрик вчерашнего дня         │
│         └──────┬───────┘     Расчёт KPI                          │
│                │                                                 │
│                ▼                                                 │
│  08:00  ┌──────────────┐     (пн-пт)                            │
│         │  Email Agent │ ──> Дайджест-рассылка                  │
│         └──────┬───────┘     Персональные подборки              │
│                │                                                 │
│                ▼                                                 │
│  09:00  ┌──────────────┐                                        │
│         │   SMM Agent  │ ──> Пост "Скидки утра" в VK, TG        │
│         └──────┬───────┘                                        │
│                │                                                 │
│  15:00  ┌──────────────┐                                        │
│         │   SMM Agent  │ ──> Пост "Акции дня" в VK, TG          │
│         └──────┬───────┘                                        │
│                │                                                 │
│  21:00  ┌──────────────┐                                        │
│         │   SMM Agent  │ ──> Пост "Последний шанс" в VK, TG     │
│         └──────┬───────┘                                        │
│                │                                                 │
│  */4    ┌──────────────┐                                        │
│         │  Performance │ ──> Обновление ставок                  │
│         │    Agent     │     Запуск/остановка кампаний          │
│         └──────┬───────┘     A/B тестирование                  │
│                │                                                 │
│                ▼                                                 │
│         ┌──────────────┐                                        │
│         │  Validator   │ ──> Проверка всех результатов          │
│         └──────┬───────┘                                        │
│                │                                                 │
│         OK  ──> Сохранение                                     │
│         FAIL ──> Retry / Уведомление                            │
│                                                                 │
│  23:30  ┌──────────────┐                                        │
│         │   Telegram   │ ──> Итоговый отчёт за день             │
│         │   Reporter   │                                        │
│         └──────────────┘                                        │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### Взаимосвязи между агентами

```
                    ┌─> SEO Agent ────┐
                    │                  ├──> Content Agent ───┬──> SMM Agent
Trend Agent ────────┼─> SMM Agent ────┘                      │
(рекомендации)      │                                        ├──> Email Agent
                    ├─> Perf Agent <─────────────────────────┘
                    │
Analytics Agent ────┘
```

**Цепочки зависимостей:**

1. **SEO -> Content:** SEO Agent генерирует ключевые слова и структуру, Content Agent пишет тексты на их основе
2. **Content -> SMM:** SMM Agent использует тексты от Content Agent для постов
3. **Content -> Email:** Email Agent адаптирует контент для рассылок
4. **Analytics -> Performance:** Performance Agent использует метрики для оптимизации ставок
5. **Analytics -> ALL:** Все агенты получают метрики для корректировки стратегии

### Состояния агента

```
        ┌──────────┐
        │  IDLE    │<────────────────────────┐
        └────┬─────┘                         │
             │ (по расписанию)               │
             ▼                               │
        ┌──────────┐    FAIL + retry < 3    │
   ┌───>│ RUNNING  │────────────────────────┤
   │    └────┬─────┘                        │
   │         │                              │
   │    ┌────┴────┐                        │
   │    ▼         ▼                         │
   │ ┌──────┐  ┌──────┐                     │
   └─│SUCCESS│  │FAILED│─────────────────────┘
     └──┬───┘  └──┬───┘  FAIL + retry >= 3
        │         │
        ▼         ▼
   ┌────────┐  ┌────────┐
   │VALIDATE│  │ALERT   │
   │ RESULT │  │ ADMIN  │
   └────────┘  └────────┘
```

---

## Validation

### Уровни валидации

Система использует **трёхуровневую** проверку результатов:

#### Уровень 1: Синтаксическая проверка (validator.py)

```python
def validate_syntax(result: dict, agent_type: str) -> ValidationResult:
    """Проверяет структуру и формат результата"""
    checks = {
        "has_required_fields": check_required_fields(result, agent_type),
        "valid_data_types": check_data_types(result, agent_type),
        "no_empty_values": check_no_empty_values(result),
        "valid_utf8": check_encoding(result),
    }
    return ValidationResult(passed=all(checks.values()), details=checks)
```

| Агент | Обязательные поля | Типы данных |
|-------|-------------------|-------------|
| SEO Agent | `meta_title`, `meta_description`, `schema_json` | string, string, object |
| SMM Agent | `platform`, `content`, `published_url` | string, string, url |
| Performance Agent | `campaign_id`, `status`, `spent_rub` | string, enum, number |
| Email Agent | `recipients_count`, `subject`, `sent_at` | integer, string, datetime |
| Analytics Agent | `metrics`, `period`, `kpis` | object, string, object |
| Content Agent | `text`, `word_count`, `channel` | string, integer, string |
| Trend Agent | `trend_type`, `confidence`, `recommended_actions` | string, float, array |

#### Уровень 2: Семантическая проверка

```python
def validate_semantic(result: dict, agent_type: str) -> ValidationResult:
    """Проверяет логическую корректность содержимого"""
    checks = {
        "reasonable_length": check_length_bounds(result, agent_type),
        "no_prohibited_words": check_blacklist(result),
        "relevant_content": check_relevance(result, agent_type),
        "valid_urls": check_urls_reachable(result),
    }
    return ValidationResult(passed=all(checks.values()), details=checks)
```

**Правила семантической проверки (validation_rules.md):**

- **SEO Agent:** Длина title 30-70 символов, description 120-160 символов
- **SMM Agent:** Пост 100-2000 символов, наличие хештегов, кликабельные ссылки
- **Performance Agent:** Ставка > 0, бюджет в пределах лимита
- **Email Agent:** Тема 10-100 символов, валидные email адреса
- **Content Agent:** Уникальность > 80%, читаемость (FLESCH) > 50
- **Trend Agent:** Уверенность (confidence) >= 0.6, минимум 2 источника данных, не старше 48 часов

#### Уровень 3: Бизнес-правила

```python
def validate_business_rules(result: dict, agent_type: str) -> ValidationResult:
    """Проверяет соответствие бизнес-ограничениям"""
    checks = {
        "budget_not_exceeded": check_budget(result),
        "rate_limits_ok": check_rate_limits(result),
        "brand_compliance": check_brand_voice(result),
        "legal_compliance": check_legal_requirements(result),
    }
    return ValidationResult(passed=all(checks.values()), details=checks)
```

### Правила обработки ошибок

| Сценарий | Действие |
|----------|----------|
| Ошибка на Уровне 1 | Retry с теми же параметрами |
| Ошибка на Уровне 2 | Retry с корректировкой промпта |
| Ошибка на Уровне 3 | Отправка на ручную модерацию + уведомление |
| 3 неудачных retry | Аларм в Telegram, агент переходит в FAILED |

### Журнал валидации

Все проверки записываются в лог:
```
logs/validation/
├── 2025-01-15/
│   ├── seo_agent_030000.json
│   ├── smm_agent_090000.json
│   ├── performance_agent_080000.json
│   └── trend_agent_050000.json
```

---

## Deployment

### Требования

| Компонент | Минимум | Рекомендуется |
|-----------|---------|---------------|
| CPU | 2 ядра | 4 ядра |
| RAM | 4 GB | 8 GB |
| Диск | 20 GB SSD | 50 GB SSD |
| Сеть | 10 Mbps | 100 Mbps |

### Переменные окружения

```bash
# .env файл
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id
YANDEX_DIRECT_TOKEN=your_yandex_token
VK_API_TOKEN=your_vk_token
EMAIL_SMTP_HOST=smtp.example.com
EMAIL_SMTP_USER=user@example.com
EMAIL_SMTP_PASS=your_password
METRIKA_COUNTER_ID=12345678
METRIKA_TOKEN=your_metrika_token
SCHEDULE_TIMEZONE=Europe/Moscow
```

### Способ 1: Docker Compose (рекомендуется)

```bash
# 1. Клонировать репозиторий
git clone https://github.com/smart-skidka/agents.git
cd agents

# 2. Создать .env файл
cp .env.example .env
# Отредактировать .env

# 3. Запустить
docker-compose -f assets/docker-compose.yml up -d

# 4. Проверить статус
docker-compose logs -f orchestrator
```

**docker-compose.yml:**
```yaml
version: "3.8"

services:
  orchestrator:
    build: .
    container_name: sk_agents_orchestrator
    restart: unless-stopped
    env_file: ../.env
    volumes:
      - ./references:/app/references
      - ./logs:/app/logs
    depends_on:
      - redis
    command: python scripts/orchestrator.py

  redis:
    image: redis:7-alpine
    container_name: sk_agents_redis
    restart: unless-stopped
    volumes:
      - redis_data:/data

  scheduler:
    build: .
    container_name: sk_agents_scheduler
    restart: unless-stopped
    env_file: ../.env
    depends_on:
      - redis
    command: python scripts/scheduler.py

volumes:
  redis_data:
```

### Способ 2: Ручной запуск

```bash
# 1. Установить зависимости
pip install -r requirements.txt

# 2. Настроить конфиги агентов
# (см. раздел Configuration)

# 3. Запустить оркестратор
python scripts/orchestrator.py --daemon

# 4. Запустить отдельного агента (для теста)
python scripts/orchestrator.py --agent seo_agent --once
```

### Способ 3: Systemd сервис

```ini
# /etc/systemd/system/smart-skidka-agents.service
[Unit]
Description=Smart Skidka Marketing Agents
After=network.target

[Service]
Type=simple
User=agents
WorkingDirectory=/opt/smart-skidka-agents
ExecStart=/opt/smart-skidka-agents/venv/bin/python scripts/orchestrator.py
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable smart-skidka-agents
sudo systemctl start smart-skidka-agents
sudo systemctl status smart-skidka-agents
```

### Проверка после деплоя

```bash
# Статус всех сервисов
docker-compose ps

# Логи оркестратора
docker-compose logs -f orchestrator

# Проверка подключения к Telegram
python scripts/telegram_reporter.py --test

# Ручной запуск валидации
python scripts/validator.py --test-config
```

---

## Configuration

### Структура JSON-конфига агента

Каждый агент настраивается через JSON-файл в `references/agents/`:

```json
{
  "agent": {
    "name": "seo_agent",
    "version": "1.0.0",
    "enabled": true,
    "priority": 1
  },
  "schedule": {
    "cron": "0 3 * * *",
    "timezone": "Europe/Moscow",
    "retry_policy": {
      "max_retries": 3,
      "delays": [60, 300, 900],
      "on_failure": "alert_admin"
    }
  },
  "input": {
    "source": "api",
    "endpoint": "https://api.smart-skidka.ru/v1/stores",
    "auth": "bearer_token",
    "pagination": "cursor"
  },
  "output": {
    "destination": "api",
    "endpoint": "https://api.smart-skidka.ru/v1/seo/meta",
    "format": "json"
  },
  "validation": {
    "rules": [
      {"field": "meta_title", "min_length": 30, "max_length": 70},
      {"field": "meta_description", "min_length": 120, "max_length": 160},
      {"field": "schema_json", "required": true, "type": "object"}
    ]
  },
  "limits": {
    "max_pages_per_run": 50,
    "max_api_calls_per_minute": 60,
    "timeout_seconds": 120
  }
}
```

### Шаблоны конфигов

#### SEO Agent — `references/agents/seo_agent.json`

```json
{
  "agent": {
    "name": "seo_agent",
    "enabled": true,
    "priority": 1,
    "description": "Генерация SEO-мета и структурированных данных"
  },
  "schedule": {
    "cron": "0 3 * * *",
    "retry_policy": {"max_retries": 3, "delays": [60, 300, 900]}
  },
  "seo_settings": {
    "title_length": {"min": 30, "max": 70},
    "description_length": {"min": 120, "max": 160},
    "keywords_per_page": 5,
    "schema_types": ["AggregateOffer", "Organization", "BreadcrumbList"],
    "target_search_engines": ["yandex", "google"],
    "language": "ru"
  },
  "input": {
    "stores_endpoint": "https://api.smart-skidka.ru/v1/stores",
    "categories_endpoint": "https://api.smart-skidka.ru/v1/categories"
  },
  "output": {
    "meta_endpoint": "https://api.smart-skidka.ru/v1/seo/update"
  },
  "limits": {
    "max_pages_per_run": 50,
    "max_keywords_per_page": 10
  }
}
```

#### SMM Agent — `references/agents/smm_agent.json`

```json
{
  "agent": {
    "name": "smm_agent",
    "enabled": true,
    "priority": 2,
    "description": "Публикация в VK, Telegram, ОК"
  },
  "schedule": {
    "cron": "0 9,15,21 * * *",
    "retry_policy": {"max_retries": 2, "delays": [120, 600]}
  },
  "platforms": {
    "vk": {
      "group_id": "123456789",
      "post_format": "text+image",
      "hashtags_count": 5
    },
    "telegram": {
      "channel": "@smart_skidka",
      "use_html": true,
      "include_button": true
    },
    "odnoklassniki": {
      "group_id": "987654321",
      "enabled": false
    }
  },
  "content": {
    "post_length": {"min": 100, "max": 2000},
    "include_top_discounts": 5,
    "cta_template": "Получить скидку → {url}",
    "hashtag_template": "#{category} #{store} #скидки #промокоды"
  }
}
```

#### Performance Agent — `references/agents/performance_agent.json`

```json
{
  "agent": {
    "name": "performance_agent",
    "enabled": true,
    "priority": 3,
    "description": "Управление рекламными кампаниями"
  },
  "schedule": {
    "cron": "0 */4 * * *",
    "retry_policy": {"max_retries": 2, "delays": [300, 900]}
  },
  "budget": {
    "daily_limit_rub": 5000,
    "campaign_min_budget_rub": 500,
    "auto_redistribute": true
  },
  "platforms": {
    "yandex_direct": {
      "api_url": "https://api.direct.yandex.com/json/v5/",
      "campaigns": ["category_search", "brand_traffic", "retargeting"]
    },
    "vk_ads": {
      "account_id": "12345678",
      "campaign_types": ["feed", "stories"]
    }
  },
  "optimization": {
    "target_cpa_rub": 150,
    "min_ctr_percent": 1.5,
    "auto_pause_underperforming": true,
    "ctr_threshold_pause": 0.5
  }
}
```

#### Email Agent — `references/agents/email_agent.json`

```json
{
  "agent": {
    "name": "email_agent",
    "enabled": true,
    "priority": 2,
    "description": "Email-рассылки и триггерные письма"
  },
  "schedule": {
    "cron": "0 8 * * 1-5",
    "retry_policy": {"max_retries": 2, "delays": [300, 600]}
  },
  "smtp": {
    "host": "smtp.example.com",
    "port": 587,
    "use_tls": true,
    "from_name": "Smart-Skidka",
    "from_email": "noreply@smart-skidka.ru"
  },
  "campaigns": {
    "daily_digest": {
      "enabled": true,
      "subject_template": "Топ скидок на {date}: экономьте до {max_discount}%",
      "max_items": 10,
      "segments": ["all_active"]
    },
    "personalized": {
      "enabled": true,
      "subject_template": "{first_name}, персональные скидки для вас",
      "min_interactions": 3,
      "categories_from_history": 3
    },
    "trigger_abandoned": {
      "enabled": true,
      "delay_hours": 24,
      "subject": "Вы забыли что-то важное!"
    }
  }
}
```

#### Analytics Agent — `references/agents/analytics_agent.json`

```json
{
  "agent": {
    "name": "analytics_agent",
    "enabled": true,
    "priority": 0,
    "description": "Сбор и анализ маркетинговых метрик"
  },
  "schedule": {
    "cron": "0 6 * * *",
    "retry_policy": {"max_retries": 3, "delays": [60, 300, 600]}
  },
  "sources": {
    "yandex_metrika": {
      "counter_id": "12345678",
      "metrics": ["ym:s:visits", "ym:s:users", "ym:s:bounceRate", "ym:s:avgSessionDuration"]
    },
    "google_analytics": {
      "property_id": "GA4_PROPERTY_ID",
      "metrics": ["sessions", "activeUsers", "conversions"]
    },
    "internal_api": {
      "endpoint": "https://api.smart-skidka.ru/v1/stats"
    }
  },
  "kpis": {
    "daily_visitors_target": 50000,
    "conversion_rate_target": 3.5,
    "avg_check_rub_target": 2500,
    "roi_target": 200
  },
  "report": {
    "include_cohort_analysis": true,
    "include_attribution": true,
    "comparison_period_days": 7
  }
}
```

#### Content Agent — `references/agents/content_agent.json`

```json
{
  "agent": {
    "name": "content_agent",
    "enabled": true,
    "priority": 1,
    "description": "Генерация текстового контента"
  },
  "schedule": {
    "cron": "0 4 * * *",
    "retry_policy": {"max_retries": 3, "delays": [60, 300, 900]}
  },
  "generation": {
    "language": "ru",
    "tone": "friendly_professional",
    "min_uniqueness_percent": 80,
    "min_flesch_score": 50,
    "max_generation_time_sec": 300
  },
  "content_types": {
    "store_description": {
      "length": {"min": 200, "max": 500},
      "template": "{store_name} — {category}. {description}. Актуальные промокоды и скидки на {current_month}."
    },
    "category_review": {
      "length": {"min": 500, "max": 1500},
      "include_top_stores": 10
    },
    "blog_post": {
      "length": {"min": 800, "max": 3000},
      "include_images": true,
      "include_cta": true
    }
  },
  "quality_checks": {
    "spellcheck": true,
    "profanity_filter": true,
    "brand_voice_check": true,
    "readability_check": true
  }
}
```

### Переопределение конфигов через env

Любое значение из JSON-конфига можно переопределить через переменные окружения:

```bash
# Формат: AGENT_NAME__SECTION__KEY__SUBKEY
export SEO_AGENT__SEO_SETTINGS__TITLE_LENGTH__MAX=80
export PERFORMANCE_AGENT__BUDGET__DAILY_LIMIT_RUB=10000
export SMM_AGENT__PLATFORMS__VK__ENABLED=false
```

### Горячая перезагрузка конфигов

```bash
# Отправить сигнал для перезагрузки конфигов
kill -HUP $(cat /var/run/smart-skidka-agents.pid)

# Или через API оркестратора
curl -X POST http://localhost:8080/api/v1/reload-configs
```

---

## Directory Structure

```
smart-skidka-agents/
├── SKILL.md                          # Этот файл — главная документация
├── README.md                         # Краткое руководство для разработчиков
├── requirements.txt                  # Python-зависимости
├── .env.example                      # Шаблон переменных окружения
├── .env                              # Переменные окружения (не в git)
│
├── scripts/                          # Исполняемые скрипты
│   ├── orchestrator.py               # Центральный оркестратор
│   ├── validator.py                  # Валидатор результатов
│   ├── telegram_reporter.py          # Отправка отчётов в Telegram
│   ├── content_generator.py          # Генератор контента (общий)
│   └── utils/                        # Вспомогательные модули
│       ├── api_client.py             # HTTP-клиент для API
│       ├── logger.py                 # Настройка логирования
│       └── exceptions.py             # Кастомные исключения
│
├── references/                       # Конфигурации и справочники
│   ├── agents/                       # Конфиги агентов (JSON)
│   │   ├── seo_agent.json
│   │   ├── smm_agent.json
│   │   ├── performance_agent.json
│   │   ├── email_agent.json
│   │   ├── analytics_agent.json
│   │   ├── content_agent.json
│   │   └── trend_agent.json
│   ├── orchestrator_workflow.md      # Подробное описание workflow
│   ├── validation_rules.md           # Правила валидации (подробно)
│   └── prompts/                      # Промпты для LLM
│       ├── seo_prompts.md
│       ├── smm_prompts.md
│       └── content_prompts.md
│
├── assets/                           # Инфраструктурные файлы
│   ├── docker-compose.yml            # Docker Compose конфигурация
│   ├── Dockerfile                    # Образ приложения
│   └── nginx.conf                    # Конфиг Nginx (если нужен)
│
├── logs/                             # Логи (создаётся автоматически)
│   ├── 2025-01-15/
│   │   ├── orchestrator.log
│   │   ├── seo_agent.log
│   │   └── validation.log
│   └── archive/                      # Архивные логи
│
└── tests/                            # Тесты
    ├── test_validator.py
    ├── test_orchestrator.py
    └── fixtures/
```

---

## Quick Start

### 1. Клонирование и настройка

```bash
git clone https://github.com/smart-skidka/agents.git
cd smart-skidka-agents
cp .env.example .env
# Редактировать .env — добавить все API-ключи
```

### 2. Настройка конфигов

```bash
# Все агенты включены по умолчанию
# Отключить ненужного:
# nano references/agents/performance_agent.json
# "enabled": false
```

### 3. Запуск

```bash
# Docker (рекомендуется)
docker-compose -f assets/docker-compose.yml up -d

# Или напрямую
pip install -r requirements.txt
python scripts/orchestrator.py
```

### 4. Проверка

```bash
# Логи
tail -f logs/$(date +%Y-%m-%d)/orchestrator.log

# Тест Telegram
python scripts/telegram_reporter.py --test

# Ручной запуск агента
python scripts/orchestrator.py --agent seo_agent --once --verbose
```

### 5. Мониторинг

- Логи: `logs/YYYY-MM-DD/`
- Telegram: ежедневные отчёты в указанный чат
- API статуса: `http://localhost:8080/api/v1/status`
- Метрики: `http://localhost:8080/metrics` (Prometheus-формат)

---

## Troubleshooting

### Частые проблемы

| Проблема | Причина | Решение |
|----------|---------|---------|
| Агент не запускается | `"enabled": false` в конфиге | Проверить JSON-конфиг |
| Ошибка API | Неверный токен | Проверить `.env`, обновить токен |
| Retry исчерпан | Внешний сервис недоступен | Проверить статус сервиса, увеличить `delays` |
| Нет отчётов в Telegram | Неверный `CHAT_ID` | Проверить через `@getidsbot` |
| Валидация не проходит | Некорректный результат агента | Проверить логи `logs/*/validation.log` |
| Docker не стартует | Занят порт | `docker-compose down && docker-compose up -d` |

### Отладка

```bash
# Запуск с подробным логированием
python scripts/orchestrator.py --log-level DEBUG

# Запуск одного агента в режиме отладки
python scripts/orchestrator.py --agent content_agent --once --verbose --dry-run

# Проверка конфига без запуска
python scripts/validator.py --check-config references/agents/seo_agent.json

# Просмотр очереди задач
python scripts/orchestrator.py --show-queue
```

### Контакты для поддержки

- Telegram: @smart_skidka_support
- Email: dev@smart-skidka.ru
- Внутренний чат: #agents-alerts

---

*Документация актуальна для версии 1.0.0. Последнее обновление: январь 2025.*
