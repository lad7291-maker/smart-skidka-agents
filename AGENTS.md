# AGENTS.md — smart-skidka-agents

> Инструкции для AI-агентов, работающих с этим кодом.  
> Дополняет `README.md` (для людей) и `SKILL.md` (для внешнего использования).

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

## 1.4 Admitad Feed Configuration (RU&CIS)

**Важно:** С 2026-06-30 фид переключён с глобального AliExpress (.com) на **RU&CIS программу**:

| | Старый | Новый |
|--|--------|-------|
| **AdSpace ID** | 2939190 | **2940069** |
| **Feed ID** | 14107 | **18906** |
| **Offer** | Global | **25179 AliExpress RU&CIS** |
| **Домен** | aliexpress.com | **aliexpress.ru** |
| **Ссылка** | rzekl.com → s.click.aliexpress.com | **ali.click** → aliexpress.ru |
| **ERID** | Нет | **Да** (закон о рекламе РФ) |

**Преимущества RU&CIS:**
- Меньше редиректов (1 вместо 2-3)
- Родной домен `.ru` для российских пользователей = меньше капчи
- ERID метка для соответствия закону о рекламе
- Admitad RU&CIS программа специально для СНГ

**Конфигурация в `.env`:**
```bash
ADMITAD_XML_URL=http://export.admitad.com/en/webmaster/websites/2940069/products/export_adv_products/?user=vladislav_sotnikov56e18&code=4fkgb3nkie&feed_id=18906&format=xml&fcid=25179
```

**update_products.py** автоматически использует `feed_rucis.xml` если он существует, иначе скачивает через ADMITAD_XML_URL.

---