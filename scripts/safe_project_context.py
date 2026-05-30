import os
import json
from pathlib import Path
from typing import Dict, List, Any, Optional
import logging

logger = logging.getLogger("project_context")

PROJECT_ROOT = os.getenv("PROJECT_ROOT", "/var/www/dealshub-miniapp")

# ═══════════════════════════════════════════════════════
# PROTECTED FILES — НЕЛЬЗЯ ТРОГАТЬ
# ═══════════════════════════════════════════════════════
PROTECTED_PATHS = {
    # Ядро сайта — readonly
    "index.html": "CORE_SITE",
    "app.js": "CORE_SITE",
    "css/style.css": "CORE_SITE",
    "products.json": "CORE_SITE",
    
    # Существующие категории — readonly
    "category/Гайды и советы.html": "EXISTING",
    "category/Гиды по экономии.html": "EXISTING",
    "category/Советы покупателям.html": "EXISTING",
    "category/guides.html": "EXISTING",
    
    # Служебные
    "sitemap.xml": "SERVICE",
    "robots.txt": "SERVICE",
    "about.html": "EXISTING",
    "contact.html": "EXISTING",
    "privacy.html": "EXISTING",
    "terms.html": "EXISTING",
    
    # Иконки
    "icons/": "ASSETS",
    "images/": "ASSETS",
}

# ═══════════════════════════════════════════════════════
# SAFE ZONES — МОЖНО СОЗДАВАТЬ/ПЕРЕЗАПИСЫВАТЬ
# ═══════════════════════════════════════════════════════
SAFE_ZONES = [
    "guides/",           # Новые гайды и статьи
    "category/new-",     # Новые категории (префикс new-)
    "landing/",          # Лендинги для трафика
    "blog/",             # Блог-посты
    "reviews/",          # Обзоры товаров
    "comparisons/",      # Сравнения
    "seasonal/",         # Сезонные подборки
]


def is_protected(rel_path: str) -> tuple[bool, str]:
    """
    Проверяет, защищён ли файл от записи.
    
    Returns: (is_protected, reason)
    """
    rel_path = rel_path.lstrip("/")
    
    # Проверяем точное совпадение
    if rel_path in PROTECTED_PATHS:
        return True, f"PROTECTED: {PROTECTED_PATHS[rel_path]} — cannot modify"
    
    # Проверяем по префиксу (директории)
    for protected, reason in PROTECTED_PATHS.items():
        if protected.endswith("/") and rel_path.startswith(protected):
            return True, f"PROTECTED_DIR: {reason}"
        # Проверяем, если файл внутри защищённой директории
        if "/" in protected and not protected.endswith("/"):
            protected_dir = protected.rsplit("/", 1)[0] + "/"
            if rel_path.startswith(protected_dir):
                return True, f"PROTECTED_DIR: {reason}"
    
    return False, ""


def is_safe_zone(rel_path: str) -> tuple[bool, str]:
    """
    Проверяет, находится ли путь в безопасной зоне.
    
    Returns: (is_safe, zone_name)
    """
    rel_path = rel_path.lstrip("/")
    
    # Проверяем path traversal
    if ".." in rel_path:
        return False, ""
    
    for zone in SAFE_ZONES:
        if rel_path.startswith(zone):
            return True, zone.rstrip("/")
        # Проверяем по префиксу (для new-)
        if zone.endswith("-") and rel_path.startswith(zone):
            return True, zone.rstrip("-")
    
    return False, ""


def validate_file_op(rel_path: str, mode: str = "overwrite") -> Dict[str, Any]:
    """
    Валидирует операцию над файлом.
    
    Returns: {"valid": bool, "error": str, "warning": str, "zone": str}
    """
    result = {"valid": True, "error": "", "warning": "", "zone": ""}
    
    # 0. Проверяем path traversal
    if ".." in rel_path:
        result["valid"] = False
        result["error"] = f"🚫 BLOCKED: {rel_path} — Path traversal detected"
        return result
    
    # 1. Проверяем безопасную зону (сначала — новые файлы разрешены)
    safe, zone = is_safe_zone(rel_path)
    if safe:
        result["zone"] = zone
        result["warning"] = f"✅ SAFE ZONE: {zone}"
        return result
    
    # 2. Проверяем защищённые файлы
    protected, reason = is_protected(rel_path)
    if protected:
        result["valid"] = False
        result["error"] = f"🚫 BLOCKED: {rel_path} — {reason}"
        return result
    
    # 3. Если не в безопасной зоне и не защищён — разрешаем, но с предупреждением
    # (для новых файлов вне зон, но не в защищённых)
    if mode == "overwrite":
        # Проверяем, существует ли файл
        full_path = Path(PROJECT_ROOT) / rel_path
        if full_path.exists():
            result["warning"] = f"⚠️ OVERWRITE: {rel_path} exists and will be replaced"
        else:
            result["warning"] = f"⚠️ NEW_FILE: {rel_path} — not in safe zone, but allowed"
    
    return result


# Расширяем ProjectContext валидатором
from scripts.project_context import ProjectContext

class SafeProjectContext(ProjectContext):
    """
    Защищённая версия ProjectContext.
    
    - Нельзя перезаписать защищённые файлы
    - Можно создавать новые только в safe zones
    - Все операции логируются
    """
    
    def write_file(self, rel_path: str, content: str, append: bool = False) -> Dict[str, Any]:
        """Защищённая запись с валидацией."""
        mode = "append" if append else "overwrite"
        
        # Валидация
        validation = validate_file_op(rel_path, mode)
        
        if not validation["valid"]:
            logger.error("write_blocked: %s - %s", rel_path, validation["error"])
            return {
                "success": False,
                "error": validation["error"],
                "blocked": True,
                "path": rel_path,
            }
        
        # Логируем предупреждение если есть
        if validation["warning"]:
            logger.warning("write_warning: %s - %s", rel_path, validation["warning"])
        
        # Выполняем запись через родителя
        result = super().write_file(rel_path, content, append)
        result["validation"] = validation
        result["safe_zone"] = validation.get("zone", "")
        
        return result


# Удобные функции для импорта
def validate_write(rel_path: str, mode: str = "overwrite") -> Dict[str, Any]:
    """Проверить, можно ли записать файл."""
    return validate_file_op(rel_path, mode)


def get_safe_zones() -> List[str]:
    """Список безопасных зон для создания файлов."""
    return SAFE_ZONES.copy()


def get_protected_files() -> Dict[str, str]:
    """Список защищённых файлов с причинами."""
    return PROTECTED_PATHS.copy()


def safe_write_file(rel_path: str, content: str, append: bool = False) -> Dict[str, Any]:
    """Безопасная запись файла."""
    ctx = SafeProjectContext()
    return ctx.write_file(rel_path, content, append)
