#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Безопасные операции с файлами проекта.
Каждая операция делает бэкап перед изменением.
"""

import shutil
import json
from pathlib import Path
from datetime import datetime
from typing import Optional

# Пути к проекту
SITE_ROOT = Path("/var/www/dealshub-miniapp")
PRODUCTS_JSON = SITE_ROOT / "products.json"
INDEX_HTML = SITE_ROOT / "index.html"
ITEMS_DIR = SITE_ROOT / "item"

def _backup_path(target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(str(target) + f".bak.{ts}")

def safe_read(path: Path) -> str:
    """Читает файл, возвращает пустую строку если не найден."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""

def safe_write(path: Path, content: str, make_backup: bool = True) -> bool:
    """
    Атомарно пишет файл с бэкапом.
    1. Делает бэкап оригинала
    2. Пишет во временный файл
    3. Перемещает (атомарно)
    4. При ошибке — откатывает из бэкапа
    """
    try:
        if make_backup and path.exists():
            backup = _backup_path(path)
            shutil.copy2(path, backup)

        tmp = Path(str(path) + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.rename(path)
        return True
    except Exception as e:
        # rollback
        backup = _backup_path(path)
        if backup.exists():
            shutil.copy2(backup, path)
        print(f"[ERROR] safe_write failed for {path}: {e}")
        return False

def safe_read_json(path: Path) -> dict:
    """Читает JSON, возвращает {} при ошибке."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}

def safe_write_json(path: Path, data: dict) -> bool:
    """Атомарно пишет JSON с бэкапом."""
    try:
        content = json.dumps(data, ensure_ascii=False, indent=2)
        return safe_write(path, content)
    except Exception as e:
        print(f"[ERROR] safe_write_json failed: {e}")
        return False

def read_site_html() -> str:
    return safe_read(INDEX_HTML)

def write_site_html(content: str) -> bool:
    return safe_write(INDEX_HTML, content)

def read_products() -> dict:
    data = safe_read_json(PRODUCTS_JSON)
    if isinstance(data, list):
        return {"products": data}
    return data if isinstance(data, dict) else {}

def write_products(data: dict) -> bool:
    # Если data — dict с "products", сохраняем как list для совместимости с app.js
    if isinstance(data, dict) and "products" in data:
        return safe_write_json(PRODUCTS_JSON, data["products"])
    return safe_write_json(PRODUCTS_JSON, data)

def list_items() -> list:
    """Список всех HTML-страниц товаров."""
    if not ITEMS_DIR.exists():
        return []
    return sorted([f.name for f in ITEMS_DIR.glob("*.html")])
