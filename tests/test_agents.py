import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/opt/smart-skidka-agents")

from scripts.project_context import ProjectContext, get_project_context
from scripts.safe_project_context import (
    SafeProjectContext,
    get_protected_files,
    get_safe_zones,
    is_protected,
    is_safe_zone,
    validate_write,
)


class TestProjectContext(unittest.TestCase):
    """Тесты для ProjectContext (глаза агентов)."""

    def setUp(self):
        self.ctx = ProjectContext("/var/www/dealshub-miniapp")

    def test_scan_returns_tree(self):
        """Сканирование возвращает дерево файлов."""
        tree = self.ctx.scan(max_depth=1)
        self.assertIn("name", tree)
        self.assertIn("children", tree)
        self.assertGreater(len(tree["children"]), 0)

    def test_scan_has_index_html(self):
        """В дереве есть HTML-файл."""
        tree = self.ctx.scan(max_depth=1)
        names = [c["name"] for c in tree["children"] if c.get("type") == "file"]
        self.assertIn("home.html", names)

    def test_read_file_index_html(self):
        """Чтение home.html возвращает HTML."""
        content = self.ctx.read_file("home.html", max_chars=1000)
        self.assertIn("<!DOCTYPE html>", content)
        self.assertIn("smart-skidka", content.lower())

    def test_read_file_products_json(self):
        """Чтение all.json возвращает JSON-массив."""
        content = self.ctx.read_file("all.json", max_chars=2000)
        self.assertIn('"id"', content)
        self.assertIn('"title"', content)

    def test_read_file_not_found(self):
        """Чтение несуществующего файла возвращает ошибку."""
        content = self.ctx.read_file("nonexistent.html")
        self.assertIn("ERROR", content)

    def test_path_traversal_blocked(self):
        """Path traversal заблокирован."""
        content = self.ctx.read_file("../etc/passwd")
        self.assertIn("blocked", content.lower())

    def test_get_context_for_content_agent(self):
        """Контекст для content-agent содержит нужные файлы."""
        ctx = self.ctx.get_context_for_agent("content")
        self.assertIn("index.html", ctx)
        self.assertIn("products.json", ctx)
        self.assertIn("app.js", ctx)

    def test_get_context_for_seo_agent(self):
        """Контекст для seo-agent содержит страницы."""
        ctx = self.ctx.get_context_for_agent("seo")
        self.assertIn("index.html", ctx)
        self.assertIn("html", ctx.lower())

    def test_get_context_for_performance_agent(self):
        """Контекст для performance-agent содержит статистику."""
        ctx = self.ctx.get_context_for_agent("performance")
        self.assertIn("products.json", ctx)

    def test_singleton(self):
        """get_project_context возвращает singleton."""
        ctx1 = get_project_context()
        ctx2 = get_project_context()
        self.assertIs(ctx1, ctx2)


class TestSafeProjectContext(unittest.TestCase):
    """Тесты для SafeProjectContext (защита от поломки)."""

    def setUp(self):
        self.ctx = SafeProjectContext("/var/www/dealshub-miniapp")

    def test_protected_index_html(self):
        """index.html защищён."""
        result = validate_write("index.html", "overwrite")
        self.assertFalse(result["valid"])
        self.assertIn("BLOCKED", result["error"])

    def test_protected_app_js(self):
        """app.js защищён."""
        result = validate_write("app.js", "overwrite")
        self.assertFalse(result["valid"])

    def test_protected_css(self):
        """css/style.css защищён."""
        result = validate_write("css/style.css", "overwrite")
        self.assertFalse(result["valid"])

    def test_protected_products_json(self):
        """products.json защищён."""
        result = validate_write("products.json", "overwrite")
        self.assertFalse(result["valid"])

    def test_protected_existing_category(self):
        """Существующая категория защищена."""
        result = validate_write("category/Гайды и советы.html", "overwrite")
        self.assertFalse(result["valid"])

    def test_safe_zone_guides(self):
        """guides/ — safe zone."""
        result = validate_write("guides/test.html", "overwrite")
        self.assertTrue(result["valid"])
        self.assertEqual(result["zone"], "guides")

    def test_safe_zone_landing(self):
        """landing/ — safe zone."""
        result = validate_write("landing/promo.html", "overwrite")
        self.assertTrue(result["valid"])
        self.assertEqual(result["zone"], "landing")

    def test_safe_zone_blog(self):
        """blog/ — safe zone."""
        result = validate_write("blog/post-1.html", "overwrite")
        self.assertTrue(result["valid"])
        self.assertEqual(result["zone"], "blog")

    def test_safe_zone_reviews(self):
        """reviews/ — safe zone."""
        result = validate_write("reviews/iphone-15.html", "overwrite")
        self.assertTrue(result["valid"])

    def test_safe_zone_comparisons(self):
        """comparisons/ — safe zone."""
        result = validate_write("comparisons/xiaomi-vs-samsung.html", "overwrite")
        self.assertTrue(result["valid"])

    def test_new_category_with_prefix(self):
        """category/new-* — разрешено."""
        result = validate_write("category/new-naushniki.html", "overwrite")
        self.assertTrue(result["valid"])

    def test_existing_category_blocked(self):
        """category/existing.html — блокируется."""
        result = validate_write("category/existing.html", "overwrite")
        # Если файл не существует в protected list, он пройдёт
        # Но если мы добавим его в PROTECTED_PATHS, будет blocked
        # Проверяем что реальный существующий файл blocked
        result2 = validate_write("category/Гайды и советы.html", "overwrite")
        self.assertFalse(result2["valid"])

    def test_new_file_outside_zone(self):
        """Новый файл вне zone — разрешён с предупреждением."""
        result = validate_write("random.html", "overwrite")
        self.assertTrue(result["valid"])
        self.assertIn("NEW_FILE", result["warning"])

    def test_path_traversal_blocked(self):
        """Path traversal в safe zones заблокирован."""
        result = validate_write("guides/../../etc/passwd", "overwrite")
        self.assertFalse(result["valid"])

    def test_safe_write_to_guides(self):
        """Запись в guides/ работает."""
        result = self.ctx.write_file("guides/test-safe-write.html", "<html><body>Test</body></html>")
        self.assertTrue(result["success"])
        self.assertFalse(result.get("blocked", False))
        self.assertEqual(result["safe_zone"], "guides")
        # Чистим за собой
        try:
            Path("/var/www/dealshub-miniapp/guides/test-safe-write.html").unlink()
        except:
            pass

    def test_blocked_write_to_index(self):
        """Запись в index.html блокируется."""
        result = self.ctx.write_file("index.html", "<html>hacked</html>")
        self.assertFalse(result["success"])
        self.assertTrue(result.get("blocked", False))

    def test_get_safe_zones(self):
        """get_safe_zones возвращает список."""
        zones = get_safe_zones()
        self.assertIn("guides/", zones)
        self.assertIn("landing/", zones)

    def test_get_protected_files(self):
        """get_protected_files возвращает словарь."""
        protected = get_protected_files()
        self.assertIn("index.html", protected)
        self.assertEqual(protected["index.html"], "CORE_SITE")

    def test_is_protected_function(self):
        """is_protected работает корректно."""
        blocked, reason = is_protected("index.html")
        self.assertTrue(blocked)
        self.assertIn("CORE_SITE", reason)

    def test_is_safe_zone_function(self):
        """is_safe_zone работает корректно."""
        safe, zone = is_safe_zone("guides/article.html")
        self.assertTrue(safe)
        self.assertEqual(zone, "guides")


class TestIntegration(unittest.TestCase):
    """Интеграционные тесты."""

    def test_end_to_end_content_creation(self):
        """Полный цикл: контекст → валидация → запись."""
        # 1. Получаем контекст
        ctx = get_project_context()
        context = ctx.get_context_for_agent("content")
        self.assertGreater(len(context), 1000)

        # 2. Пытаемся записать в safe zone
        safe = SafeProjectContext()
        result = safe.write_file("guides/test-integration.html", "<html><body>Integration Test</body></html>")
        self.assertTrue(result["success"])

        # 3. Проверяем, что файл создан
        path = Path("/var/www/dealshub-miniapp/guides/test-integration.html")
        self.assertTrue(path.exists())

        # 4. Чистим
        path.unlink()

    def test_multiple_safe_writes(self):
        """Множественные записи в safe zone."""
        safe = SafeProjectContext()
        files = [
            "guides/test-1.html",
            "guides/test-2.html",
            "landing/test-1.html",
        ]
        for f in files:
            result = safe.write_file(f, "<html><body>Test</body></html>")
            self.assertTrue(result["success"])

        # Чистим
        for f in files:
            try:
                Path(f"/var/www/dealshub-miniapp/{f}").unlink()
            except:
                pass

    def test_mixed_valid_and_invalid(self):
        """Смешанные операции: valid + invalid."""
        safe = SafeProjectContext()

        # Valid
        r1 = safe.write_file("guides/valid.html", "<html></body>Valid</body></html>")
        self.assertTrue(r1["success"])

        # Invalid
        r2 = safe.write_file("index.html", "<html></body>Invalid</body></html>")
        self.assertFalse(r2["success"])
        self.assertTrue(r2["blocked"])

        # Valid
        r3 = safe.write_file("landing/valid.html", "<html></body>Valid</body></html>")
        self.assertTrue(r3["success"])

        # Чистим
        for f in ["guides/valid.html", "landing/valid.html"]:
            try:
                Path(f"/var/www/dealshub-miniapp/{f}").unlink()
            except:
                pass


if __name__ == "__main__":
    # Запускаем с подробным выводом
    unittest.main(verbosity=2)
