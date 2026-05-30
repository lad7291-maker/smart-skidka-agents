#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Действия агентов над файлами сайта smart-skidka.ru.
Все операции через file_utils (с бэкапом).
"""

import os
import re
import asyncio
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

import aiohttp

from .file_utils import read_site_html, write_site_html, read_products, write_products, safe_read, safe_write
from . import with_retry
from .action_registry import register_action

# ═══════════════════════════════════════════════════════════════════════════════
# P2-9: Квоты на создание файлов
# ═══════════════════════════════════════════════════════════════════════════════

# Максимум новых страниц категорий в сутки
DAILY_CATEGORY_PAGE_LIMIT: int = int(os.getenv("DAILY_CATEGORY_PAGE_LIMIT", "10"))

# Файл для отслеживания квот (в PROJECT_ROOT)
QUOTA_TRACKER_FILE: str = ".agent_quota_tracker.json"


def _get_quota_tracker_path() -> Path:
    """Возвращает путь к файлу отслеживания квот."""
    site_root = Path(os.getenv("PROJECT_ROOT", "/var/www/dealshub-miniapp"))
    return site_root / QUOTA_TRACKER_FILE


def _load_quota_tracker() -> Dict[str, Any]:
    """Загружает данные о квотах из файла."""
    path = _get_quota_tracker_path()
    if not path.exists():
        return {"created_pages": [], "updated_meta": [], "updated_products": []}
    try:
        import json
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"created_pages": [], "updated_meta": [], "updated_products": []}


def _save_quota_tracker(data: Dict[str, Any]) -> bool:
    """Сохраняет данные о квотах в файл."""
    path = _get_quota_tracker_path()
    try:
        import json
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to save quota tracker: {e}")
        return False


def _cleanup_old_entries(data: Dict[str, Any]) -> Dict[str, Any]:
    """Удаляет записи старше 24 часов."""
    now = datetime.now()
    cutoff = now - timedelta(hours=24)
    
    for key in data:
        if isinstance(data[key], list):
            data[key] = [
                entry for entry in data[key]
                if isinstance(entry, dict) and _parse_time(entry.get("timestamp", "")) > cutoff
            ]
    return data


def _parse_time(ts: str) -> datetime:
    """Парсит timestamp из строки."""
    try:
        return datetime.fromisoformat(ts)
    except Exception:
        return datetime.min


def check_category_page_quota() -> tuple[bool, str, Dict[str, Any]]:
    """
    Проверяет, не превышена ли дневная квота на создание страниц.
    
    Returns: (allowed, reason, tracker_data)
    """
    tracker = _load_quota_tracker()
    tracker = _cleanup_old_entries(tracker)
    
    created_today = len(tracker.get("created_pages", []))
    
    if created_today >= DAILY_CATEGORY_PAGE_LIMIT:
        return False, (
            f"Daily category page limit reached: {created_today}/"
            f"{DAILY_CATEGORY_PAGE_LIMIT}. Try again tomorrow."
        ), tracker
    
    return True, "", tracker


def record_category_page_creation(page_name: str) -> bool:
    """Записывает факт создания страницы категории."""
    tracker = _load_quota_tracker()
    tracker = _cleanup_old_entries(tracker)
    
    tracker.setdefault("created_pages", []).append({
        "page": page_name,
        "timestamp": datetime.now().isoformat(),
    })
    
    return _save_quota_tracker(tracker)


def get_quota_status() -> Dict[str, Any]:
    """Возвращает текущий статус квот для мониторинга."""
    tracker = _load_quota_tracker()
    tracker = _cleanup_old_entries(tracker)
    
    return {
        "daily_category_page_limit": DAILY_CATEGORY_PAGE_LIMIT,
        "created_pages_today": len(tracker.get("created_pages", [])),
        "updated_meta_today": len(tracker.get("updated_meta", [])),
        "updated_products_today": len(tracker.get("updated_products", [])),
        "remaining_category_pages": max(0, DAILY_CATEGORY_PAGE_LIMIT - len(tracker.get("created_pages", []))),
    }

# ─── SEO: обновление meta-тегов в index.html ─────────────────────────────

@with_retry(max_retries=3, delay=0.5, backoff=2.0, exceptions=(Exception,))
@register_action("update_meta_tags", agent_types=["seo"], description="Обновляет meta-теги сайта")
def update_meta_tags(title: str, description: str, keywords: str = "") -> bool:
    """
    Обновляет <title> и <meta name="description"> в index.html.
    Безопасно — бэкап создается автоматически.
    """
    html = read_site_html()
    if not html:
        return False

    # title
    html = re.sub(r'<title>.*?</title>', f'<title>{title}</title>', html, flags=re.DOTALL)

    # meta description
    pattern = r'<meta\s+name="description"\s+content=".*?">'
    replacement = f'<meta name="description" content="{description}">'
    if re.search(pattern, html):
        html = re.sub(pattern, replacement, html, flags=re.DOTALL)
    else:
        # Вставляем после <title>
        html = html.replace('</title>', f'</title>\n    {replacement}')

    # meta keywords (опционально)
    if keywords:
        kw_pattern = r'<meta\s+name="keywords"\s+content=".*?">'
        kw_replacement = f'<meta name="keywords" content="{keywords}">'
        if re.search(kw_pattern, html):
            html = re.sub(kw_pattern, kw_replacement, html, flags=re.DOTALL)
        else:
            html = html.replace('</title>', f'</title>\n    {kw_replacement}')

    return write_site_html(html)


# ─── Контент: создание категории ─────────────────────────────────────────

@with_retry(max_retries=3, delay=0.5, backoff=2.0, exceptions=(Exception,))
@register_action("create_category_page", agent_types=["content"], description="Создаёт страницу категории")
def create_category_page(category_name: str, items: list) -> bool:
    """
    Создаёт страницу категории (например, category/naushniki.html).
    items — список словарей с ключами title, price, image, link.
    
    P2-9: Проверяет дневную квоту перед созданием.
    """
    # Проверка квоты
    allowed, reason, _ = check_category_page_quota()
    if not allowed:
        print(f"[QUOTA_BLOCKED] create_category_page: {reason}")
        return False
    
    site_root = Path(os.getenv("PROJECT_ROOT", "/var/www/dealshub-miniapp"))
    slug = re.sub(r'[^a-z0-9\-]', '', category_name.lower().replace(' ', '-'))
    path = site_root / "category" / f"{slug}.html"
    path.parent.mkdir(parents=True, exist_ok=True)

    cards = ""
    for item in items:
        cards += f'''
        <div class="product-card">
            <img src="{item.get('image', '')}" alt="{item.get('title', '')}" loading="lazy">
            <h3>{item.get('title', '')}</h3>
            <p class="price">{item.get('price', '')}</p>
            <a href="{item.get('link', '#')}" class="btn" target="_blank">Купить со скидкой</a>
        </div>'''

    html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{category_name} — лучшие предложения | Smart Skidka</title>
    <meta name="description" content="Топовые скидки на {category_name}. Ежедневное обновление.">
    <link rel="stylesheet" href="../style.css">
</head>
<body>
    <header><h1>Smart Skidka</h1><nav><a href="../index.html">Главная</a></nav></header>
    <main>
        <h2>{category_name}</h2>
        <div class="grid">{cards}</div>
    </main>
    <footer>Smart Skidka © 2025</footer>
</body>
</html>'''

    # Записываем факт создания для квоты
    record_category_page_creation(f"category/{slug}.html")
    
    return safe_write(path, html)


# ─── Контент: обновление описания товара ─────────────────────────────────

@with_retry(max_retries=3, delay=0.5, backoff=2.0, exceptions=(Exception,))
@register_action("update_item_description", agent_types=["content"], description="Обновляет описание товара")
def update_item_description(item_id: str, new_description: str) -> bool:
    """
    Обновляет description товара в products.json.
    Поле 'description' разрешено для изменения (P1-9).
    """
    from .file_utils import validate_products_update
    allowed, reason = validate_products_update(item_id, "description", new_description)
    if not allowed:
        print(f"[BLOCKED] update_item_description: {reason}")
        return False

    data = read_products()
    if not data or "products" not in data:
        return False
    for p in data["products"]:
        if str(p.get("id", "")) == str(item_id):
            p["description"] = new_description
            return write_products(data)
    return False


# ─── SMM: добавление бейджа "Тренд" к товару ─────────────────────────────

@with_retry(max_retries=3, delay=0.5, backoff=2.0, exceptions=(Exception,))
@register_action("add_badge", agent_types=["performance"], description="Добавляет бейдж к товару")
def add_badge(item_id: str, badge_text: str = "🔥 Тренд") -> bool:
    """
    Добавляет бейдж к товару в products.json.
    Поле 'badge' разрешено для изменения (P1-9).
    """
    from .file_utils import validate_products_update
    allowed, reason = validate_products_update(item_id, "badge", badge_text)
    if not allowed:
        print(f"[BLOCKED] add_badge: {reason}")
        return False
    return _add_badge_to_index(item_id, badge_text)


# ─── Performance: приоритизация товаров ──────────────────────────────────

@with_retry(max_retries=3, delay=0.5, backoff=2.0, exceptions=(Exception,))
@register_action("prioritize_products", agent_types=["performance"], description="Устанавливает приоритет товаров")
def prioritize_products(product_ids: list) -> bool:
    """
    Перемещает указанные товары в начало products.json.
    Операция разрешена — изменяет только порядок, не поля товаров (P1-9).
    """
    data = read_products()
    if not data or "products" not in data:
        return False

    products = data["products"]
    prioritized = [p for p in products if str(p.get("id", "")) in map(str, product_ids)]
    rest = [p for p in products if str(p.get("id", "")) not in map(str, product_ids)]
    data["products"] = prioritized + rest
    return write_products(data)


# ─── Email: обновление поля товара ───────────────────────────────────────

@with_retry(max_retries=3, delay=0.5, backoff=2.0, exceptions=(Exception,))
@register_action("update_product_field", agent_types=["performance", "seo"], description="Обновляет поле товара")
def update_product_field(item_id: str, field: str, value) -> bool:
    """
    Обновляет разрешённое поле товара.
    Проверяет whitelist полей (P1-9).
    """
    from .file_utils import validate_products_update
    allowed, reason = validate_products_update(item_id, field, value)
    if not allowed:
        print(f"[BLOCKED] update_product_field: {reason}")
        return False

    data = read_products()
    if not data or "products" not in data:
        return False
    for p in data["products"]:
        if str(p.get("id", "")) == str(item_id):
            p[field] = value
            return write_products(data)
    return False


def _add_badge_to_index(item_id: str, badge_text: str) -> bool:
    data = read_products()
    if not data or "products" not in data:
        return False
    for p in data["products"]:
        # Ищем по внутреннему id (индекс товара)
        if str(p.get("id", "")) == str(item_id):
            p["badge"] = badge_text
            return write_products(data)
    return False


# ─── IMP-7: Авто-обновление sitemap.xml ──────────────────────────────────

def update_sitemap(pages: list) -> bool:
    """
    Обновляет sitemap.xml списком страниц.
    
    Args:
        pages: Список словарей с ключами: path, lastmod (опционально), changefreq (опционально)
    
    Returns:
        True если успешно
    """
    site_root = Path(os.getenv("PROJECT_ROOT", "/var/www/dealshub-miniapp"))
    sitemap_path = site_root / "sitemap.xml"
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    urls = []
    for page in pages:
        path = page.get("path", "")
        lastmod = page.get("lastmod", today)
        changefreq = page.get("changefreq", "weekly")
        priority = page.get("priority", "0.5")
        
        # Формируем полный URL
        url = f"https://smart-skidka.ru/{path.lstrip('/')}"
        
        urls.append(f"""  <url>
    <loc>{url}</loc>
    <lastmod>{lastmod}</lastmod>
    <changefreq>{changefreq}</changefreq>
    <priority>{priority}</priority>
  </url>""")
    
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{chr(10).join(urls)}
</urlset>"""
    
    return safe_write(sitemap_path, xml)


def add_to_sitemap(path: str, priority: str = "0.5", changefreq: str = "weekly") -> bool:
    """
    Добавляет одну страницу в существующий sitemap.xml.
    Если страница уже есть — обновляет lastmod.
    
    Args:
        path: Относительный путь (например, "guides/naushniki.html")
        priority: Приоритет (0.0-1.0)
        changefreq: Частота изменений
    """
    site_root = Path(os.getenv("PROJECT_ROOT", "/var/www/dealshub-miniapp"))
    sitemap_path = site_root / "sitemap.xml"
    
    today = datetime.now().strftime("%Y-%m-%d")
    url = f"https://smart-skidka.ru/{path.lstrip('/')}"
    
    # Читаем существующий sitemap
    existing = safe_read(sitemap_path)
    
    if existing and "<urlset" in existing:
        # Проверяем, есть ли уже такой URL
        if f"<loc>{url}</loc>" in existing:
            # Обновляем lastmod для существующего URL
            pattern = rf'(<loc>{re.escape(url)}</loc>\s+<lastmod>)[^<]+(</lastmod>)'
            updated = re.sub(pattern, rf'\g<1>{today}\g<2>', existing)
            if updated != existing:
                return safe_write(sitemap_path, updated)
            return True  # already up to date
        
        # Добавляем новый URL перед закрывающим </urlset>
        new_url = f"""  <url>
    <loc>{url}</loc>
    <lastmod>{today}</lastmod>
    <changefreq>{changefreq}</changefreq>
    <priority>{priority}</priority>
  </url>
</urlset>"""
        updated = existing.replace("</urlset>", new_url)
        return safe_write(sitemap_path, updated)
    else:
        # Создаём новый sitemap
        return update_sitemap([{
            "path": path,
            "priority": priority,
            "changefreq": changefreq,
        }])


# ─── IMP-8: Перелинковка ─────────────────────────────────────────────────

def add_cross_links(page_path: str, related_pages: list) -> bool:
    """
    Добавляет блок "Читайте также" с ссылками на связанные страницы.
    
    Args:
        page_path: Путь к странице, куда добавлять ссылки
        related_pages: Список словарей {title, path}
    
    Returns:
        True если успешно
    """
    site_root = Path(os.getenv("PROJECT_ROOT", "/var/www/dealshub-miniapp"))
    full_path = site_root / page_path.lstrip("/")
    
    html = safe_read(full_path)
    if not html:
        return False
    
    # Удаляем старый блок если есть
    html = re.sub(
        r'<div class="related-links">.*?</ul>\s*</div>\s*',
        '',
        html,
        flags=re.DOTALL,
    )
    
    # Если нет связанных страниц — просто сохраняем без блока
    valid_pages = [p for p in related_pages if p.get("title") and p.get("path")]
    if not valid_pages:
        return safe_write(full_path, html)
    
    # Формируем блок ссылок
    links_html = '<div class="related-links"><h3>📚 Читайте также</h3><ul>\n'
    for page in valid_pages:
        title = page.get("title", "")
        path = page.get("path", "")
        url = f"/{path.lstrip('/')}" 
        links_html += f'  <li><a href="{url}">{title}</a></li>\n'
    links_html += '</ul></div>'
    
    # Вставляем перед </body>
    if "</body>" in html:
        html = html.replace("</body>", f"{links_html}\n</body>")
    else:
        html += f"\n{links_html}"
    
    return safe_write(full_path, html)


# ─── IMP-9: Telegram постинг о новых страницах ───────────────────────────

async def post_new_page_to_telegram(page_path: str, title: str, description: str = "") -> bool:
    """
    Публикует анонс новой страницы в Telegram канал.
    
    Args:
        page_path: Путь к странице
        title: Заголовок страницы
        description: Краткое описание
    """
    from .telegram_actions import post_to_channel
    
    url = f"https://smart-skidka.ru/{page_path.lstrip('/')}"
    
    text = f"""📢 Новый гайд на сайте!

<b>{title}</b>

{description[:200]}{'...' if len(description) > 200 else ''}

👉 <a href='{url}'>Читать на сайте</a>"""
    
    return await post_to_channel(text)


# ─── CRIT-2: HTTP 200 check после создания страницы ──────────────────────

HTTP_CHECK_TIMEOUT = int(os.getenv("HTTP_CHECK_TIMEOUT", "10"))
HTTP_CHECK_BASE_URL = os.getenv("HTTP_CHECK_BASE_URL", "https://smart-skidka.ru")


@with_retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
async def check_page_http_status(
    page_path: str,
    expected_status: int = 200,
    timeout: int = HTTP_CHECK_TIMEOUT,
) -> dict:
    """
    Проверяет HTTP-статус страницы после публикации.
    
    Args:
        page_path: Относительный путь (например, "guides/naushniki.html")
        expected_status: Ожидаемый статус (по умолчанию 200)
        timeout: Таймаут запроса в секундах
    
    Returns:
        Словарь {"ok": bool, "status": int, "url": str, "error": str|None}
    """
    url = f"{HTTP_CHECK_BASE_URL}/{page_path.lstrip('/')}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout), allow_redirects=True) as resp:
                ok = resp.status == expected_status
                result = {
                    "ok": ok,
                    "status": resp.status,
                    "url": url,
                    "error": None if ok else f"Expected {expected_status}, got {resp.status}",
                }
                if not ok:
                    print(f"[HTTP CHECK FAIL] {url} -> {resp.status}")
                else:
                    print(f"[HTTP CHECK OK] {url} -> {resp.status}")
                return result
    except asyncio.TimeoutError:
        print(f"[HTTP CHECK TIMEOUT] {url}")
        return {"ok": False, "status": 0, "url": url, "error": "timeout"}
    except Exception as e:
        print(f"[HTTP CHECK ERROR] {url}: {e}")
        return {"ok": False, "status": 0, "url": url, "error": str(e)}


async def verify_and_track_page(
    page_path: str,
    agent_name: str,
    page_type: str = "",
    title: str = "",
    html_valid: Optional[bool] = None,
    track_func = None,
) -> dict:
    """
    Полный пайплайн проверки: HTTP 200 + трекинг в БД.
    
    Args:
        page_path: Путь к странице
        agent_name: Имя агента
        page_type: Тип страницы
        title: Заголовок
        html_valid: Результат валидации HTML
        track_func: Async функция для трекинга (MemoryStore.track_page)
    
    Returns:
        {"ok": bool, "http_check": dict, "tracked": bool}
    """
    # 1. HTTP check
    http_result = await check_page_http_status(page_path)
    
    # 2. Track in DB если передана функция
    tracked = False
    if track_func is not None:
        try:
            await track_func(
                path=page_path,
                agent_name=agent_name,
                page_type=page_type,
                title=title,
                html_valid=html_valid,
                http_status=http_result["status"],
            )
            tracked = True
        except Exception as e:
            print(f"[TRACK ERROR] {page_path}: {e}")
    
    return {
        "ok": http_result["ok"] and tracked,
        "http_check": http_result,
        "tracked": tracked,
    }


# ─── IMP-6: Content registry helpers (deduplication) ─────────────────────

def generate_slug(title: str) -> str:
    """Генерирует URL-friendly slug из заголовка."""
    slug = re.sub(r'[^\w\s-]', '', title.lower())
    slug = re.sub(r'[-\s]+', '-', slug)
    return slug.strip('-')


def is_duplicate_title(new_title: str, existing_titles: list, threshold: float = 0.7) -> bool:
    """
    Проверяет, является ли заголовок дубликатом (локальная проверка).
    
    Args:
        new_title: Новый заголовок
        existing_titles: Список существующих заголовков
        threshold: Порог схожести (0-1)
    
    Returns:
        True если дубликат найден
    """
    new_words = set(new_title.lower().split())
    if not new_words:
        return False
    
    for existing in existing_titles:
        existing_words = set(existing.lower().split())
        if not existing_words:
            continue
        intersection = new_words & existing_words
        union = new_words | existing_words
        similarity = len(intersection) / len(union) if union else 0
        if similarity >= threshold:
            return True
    
    return False


def suggest_unique_title(base_title: str, existing_titles: list, max_attempts: int = 10) -> str:
    """
    Предлагает уникальный заголовок, добавляя номер если нужно.
    
    Args:
        base_title: Базовый заголовок
        existing_titles: Список существующих заголовков
        max_attempts: Максимум попыток
    
    Returns:
        Уникальный заголовок
    """
    if not is_duplicate_title(base_title, existing_titles):
        return base_title
    
    for i in range(2, max_attempts + 2):
        candidate = f"{base_title} ({i})"
        if not is_duplicate_title(candidate, existing_titles):
            return candidate
    
    # Fallback: добавляем timestamp
    return f"{base_title} — {datetime.now().strftime('%Y-%m-%d')}"
