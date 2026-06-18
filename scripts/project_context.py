import logging
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger("project_context")

PROJECT_ROOT = os.getenv("PROJECT_ROOT", "/var/www/dealshub-miniapp")


class ProjectContext:
    """
    Дает агентам доступ к файловой системе проекта.

    Возможности:
    - scan(): сканировать структуру проекта
    - read_file(): читать содержимое файла
    - write_file(): записывать изменения
    - list_dir(): список файлов в директории
    - get_file_stats(): метаданные файла
    """

    def __init__(self, root: str = PROJECT_ROOT):
        self.root = Path(root)
        self.cache: Dict[str, Any] = {}

    def scan(self, max_depth: int = 3) -> Dict[str, Any]:
        """
        Сканирует проект и возвращает дерево файлов.
        """
        tree = {
            "name": self.root.name or "dealshub-miniapp",
            "type": "directory",
            "children": [],
        }

        try:
            for item in sorted(self.root.iterdir()):
                if item.name.startswith(".") or item.name in ("node_modules",):
                    continue

                node = self._scan_item(item, depth=1, max_depth=max_depth)
                if node:
                    tree["children"].append(node)
        except Exception as e:
            logger.error("scan_failed", error=str(e))
            return {"error": str(e)}

        return tree

    def _scan_item(self, path: Path, depth: int, max_depth: int) -> Optional[Dict[str, Any]]:
        """Рекурсивное сканирование."""
        try:
            if path.is_file():
                size = path.stat().st_size
                return {
                    "name": path.name,
                    "type": "file",
                    "size": size,
                    "ext": path.suffix,
                }

            if path.is_dir() and depth < max_depth:
                children = []
                try:
                    for child in sorted(path.iterdir()):
                        if child.name.startswith("."):
                            continue
                        node = self._scan_item(child, depth + 1, max_depth)
                        if node:
                            children.append(node)
                except PermissionError:
                    pass

                return {
                    "name": path.name,
                    "type": "directory",
                    "children": children,
                }

            return {"name": path.name, "type": "directory", "children": []}
        except Exception:
            return None

    def read_file(self, rel_path: str, max_chars: int = 10000) -> str:
        """
        Читает файл из проекта.

        Args:
            rel_path: Относительный путь от PROJECT_ROOT (например, "index.html")
            max_chars: Максимум символов для чтения
        """
        try:
            full_path = self.root / rel_path
            # Защита от path traversal
            real_path = full_path.resolve()
            real_root = self.root.resolve()
            if not str(real_path).startswith(str(real_root)):
                return f"ERROR: Path traversal blocked: {rel_path}"

            if not real_path.exists():
                return f"ERROR: File not found: {rel_path}"

            content = real_path.read_text(encoding="utf-8", errors="ignore")
            if len(content) > max_chars:
                content = content[:max_chars] + f"\n\n... [{len(content) - max_chars} chars truncated]"

            self.cache[rel_path] = content
            return content
        except Exception as e:
            logger.error("read_file_failed", path=rel_path, error=str(e))
            return f"ERROR: {str(e)}"

    def write_file(self, rel_path: str, content: str, append: bool = False) -> Dict[str, Any]:
        """
        Записывает файл в проект с атомарной записью и валидацией HTML.

        Args:
            rel_path: Относительный путь
            content: Содержимое для записи
            append: True — добавить в конец, False — перезаписать

        Returns:
            {"success": bool, "path": str, "backup": str|None, "html_valid": bool,
             "http_status": int|None, "error": str}
        """
        import shutil
        import tempfile

        full_path = self.root / rel_path
        real_path = full_path.resolve()
        real_root = self.root.resolve()

        # Защита от path traversal
        if not str(real_path).startswith(str(real_root)):
            return {"success": False, "error": f"Path traversal blocked: {rel_path}"}

        try:
            # Создаем директории если нужно
            real_path.parent.mkdir(parents=True, exist_ok=True)

            backup_path = None

            if not append and real_path.exists():
                # CRIT-1: Создаём бэкап перед перезаписью
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                backup_path = str(real_path) + f".bak.{ts}"
                shutil.copy2(real_path, backup_path)

            if append:
                # Append — просто дописываем
                with open(real_path, "a", encoding="utf-8") as f:
                    f.write(content)
            else:
                # P1-X: Auto-inject charset into HTML if missing
                if rel_path.endswith(".html") and "charset=" not in content.lower():
                    content = self._inject_html_charset(content)
                # CRIT-2: Атомарная запись через временный файл
                tmp_fd, tmp_path = tempfile.mkstemp(dir=real_path.parent, prefix=f".{real_path.name}.", suffix=".tmp")
                try:
                    with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
                        f.write(content)
                    # Атомарный rename
                    os.replace(tmp_path, real_path)
                    # P1-X: Устанавливаем права для nginx
                    try:
                        os.chmod(real_path, 0o644)
                        shutil.chown(real_path, user="www-data", group="www-data")
                    except Exception:
                        pass  # Если не root — пропускаем
                except Exception:
                    # При ошибке — удаляем временный файл
                    try:
                        os.unlink(tmp_path)
                    except FileNotFoundError:
                        pass
                    raise

            result = {
                "success": True,
                "path": rel_path,
                "size": len(content),
                "mode": "append" if append else "overwrite",
                "backup": backup_path,
            }

            # CRIT-3: Валидация HTML после записи
            if rel_path.endswith(".html"):
                html_valid = self._validate_html(content)
                result["html_valid"] = html_valid
                if not html_valid:
                    result["warning"] = "HTML may be malformed: missing </html>, </body>, or <title>"

            # CRIT-5: Проверка HTTP 200 (если nginx/localhost доступен)
            http_status = self._check_http_status(rel_path)
            if http_status:
                result["http_status"] = http_status

            logger.info(
                "file_written: %s size=%d backup=%s",
                rel_path,
                len(content),
                backup_path,
            )
            return result

        except Exception as e:
            logger.error("write_file_failed: %s - %s", rel_path, str(e))
            return {"success": False, "error": str(e)}

    def _inject_html_charset(self, content: str) -> str:
        """P1-X: Автоматически добавляет <meta charset=\"UTF-8\"> в HTML если отсутствует."""
        if "<meta charset=" in content.lower():
            return content
        # Ищем <head> и вставляем charset сразу после него
        head_match = re.search(r"(<head[^>]*>)", content, re.IGNORECASE)
        if head_match:
            insert_pos = head_match.end()
            return content[:insert_pos] + '\n<meta charset="UTF-8">' + content[insert_pos:]
        # Если нет <head>, ищем <html> и добавляем <head> с charset
        html_match = re.search(r"(<html[^>]*>)", content, re.IGNORECASE)
        if html_match:
            insert_pos = html_match.end()
            return (
                content[:insert_pos]
                + '\n<head><meta charset="UTF-8"><title>Smart Skidka</title></head>'
                + content[insert_pos:]
            )
        # Fallback: добавляем в начало
        return '<meta charset="UTF-8">\n' + content

    def _validate_html(self, content: str) -> bool:
        """CRIT-3: Проверяет базовую валидность HTML и наличие charset."""
        content_lower = content.lower()
        checks = [
            "</html>" in content_lower,
            "</body>" in content_lower,
            "<title>" in content_lower,
            'charset="utf-8"' in content_lower
            or "charset='utf-8'" in content_lower
            or 'charset="utf-8"' in content_lower,
        ]
        return all(checks)

    def _check_http_status(self, rel_path: str) -> Optional[int]:
        """CRIT-5: Проверяет HTTP статус страницы через curl."""
        try:
            # Пытаемся сделать HEAD запрос к localhost
            url_path = rel_path.lstrip("/")
            result = subprocess.run(
                [
                    "curl",
                    "-s",
                    "-o",
                    "/dev/null",
                    "-w",
                    "%{http_code}",
                    f"http://localhost/{url_path}",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                status = int(result.stdout.strip())
                return status
        except Exception:
            pass
        return None

    def list_dir(self, rel_path: str = ".") -> List[Dict[str, Any]]:
        """Список файлов в директории."""
        try:
            full_path = self.root / rel_path
            real_path = full_path.resolve()
            real_root = self.root.resolve()

            if not str(real_path).startswith(str(real_root)):
                return [{"error": f"Path traversal blocked: {rel_path}"}]

            items = []
            for item in sorted(real_path.iterdir()):
                if item.name.startswith("."):
                    continue
                stat = item.stat()
                items.append(
                    {
                        "name": item.name,
                        "type": "directory" if item.is_dir() else "file",
                        "size": stat.st_size if item.is_file() else None,
                    }
                )
            return items
        except Exception as e:
            return [{"error": str(e)}]

    def get_context_for_agent(self, agent_type: str) -> str:
        """
        Формирует контекст проекта для конкретного агента.

        Каждый агент получает релевантную часть проекта.
        """
        parts = []

        # Общая структура (краткая)
        parts.append("## Структура проекта SmartSkidka.ru")
        tree = self.scan(max_depth=2)
        parts.append(self._format_tree(tree))

        # Контекст по типу агента
        if agent_type in ("smm", "content", "seo"):
            # Эти агенты работают с контентом — показываем ему ключевые файлы
            parts.append("\n## Текущий index.html (первые 2000 символов)")
            parts.append(self.read_file("index.html", max_chars=2000))

            parts.append("\n## Текущие товары (products.json — первые 3000 символов)")
            parts.append(self.read_file("products.json", max_chars=3000))

            parts.append("\n## Текущий app.js (первые 1500 символов)")
            parts.append(self.read_file("app.js", max_chars=1500))

        elif agent_type == "performance":
            # Performance работает с товарами
            parts.append("\n## Текущие товары (products.json)")
            parts.append(self.read_file("products.json", max_chars=5000))

            # Статистика файлов
            parts.append("\n## Статистика")
            parts.append(f"- Файлов товаров item/*.html: {len(list(self.root.glob('item/*.html')))}")
            parts.append(f"- Файлов категорий category/*.html: {len(list(self.root.glob('category/*.html')))}")

        elif agent_type == "analytics":
            # Analytics смотрит на структуру
            parts.append("\n## Страницы сайта")
            for page in sorted(self.root.glob("*.html")):
                parts.append(f"- {page.name} ({page.stat().st_size} bytes)")

            parts.append("\n## Товарные страницы")
            items = list(self.root.glob("item/*.html"))
            parts.append(f"- Всего: {len(items)} товарных страниц")
            for item in sorted(items)[:5]:
                parts.append(f"  - {item.name}")

        return "\n".join(parts)

    def _format_tree(self, node: Dict[str, Any], indent: int = 0) -> str:
        """Форматирует дерево для вывода."""
        lines = []
        prefix = "  " * indent

        if node.get("type") == "file":
            size = node.get("size", 0)
            lines.append(f"{prefix}- {node['name']} ({size} bytes)")
        else:
            lines.append(f"{prefix}+ {node['name']}/")
            for child in node.get("children", [])[:20]:  # limit children
                lines.append(self._format_tree(child, indent + 1))
            if len(node.get("children", [])) > 20:
                lines.append(f"{prefix}  ... ({len(node['children']) - 20} more)")

        return "\n".join(lines)


# Singleton для повторного использования
_project_context: Optional[ProjectContext] = None


def get_project_context() -> ProjectContext:
    global _project_context
    if _project_context is None:
        _project_context = ProjectContext()
    return _project_context


# Удобные функции для импорта
def scan_project(max_depth: int = 3) -> Dict[str, Any]:
    return get_project_context().scan(max_depth)


def read_project_file(path: str, max_chars: int = 10000) -> str:
    return get_project_context().read_file(path, max_chars)


def write_project_file(path: str, content: str, append: bool = False) -> Dict[str, Any]:
    return get_project_context().write_file(path, content, append)


def list_project_dir(path: str = ".") -> List[Dict[str, Any]]:
    return get_project_context().list_dir(path)


def get_project_context_for_agent(agent_type: str) -> str:
    return get_project_context().get_context_for_agent(agent_type)
