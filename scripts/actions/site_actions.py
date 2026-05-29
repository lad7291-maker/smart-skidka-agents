#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Действия агентов над файлами сайта smart-skidka.ru.
Все операции через file_utils (с бэкапом).
"""

import re
from pathlib import Path
from .file_utils import read_site_html, write_site_html, read_products, write_products, safe_read, safe_write

# ─── SEO: обновление meta-тегов в index.html ─────────────────────────────

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
        # вставляем после <head>
        html = html.replace('<head>', f'<head>\n    {replacement}')

    # meta keywords (опционально)
    if keywords:
        kw_pattern = r'<meta\s+name="keywords"\s+content=".*?">'
        kw_replacement = f'<meta name="keywords" content="{keywords}">'
        if re.search(kw_pattern, html):
            html = re.sub(kw_pattern, kw_replacement, html, flags=re.DOTALL)
        else:
            html = html.replace('<head>', f'<head>\n    {kw_replacement}')

    return write_site_html(html)


# ─── Performance: обновление приоритетов товаров ──────────────────────────

def prioritize_products(product_ids: list) -> bool:
    """
    Поднимает указанные товары в начало products.json (отображаются первыми).
    product_ids — список ID товаров в порядке приоритета.
    """
    data = read_products()
    if not data or "products" not in data:
        return False

    products = data["products"]
    id_to_prod = {str(p.get("itemId", p.get("id", i))): p for i, p in enumerate(products)}

    new_order = []
    # Сначала указанные
    for pid in product_ids:
        if pid in id_to_prod:
            new_order.append(id_to_prod.pop(pid))
    # Потом остальные
    new_order.extend(id_to_prod.values())

    data["products"] = new_order
    return write_products(data)


def update_product_field(product_id: str, field: str, value) -> bool:
    """
    Обновляет одно поле у товара (например, featured=True, badge="ХИТ").
    """
    data = read_products()
    if not data or "products" not in data:
        return False

    for p in data["products"]:
        if str(p.get("itemId", p.get("id"))) == str(product_id):
            p[field] = value
            return write_products(data)
    return False


# ─── Content: создание страницы категории ─────────────────────────────────

def create_category_page(category: str, content_html: str) -> bool:
    """
    Создаёт/обновляет страницу категории, например category/electronics.html.
    """
    cat_dir = Path("/var/www/dealshub-miniapp/category")
    cat_dir.mkdir(parents=True, exist_ok=True)

    template = read_site_html()
    if not template:
        # минимальный fallback
        template = f"""<!DOCTYPE html>
<html lang="ru">
<head><meta charset="UTF-8"><title>{category}</title></head>
<body>{{CONTENT}}</body>
</html>"""

    # Вставляем контент в body
    page = template.replace('</body>', f'<main class="category-page">\n{content_html}\n</main>\n</body>')
    page = re.sub(r'<title>.*?</title>', f'<title>{category} — Скидки на AliExpress | SmartSkidka</title>', page)

    target = cat_dir / f"{category}.html"
    return safe_write(target, page)


# ─── Content: обновление описания товара на его странице ──────────────────

def update_item_description(item_id: str, description: str) -> bool:
    """
    Обновляет описание на странице товара item/{item_id}.html.
    """
    item_file = Path(f"/var/www/dealshub-miniapp/item/{item_id}.html")
    if not item_file.exists():
        return False

    html = safe_read(item_file)
    desc_html = f'<div class="item-description">{description}</div>'

    # Удаляем старое описание если есть
    pattern = r'<div class="item-description".*?</div>'
    html = re.sub(pattern, '', html, flags=re.DOTALL)

    # Вставляем после item-tags или перед item-shipping
    if "<div class='item-tags'>" in html:
        tags_end = html.find("</div>", html.find("<div class='item-tags'>")) + 6
        if tags_end > 6:
            html = html[:tags_end] + '\n                ' + desc_html + html[tags_end:]
            return safe_write(item_file, html)

    # fallback: перед item-shipping
    if '<div class="item-shipping">' in html:
        html = html.replace('<div class="item-shipping">', desc_html + '\n                <div class="item-shipping">')
        return safe_write(item_file, html)

    return False


# ─── Performance: добавление бейджа на карточку товара ──────────────────

def add_badge(item_id: str, badge_text: str) -> bool:
    """
    Добавляет бейдж (например 'ХИТ', 'NEW', 'ТОП') на карточку товара в index.html и item/{item_id}.html.
    """
    ok1 = _add_badge_to_item_page(item_id, badge_text)
    ok2 = _add_badge_to_index(item_id, badge_text)
    return ok1 or ok2


def _add_badge_to_item_page(item_id: str, badge_text: str) -> bool:
    item_file = Path(f"/var/www/dealshub-miniapp/item/{item_id}.html")
    if not item_file.exists():
        return False
    html = safe_read(item_file)

    # CSS класс по тексту бейджа
    css_class = "hit"
    if "NEW" in badge_text or "new" in badge_text:
        css_class = "new"
    elif "ТОП" in badge_text or "TOP" in badge_text or "top" in badge_text:
        css_class = "top"

    badge_html = f'<span class="item-extra-badge {css_class}">{badge_text}</span>'

    # Удаляем старый бейдж с таким же текстом (если есть)
    pattern = f'<span class="item-extra-badge[^"]*">{re.escape(badge_text)}</span>'
    html = re.sub(pattern, '', html)

    # Вставляем после <h1 class="item-title">
    if '<h1 class="item-title">' in html:
        # Находим закрывающий </h1> после item-title
        title_end = html.find('</h1>', html.find('<h1 class="item-title">'))
        if title_end > 0:
            insert_pos = title_end + 5
            html = html[:insert_pos] + '\n                ' + badge_html + html[insert_pos:]
            return safe_write(item_file, html)

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
