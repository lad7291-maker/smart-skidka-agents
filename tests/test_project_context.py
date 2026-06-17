#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для project_context.py и safe_project_context.py.
Изолированные — используют tmp_path, не зависят от /var/www/dealshub-miniapp.
"""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

from scripts.project_context import ProjectContext, get_project_context
from scripts.safe_project_context import (
    SafeProjectContext,
    get_protected_files,
    get_safe_zones,
    is_protected,
    is_safe_zone,
    validate_file_op,
    validate_write,
)

# ═══════════════════════════════════════════════════════════════════════════════
# ProjectContext
# ═══════════════════════════════════════════════════════════════════════════════


class TestProjectContext:
    """Тесты для ProjectContext."""

    def test_scan_empty_dir(self, tmp_path):
        """scan() возвращает дерево с пустыми children для пустой директории."""
        ctx = ProjectContext(str(tmp_path))
        tree = ctx.scan(max_depth=1)
        assert tree["name"] == tmp_path.name
        assert tree["type"] == "directory"
        assert tree["children"] == []

    def test_scan_with_files(self, tmp_path):
        """scan() находит файлы."""
        (tmp_path / "index.html").write_text("<html></html>")
        (tmp_path / "app.js").write_text("console.log('hi')")
        ctx = ProjectContext(str(tmp_path))
        tree = ctx.scan(max_depth=1)
        names = [c["name"] for c in tree["children"]]
        assert "index.html" in names
        assert "app.js" in names

    def test_scan_skips_hidden(self, tmp_path):
        """scan() пропускает скрытые файлы."""
        (tmp_path / ".gitignore").write_text("*.pyc")
        (tmp_path / "visible.txt").write_text("ok")
        ctx = ProjectContext(str(tmp_path))
        tree = ctx.scan(max_depth=1)
        names = [c["name"] for c in tree["children"]]
        assert ".gitignore" not in names
        assert "visible.txt" in names

    def test_scan_recursion(self, tmp_path):
        """scan() рекурсивно сканирует поддиректории."""
        sub = tmp_path / "guides"
        sub.mkdir()
        (sub / "test.md").write_text("# Test")
        ctx = ProjectContext(str(tmp_path))
        tree = ctx.scan(max_depth=2)
        guide_node = [c for c in tree["children"] if c["name"] == "guides"][0]
        assert guide_node["type"] == "directory"
        assert len(guide_node["children"]) == 1
        assert guide_node["children"][0]["name"] == "test.md"

    def test_scan_respects_max_depth(self, tmp_path):
        """scan() не уходит глубже max_depth."""
        sub = tmp_path / "a" / "b"
        sub.mkdir(parents=True)
        (sub / "deep.txt").write_text("deep")
        ctx = ProjectContext(str(tmp_path))
        tree = ctx.scan(max_depth=2)
        a_node = [c for c in tree["children"] if c["name"] == "a"][0]
        # depth=2: a показывается, но b — пустой (depth limit)
        assert a_node["type"] == "directory"

    def test_read_file_success(self, tmp_path):
        """read_file() читает содержимое."""
        (tmp_path / "test.txt").write_text("Hello World")
        ctx = ProjectContext(str(tmp_path))
        content = ctx.read_file("test.txt", max_chars=100)
        assert "Hello World" in content

    def test_read_file_not_found(self, tmp_path):
        """read_file() возвращает ошибку для несуществующего файла."""
        ctx = ProjectContext(str(tmp_path))
        content = ctx.read_file("missing.txt", max_chars=100)
        assert "ERROR" in content or "not found" in content.lower()

    def test_read_file_max_chars(self, tmp_path):
        """read_file() обрезает по max_chars."""
        (tmp_path / "long.txt").write_text("A" * 1000)
        ctx = ProjectContext(str(tmp_path))
        content = ctx.read_file("long.txt", max_chars=100)
        assert len(content) <= 150  # небольшой допуск для преамбулы

    def test_read_file_html(self, tmp_path):
        """read_file() добавляет преамбулу для HTML."""
        (tmp_path / "page.html").write_text("<html><body>Test</body></html>")
        ctx = ProjectContext(str(tmp_path))
        content = ctx.read_file("page.html", max_chars=200)
        assert "HTML" in content or "<html>" in content

    def test_read_file_json(self, tmp_path):
        """read_file() форматирует JSON."""
        data = {"key": "value", "list": [1, 2, 3]}
        (tmp_path / "data.json").write_text(json.dumps(data))
        ctx = ProjectContext(str(tmp_path))
        content = ctx.read_file("data.json", max_chars=500)
        assert '"key"' in content

    def test_write_file_new(self, tmp_path):
        """write_file() создаёт новый файл."""
        ctx = ProjectContext(str(tmp_path))
        result = ctx.write_file("new.txt", "content")
        assert result["success"] is True
        assert (tmp_path / "new.txt").read_text() == "content"

    def test_write_file_overwrite(self, tmp_path):
        """write_file() перезаписывает существующий."""
        (tmp_path / "existing.txt").write_text("old")
        ctx = ProjectContext(str(tmp_path))
        result = ctx.write_file("existing.txt", "new")
        assert result["success"] is True
        assert (tmp_path / "existing.txt").read_text() == "new"

    def test_write_file_append(self, tmp_path):
        """write_file() дописывает при append=True."""
        (tmp_path / "log.txt").write_text("line1\n")
        ctx = ProjectContext(str(tmp_path))
        result = ctx.write_file("log.txt", "line2\n", append=True)
        assert result["success"] is True
        assert "line1" in (tmp_path / "log.txt").read_text()
        assert "line2" in (tmp_path / "log.txt").read_text()

    def test_write_file_creates_dirs(self, tmp_path):
        """write_file() создаёт поддиректории."""
        ctx = ProjectContext(str(tmp_path))
        result = ctx.write_file("sub/deep/file.txt", "deep content")
        assert result["success"] is True
        assert (tmp_path / "sub" / "deep" / "file.txt").read_text() == "deep content"

    def test_write_file_path_traversal_blocked(self, tmp_path):
        """write_file() блокирует path traversal."""
        ctx = ProjectContext(str(tmp_path))
        result = ctx.write_file("../outside.txt", "evil")
        assert result["success"] is False
        assert "traversal" in result.get("error", "").lower()

    def test_list_dir(self, tmp_path):
        """list_dir() возвращает список файлов."""
        (tmp_path / "a.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")
        ctx = ProjectContext(str(tmp_path))
        files = ctx.list_dir(".")
        names = [f["name"] for f in files]
        assert "a.txt" in names
        assert "b.txt" in names

    def test_list_dir_details(self, tmp_path):
        """list_dir() возвращает детали файлов."""
        (tmp_path / "stats.txt").write_text("stats content")
        ctx = ProjectContext(str(tmp_path))
        files = ctx.list_dir(".")
        stats_file = [f for f in files if f["name"] == "stats.txt"][0]
        assert stats_file["type"] == "file"
        assert stats_file["size"] == len("stats content")

    def test_get_context_for_agent(self, tmp_path):
        """get_context_for_agent() возвращает строку с контекстом."""
        (tmp_path / "index.html").write_text("<html><title>Site</title></html>")
        (tmp_path / "products.json").write_text('[{"id":1}]')
        (tmp_path / "app.js").write_text("console.log('app')")
        ctx = ProjectContext(str(tmp_path))
        context = ctx.get_context_for_agent("content")
        assert isinstance(context, str)
        assert len(context) > 100

    def test_cache_hit(self, tmp_path):
        """read_file() использует кэш."""
        (tmp_path / "cached.txt").write_text("cached")
        ctx = ProjectContext(str(tmp_path))
        ctx.read_file("cached.txt", max_chars=100)
        assert "cached.txt" in ctx.cache

    def test_get_project_context_singleton(self, tmp_path):
        """get_project_context() возвращает singleton."""
        with patch("scripts.project_context.PROJECT_ROOT", str(tmp_path)):
            ctx1 = get_project_context()
            ctx2 = get_project_context()
            assert ctx1 is ctx2


# ═══════════════════════════════════════════════════════════════════════════════
# SafeProjectContext
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsProtected:
    """Тесты is_protected()."""

    def test_exact_match(self):
        assert is_protected("index.html")[0] is True

    def test_no_match(self):
        assert is_protected("new-file.txt")[0] is False

    def test_prefix_dir(self):
        assert is_protected("icons/logo.png")[0] is True

    def test_leading_slash(self):
        assert is_protected("/index.html")[0] is True


class TestIsSafeZone:
    """Тесты is_safe_zone()."""

    def test_guides(self):
        assert is_safe_zone("guides/new-guide.md")[0] is True

    def test_landing(self):
        assert is_safe_zone("landing/promo.html")[0] is True

    def test_new_prefix(self):
        assert is_safe_zone("category/new-electronics.html")[0] is True

    def test_not_safe(self):
        assert is_safe_zone("index.html")[0] is False

    def test_path_traversal(self):
        assert is_safe_zone("../etc/passwd")[0] is False


class TestValidateFileOp:
    """Тесты validate_file_op()."""

    def test_safe_zone(self):
        result = validate_file_op("guides/test.md")
        assert result["valid"] is True
        assert "SAFE ZONE" in result["warning"]

    def test_protected(self):
        result = validate_file_op("index.html")
        assert result["valid"] is False
        assert "BLOCKED" in result["error"]

    def test_path_traversal(self):
        result = validate_file_op("../etc/passwd")
        assert result["valid"] is False
        assert "traversal" in result["error"].lower()

    def test_new_file_outside_zones(self):
        result = validate_file_op("random.txt", mode="overwrite")
        assert result["valid"] is True
        assert "NEW_FILE" in result["warning"]

    def test_overwrite_existing(self, tmp_path):
        with patch("scripts.safe_project_context.PROJECT_ROOT", str(tmp_path)):
            (tmp_path / "existing.txt").write_text("old")
            result = validate_file_op("existing.txt", mode="overwrite")
            assert result["valid"] is True
            assert "OVERWRITE" in result["warning"]


class TestSafeProjectContext:
    """Тесты SafeProjectContext."""

    def test_write_safe_zone(self, tmp_path):
        ctx = SafeProjectContext(str(tmp_path))
        result = ctx.write_file("guides/test.md", "# Guide")
        assert result["success"] is True
        assert (tmp_path / "guides" / "test.md").read_text() == "# Guide"

    def test_write_protected_blocked(self, tmp_path):
        ctx = SafeProjectContext(str(tmp_path))
        result = ctx.write_file("index.html", "<html>evil</html>")
        assert result["success"] is False
        assert result["blocked"] is True

    def test_write_validation_in_result(self, tmp_path):
        ctx = SafeProjectContext(str(tmp_path))
        result = ctx.write_file("guides/v.md", "content")
        assert "validation" in result
        assert "safe_zone" in result

    def test_validate_write_function(self):
        result = validate_write("guides/test.md")
        assert result["valid"] is True

    def test_get_safe_zones(self):
        zones = get_safe_zones()
        assert "guides/" in zones
        assert "landing/" in zones

    def test_get_protected_files(self):
        protected = get_protected_files()
        assert "index.html" in protected
        assert "app.js" in protected

    def test_safe_write_file_function(self, tmp_path):
        with patch("scripts.safe_project_context.PROJECT_ROOT", str(tmp_path)):
            result = validate_write("guides/func.md")
            assert result["valid"] is True
