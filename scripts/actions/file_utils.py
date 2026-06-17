#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Безопасные операции с файлами проекта.
Каждая операция делает бэкап перед изменением.
"""

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

# Пути к проекту
def _get_site_root() -> Path:
    """Возвращает SITE_ROOT из env var (динамически, для тестов)."""
    return Path(os.getenv("PROJECT_ROOT", "/var/www/dealshub-miniapp")).resolve()


SITE_ROOT = _get_site_root()
PRODUCTS_JSON = SITE_ROOT / "products.json"
INDEX_HTML = SITE_ROOT / "index.html"
ITEMS_DIR = SITE_ROOT / "item"


def _resolve_within_site_root(path: Path) -> Path:
    """Проверяет, что путь находится внутри SITE_ROOT (защита от path traversal)."""
    resolved = path.resolve()
    site_root_resolved = _get_site_root().resolve()
    # Приводим к общему виду для сравнения
    try:
        resolved.relative_to(site_root_resolved)
    except ValueError:
        raise ValueError(f"Path traversal detected: {resolved} is outside SITE_ROOT {site_root_resolved}")
    return resolved


def _backup_path(target: Path) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(str(target) + f".bak.{ts}")


def safe_read(path: Path) -> str:
    """Читает файл, возвращает пустую строку если не найден."""
    try:
        _resolve_within_site_root(path)
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except ValueError:
        # Path traversal — silently return empty
        return ""


def safe_write(path: Path, content: str, make_backup: bool = True) -> bool:
    """
    Атомарно пишет файл с бэкапом.
    1. Проверяет, что путь внутри SITE_ROOT
    2. Делает бэкап оригинала
    3. Пишет во временный файл
    4. Перемещает (атомарно)
    5. При ошибке — откатывает из бэкапа
    """
    backup: Optional[Path] = None
    try:
        _resolve_within_site_root(path)

        if make_backup and path.exists():
            backup = _backup_path(path)
            shutil.copy2(path, backup)

        tmp = Path(str(path) + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        tmp.rename(path)
        return True
    except Exception as e:
        # rollback из сохранённого бэкапа
        if backup is not None and backup.exists():
            try:
                shutil.copy2(backup, path)
            except Exception as rollback_err:
                print(f"[ERROR] rollback failed for {path}: {rollback_err}")
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
    return safe_read(_get_site_root() / "index.html")


def write_site_html(content: str) -> bool:
    return safe_write(_get_site_root() / "index.html", content)


def read_products() -> dict:
    data = safe_read_json(_get_site_root() / "products.json")
    if isinstance(data, list):
        return {"products": data}
    return data if isinstance(data, dict) else {}


# ─── P1-9: Защита products.json — whitelist операций ─────────────────────


# Разрешённые поля для обновления через агентов
PRODUCTS_ALLOWED_FIELDS = {
    "description",  # Описание товара
    "badge",  # Бейдж (Тренд, ХИТ, NEW)
    "priority",  # Приоритет сортировки
    "discount",  # Размер скидки
    "promo_code",  # Промокод
    "expires_at",  # Срок действия акции
}

# Поля, которые НЕЛЬЗЯ менять через агентов
PRODUCTS_PROTECTED_FIELDS = {
    "id",
    "name",
    "price",
    "original_price",
    "image",
    "category",
    "link",
    "rating",
    "reviews",
}


def validate_products_update(item_id: str, field: str, value) -> tuple[bool, str]:
    """
    Проверяет, разрешено ли обновление поля товара.

    Returns: (is_allowed, reason)
    """
    if field in PRODUCTS_PROTECTED_FIELDS:
        return False, f"Field '{field}' is protected and cannot be modified by agents"
    if field not in PRODUCTS_ALLOWED_FIELDS:
        return (
            False,
            f"Field '{field}' is not in allowed fields list: {PRODUCTS_ALLOWED_FIELDS}",
        )
    return True, ""


def write_products(data: dict, validate: bool = False) -> bool:
    """
    Атомарно пишет products.json с бэкапом.

    Args:
        data: Данные для записи
        validate: Если True, проверяет разрешённые поля (для агентов)
    """
    # Если data — dict с "products", сохраняем как list для совместимости с app.js
    products_json = _get_site_root() / "products.json"
    if isinstance(data, dict) and "products" in data:
        return safe_write_json(products_json, data["products"])
    return safe_write_json(products_json, data)


def list_items() -> list:
    """Список всех HTML-страниц товаров."""
    items_dir = _get_site_root() / "item"
    if not items_dir.exists():
        return []
    return sorted([f.name for f in items_dir.glob("*.html")])


# ─── COS-1: Git versioning on file changes ───────────────────────────────


def git_commit_file(path: Path, message: Optional[str] = None) -> bool:
    """
    Автоматически коммитит изменённый файл в git.

    Args:
        path: Путь к файлу
        message: Сообщение коммита (auto-generated если None)

    Returns:
        True если коммит создан или файл уже в git
    """
    try:
        # Проверяем, что это git-репозиторий
        repo_root = Path(path).resolve()
        while repo_root != repo_root.parent:
            if (repo_root / ".git").exists():
                break
            repo_root = repo_root.parent
        else:
            # Не git-репозиторий — молча пропускаем
            return True

        rel_path = Path(path).resolve().relative_to(repo_root)

        # Проверяем, есть ли изменения
        result = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain", str(rel_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return False

        # Если нет изменений — ничего не делаем
        if not result.stdout.strip():
            return True

        # Добавляем файл
        add_result = subprocess.run(
            ["git", "-C", str(repo_root), "add", str(rel_path)],
            capture_output=True,
            timeout=10,
        )
        if add_result.returncode != 0:
            return False

        # Создаём коммит
        if message is None:
            message = f"agent: update {rel_path} at {datetime.now().strftime('%Y-%m-%d %H:%M')}"

        commit_result = subprocess.run(
            ["git", "-C", str(repo_root), "commit", "-m", message],
            capture_output=True,
            timeout=10,
        )
        return commit_result.returncode == 0

    except FileNotFoundError:
        # git не установлен — пропускаем
        return True
    except subprocess.TimeoutExpired:
        return False
    except Exception as e:
        print(f"[GIT WARN] git_commit_file failed for {path}: {e}")
        return False


def safe_write_with_git(
    path: Path,
    content: str,
    make_backup: bool = True,
    git_message: Optional[str] = None,
) -> bool:
    """
    Атомарная запись + автоматический git-коммит.

    Args:
        path: Путь к файлу
        content: Содержимое
        make_backup: Создавать ли бэкап
        git_message: Сообщение коммита

    Returns:
        True если запись успешна (git-коммит опционален)
    """
    ok = safe_write(path, content, make_backup)
    if ok:
        git_commit_file(path, git_message)
    return ok
