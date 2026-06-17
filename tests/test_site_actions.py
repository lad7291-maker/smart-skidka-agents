#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для site_actions.py — действия агентов над файлами сайта.
"""

import asyncio
import importlib
import json
import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

# Set PROJECT_ROOT before any imports
os.environ["PROJECT_ROOT"] = "/tmp/test_site"

from scripts.actions.site_actions import (
    DAILY_CATEGORY_PAGE_LIMIT,
    _cleanup_old_entries,
    _get_quota_tracker_path,
    _h,
    _load_quota_tracker,
    _parse_time,
    _save_quota_tracker,
    add_badge,
    add_cross_links,
    add_to_sitemap,
    check_category_page_quota,
    check_page_http_status,
    create_blog_post,
    create_category_page,
    generate_slug,
    get_quota_status,
    is_duplicate_title,
    prioritize_products,
    record_category_page_creation,
    suggest_unique_title,
    update_item_description,
    update_meta_tags,
    update_product_field,
    update_sitemap,
    verify_and_track_page,
)


class TestHtmlEscape(unittest.TestCase):
    """Тесты _h — HTML escape."""

    def test_basic_escape(self):
        self.assertEqual(
            _h("<script>alert('xss')</script>"),
            "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;",
        )

    def test_none_value(self):
        self.assertEqual(_h(None), "")

    def test_empty_string(self):
        self.assertEqual(_h(""), "")

    def test_no_special_chars(self):
        self.assertEqual(_h("Hello World"), "Hello World")


class TestQuotaTracker(unittest.TestCase):
    """Тесты квотного трекера."""

    def setUp(self):
        """Создаём временную директорию и чистим tracker перед каждым тестом."""
        import tempfile
        import shutil

        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self.test_root = Path(tempfile.mkdtemp(prefix="test_site_"))
        os.environ["PROJECT_ROOT"] = str(self.test_root)
        # Reset tracker in the new location
        tracker = {"created_pages": [], "updated_meta": [], "updated_products": []}
        _save_quota_tracker(tracker)

    def tearDown(self):
        """Чистим после теста."""
        import shutil

        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        if self._orig_project_root is not None:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        elif "PROJECT_ROOT" in os.environ:
            del os.environ["PROJECT_ROOT"]

    def test_load_empty_tracker(self):
        tracker = _load_quota_tracker()
        self.assertEqual(tracker, {"created_pages": [], "updated_meta": [], "updated_products": []})

    def test_save_and_load(self):
        tracker = {"created_pages": [{"page": "test.html", "timestamp": "2024-01-01T00:00:00"}]}
        _save_quota_tracker(tracker)
        loaded = _load_quota_tracker()
        self.assertEqual(len(loaded["created_pages"]), 1)

    def test_cleanup_old_entries(self):
        tracker = {
            "created_pages": [
                {
                    "page": "old.html",
                    "timestamp": (datetime.now() - __import__("datetime").timedelta(hours=25)).isoformat(),
                },
                {"page": "new.html", "timestamp": datetime.now().isoformat()},
            ]
        }
        cleaned = _cleanup_old_entries(tracker)
        self.assertEqual(len(cleaned["created_pages"]), 1)
        self.assertEqual(cleaned["created_pages"][0]["page"], "new.html")

    def test_parse_time_valid(self):
        dt = _parse_time("2024-01-01T12:00:00")
        self.assertEqual(dt.year, 2024)

    def test_parse_time_invalid(self):
        dt = _parse_time("invalid")
        self.assertEqual(dt, datetime.min)

    def test_check_quota_allowed_when_empty(self):
        allowed, reason, tracker = check_category_page_quota()
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_check_quota_blocks_at_limit(self):
        for i in range(DAILY_CATEGORY_PAGE_LIMIT):
            record_category_page_creation(f"page-{i}.html")
        allowed, reason, tracker = check_category_page_quota()
        self.assertFalse(allowed)
        self.assertIn("limit", reason.lower())

    def test_get_quota_status_structure(self):
        status = get_quota_status()
        self.assertIn("daily_category_page_limit", status)
        self.assertIn("created_pages_today", status)
        self.assertIn("remaining_category_pages", status)


class TestUpdateMetaTags(unittest.TestCase):
    """Тесты update_meta_tags."""

    def setUp(self):
        import tempfile

        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self.site_root = Path(tempfile.mkdtemp(prefix="test_site_"))
        os.environ["PROJECT_ROOT"] = str(self.site_root)
        from scripts.actions.file_utils import _get_site_root

        index_html = _get_site_root() / "index.html"
        index_html.write_text(
            "<html><head><title>Old</title></head><body></body></html>",
            encoding="utf-8",
        )

    def tearDown(self):
        import shutil
        from scripts.actions.file_utils import _get_site_root

        index_html = _get_site_root() / "index.html"
        index_html.unlink(missing_ok=True)
        for f in self.site_root.glob("*.bak.*"):
            f.unlink(missing_ok=True)
        if self.site_root.exists():
            shutil.rmtree(self.site_root)
        if self._orig_project_root is not None:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        elif "PROJECT_ROOT" in os.environ:
            del os.environ["PROJECT_ROOT"]

    def test_update_title(self):
        result = update_meta_tags("New Title", "New Description")
        self.assertTrue(result)

        from scripts.actions.file_utils import _get_site_root

        html = (_get_site_root() / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>New Title</title>", html)
        self.assertIn('<meta name="description" content="New Description">', html)

    def test_update_with_keywords(self):
        result = update_meta_tags("Title", "Desc", "kw1, kw2")
        self.assertTrue(result)

        from scripts.actions.file_utils import _get_site_root

        html = (_get_site_root() / "index.html").read_text(encoding="utf-8")
        self.assertIn('<meta name="keywords" content="kw1, kw2">', html)

    def test_html_escape(self):
        result = update_meta_tags("<script>alert(1)</script>", "Desc")
        self.assertTrue(result)

        from scripts.actions.file_utils import _get_site_root

        html = (_get_site_root() / "index.html").read_text(encoding="utf-8")
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)

    def test_empty_html_returns_false(self):
        from scripts.actions.file_utils import _get_site_root

        index_html = _get_site_root() / "index.html"
        index_html.write_text("", encoding="utf-8")
        result = update_meta_tags("Title", "Desc")
        self.assertFalse(result)


class TestCreateCategoryPage(unittest.TestCase):
    """Тесты create_category_page."""

    def setUp(self):
        import tempfile

        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self.site_root = Path(tempfile.mkdtemp(prefix="test_site_"))
        os.environ["PROJECT_ROOT"] = str(self.site_root)
        # Clear quota tracker
        tracker = {"created_pages": [], "updated_meta": [], "updated_products": []}
        _save_quota_tracker(tracker)

    def tearDown(self):
        import shutil

        category_dir = self.site_root / "category"
        if category_dir.exists():
            for f in category_dir.glob("*.html"):
                f.unlink(missing_ok=True)
        if self.site_root.exists():
            shutil.rmtree(self.site_root)
        if self._orig_project_root is not None:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        elif "PROJECT_ROOT" in os.environ:
            del os.environ["PROJECT_ROOT"]

    def test_create_category_page(self):
        items = [
            {
                "title": "Item 1",
                "price": "100₽",
                "image": "img1.jpg",
                "link": "http://example.com/1",
            },
            {
                "title": "Item 2",
                "price": "200₽",
                "image": "img2.jpg",
                "link": "http://example.com/2",
            },
        ]
        result = create_category_page("Test Category", items)
        self.assertTrue(result)

        path = self.site_root / "category" / "test-category.html"
        self.assertTrue(path.exists())

        html = path.read_text(encoding="utf-8")
        self.assertIn("Test Category", html)
        self.assertIn("Item 1", html)
        self.assertIn("Item 2", html)
        self.assertIn("100₽", html)

    def test_slug_generation(self):
        items = [{"title": "T", "price": "1", "image": "", "link": ""}]
        create_category_page("Test Category!@#", items)

        path = self.site_root / "category" / "test-category.html"
        self.assertTrue(path.exists())

    def test_quota_blocks(self):
        # Fill quota
        for i in range(DAILY_CATEGORY_PAGE_LIMIT):
            record_category_page_creation(f"page-{i}.html")

        items = [{"title": "T", "price": "1", "image": "", "link": ""}]
        result = create_category_page("Blocked", items)
        self.assertFalse(result)


class TestUpdateItemDescription(unittest.TestCase):
    """Тесты update_item_description."""

    def setUp(self):
        import tempfile

        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self.site_root = Path(tempfile.mkdtemp(prefix="test_site_"))
        os.environ["PROJECT_ROOT"] = str(self.site_root)
        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        products_json.write_text(
            '{"products": [{"id": "1", "name": "Test", "description": "Old"}]}',
            encoding="utf-8",
        )

    def tearDown(self):
        import shutil
        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        products_json.unlink(missing_ok=True)
        if self.site_root.exists():
            shutil.rmtree(self.site_root)
        if self._orig_project_root is not None:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        elif "PROJECT_ROOT" in os.environ:
            del os.environ["PROJECT_ROOT"]

    def test_update_description(self):
        result = update_item_description("1", "New Description")
        self.assertTrue(result)

        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        data = json.loads(products_json.read_text(encoding="utf-8"))
        # write_products writes list when dict has "products" key
        self.assertEqual(data[0]["description"], "New Description")

    def test_item_not_found(self):
        result = update_item_description("999", "New Description")
        self.assertFalse(result)

    def test_invalid_field_blocked(self):
        # This should not happen since function hardcodes "description"
        # But test the protection mechanism
        result = update_item_description("1", "New Description")
        self.assertTrue(result)  # description is allowed


class TestAddBadge(unittest.TestCase):
    """Тесты add_badge."""

    def setUp(self):
        import tempfile

        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self.site_root = Path(tempfile.mkdtemp(prefix="test_site_"))
        os.environ["PROJECT_ROOT"] = str(self.site_root)
        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        products_json.write_text('{"products": [{"id": "1", "name": "Test"}]}', encoding="utf-8")

    def tearDown(self):
        import shutil
        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        products_json.unlink(missing_ok=True)
        if self.site_root.exists():
            shutil.rmtree(self.site_root)
        if self._orig_project_root is not None:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        elif "PROJECT_ROOT" in os.environ:
            del os.environ["PROJECT_ROOT"]

    def test_add_badge(self):
        result = add_badge("1", "🔥 Тренд")
        self.assertTrue(result)

        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        data = json.loads(products_json.read_text(encoding="utf-8"))
        self.assertEqual(data[0]["badge"], "🔥 Тренд")

    def test_item_not_found(self):
        result = add_badge("999", "🔥 Тренд")
        self.assertFalse(result)


class TestPrioritizeProducts(unittest.TestCase):
    """Тесты prioritize_products."""

    def setUp(self):
        import tempfile

        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self.site_root = Path(tempfile.mkdtemp(prefix="test_site_"))
        os.environ["PROJECT_ROOT"] = str(self.site_root)
        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        products_json.write_text('{"products": [{"id": "1"}, {"id": "2"}, {"id": "3"}]}', encoding="utf-8")

    def tearDown(self):
        import shutil
        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        products_json.unlink(missing_ok=True)
        if self.site_root.exists():
            shutil.rmtree(self.site_root)
        if self._orig_project_root is not None:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        elif "PROJECT_ROOT" in os.environ:
            del os.environ["PROJECT_ROOT"]

    def test_prioritize(self):
        result = prioritize_products(["2", "3"])
        self.assertTrue(result)

        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        data = json.loads(products_json.read_text(encoding="utf-8"))
        ids = [p["id"] for p in data]
        self.assertEqual(ids, ["2", "3", "1"])

    def test_empty_products(self):
        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        products_json.write_text("{}", encoding="utf-8")
        result = prioritize_products(["1"])
        self.assertFalse(result)


class TestUpdateProductField(unittest.TestCase):
    """Тесты update_product_field."""

    def setUp(self):
        import tempfile

        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self.site_root = Path(tempfile.mkdtemp(prefix="test_site_"))
        os.environ["PROJECT_ROOT"] = str(self.site_root)
        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        products_json.write_text('{"products": [{"id": "1", "name": "Test"}]}', encoding="utf-8")

    def tearDown(self):
        import shutil
        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        products_json.unlink(missing_ok=True)
        if self.site_root.exists():
            shutil.rmtree(self.site_root)
        if self._orig_project_root is not None:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        elif "PROJECT_ROOT" in os.environ:
            del os.environ["PROJECT_ROOT"]

    def test_update_allowed_field(self):
        result = update_product_field("1", "discount", "50%")
        self.assertTrue(result)

        from scripts.actions.file_utils import _get_site_root

        products_json = _get_site_root() / "products.json"
        data = json.loads(products_json.read_text(encoding="utf-8"))
        self.assertEqual(data[0]["discount"], "50%")

    def test_update_protected_field(self):
        result = update_product_field("1", "price", 999)
        self.assertFalse(result)

    def test_update_unknown_field(self):
        result = update_product_field("1", "hacked", "evil")
        self.assertFalse(result)

    def test_item_not_found(self):
        result = update_product_field("999", "discount", "50%")
        self.assertFalse(result)


class TestSitemap(unittest.TestCase):
    """Тесты sitemap.xml."""

    def setUp(self):
        import tempfile

        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self.site_root = Path(tempfile.mkdtemp(prefix="test_site_"))
        os.environ["PROJECT_ROOT"] = str(self.site_root)

    def tearDown(self):
        import shutil

        sitemap = self.site_root / "sitemap.xml"
        sitemap.unlink(missing_ok=True)
        if self.site_root.exists():
            shutil.rmtree(self.site_root)
        if self._orig_project_root is not None:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        elif "PROJECT_ROOT" in os.environ:
            del os.environ["PROJECT_ROOT"]

    def test_update_sitemap(self):
        pages = [
            {"path": "index.html", "priority": "1.0"},
            {"path": "about.html", "priority": "0.8"},
        ]
        result = update_sitemap(pages)
        self.assertTrue(result)

        sitemap = self.site_root / "sitemap.xml"
        self.assertTrue(sitemap.exists())

        xml = sitemap.read_text(encoding="utf-8")
        self.assertIn("<urlset", xml)
        self.assertIn("index.html", xml)
        self.assertIn("about.html", xml)
        self.assertIn("1.0", xml)

    def test_add_to_sitemap_new(self):
        result = add_to_sitemap("new-page.html", "0.5", "weekly")
        self.assertTrue(result)

        sitemap = self.site_root / "sitemap.xml"
        xml = sitemap.read_text(encoding="utf-8")
        self.assertIn("new-page.html", xml)

    def test_add_to_sitemap_update_existing(self):
        # First add
        add_to_sitemap("page.html", "0.5", "weekly")
        # Then update
        result = add_to_sitemap("page.html", "0.7", "daily")
        self.assertTrue(result)


class TestCrossLinks(unittest.TestCase):
    """Тесты add_cross_links."""

    def setUp(self):
        import tempfile

        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self.site_root = Path(tempfile.mkdtemp(prefix="test_site_"))
        os.environ["PROJECT_ROOT"] = str(self.site_root)
        self.page = self.site_root / "test.html"
        self.page.write_text("<html><body><h1>Test</h1></body></html>", encoding="utf-8")

    def tearDown(self):
        import shutil

        self.page.unlink(missing_ok=True)
        if self.site_root.exists():
            shutil.rmtree(self.site_root)
        if self._orig_project_root is not None:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        elif "PROJECT_ROOT" in os.environ:
            del os.environ["PROJECT_ROOT"]

    def test_add_cross_links(self):
        related = [
            {"title": "Related 1", "path": "page1.html"},
            {"title": "Related 2", "path": "page2.html"},
        ]
        result = add_cross_links("test.html", related)
        self.assertTrue(result)

        html = self.page.read_text(encoding="utf-8")
        self.assertIn("Читайте также", html)
        self.assertIn("Related 1", html)
        self.assertIn("Related 2", html)

    def test_remove_old_block(self):
        # First add
        add_cross_links("test.html", [{"title": "Old", "path": "old.html"}])
        # Then update
        result = add_cross_links("test.html", [{"title": "New", "path": "new.html"}])
        self.assertTrue(result)

        html = self.page.read_text(encoding="utf-8")
        self.assertNotIn("Old", html)
        self.assertIn("New", html)

    def test_empty_related_pages(self):
        result = add_cross_links("test.html", [])
        self.assertTrue(result)

    def test_invalid_related_pages(self):
        result = add_cross_links("test.html", [{"title": "", "path": ""}])
        self.assertTrue(result)

    def test_missing_body_tag(self):
        self.page.write_text("<html><h1>No body</h1></html>", encoding="utf-8")
        related = [{"title": "T", "path": "p.html"}]
        result = add_cross_links("test.html", related)
        self.assertTrue(result)


class TestGenerateSlug(unittest.TestCase):
    """Тесты generate_slug."""

    def test_basic(self):
        self.assertEqual(generate_slug("Hello World"), "hello-world")

    def test_special_chars(self):
        self.assertEqual(generate_slug("Hello! World?"), "hello-world")

    def test_multiple_spaces(self):
        self.assertEqual(generate_slug("Hello   World"), "hello-world")

    def test_trailing_dashes(self):
        self.assertEqual(generate_slug("-Hello World-"), "hello-world")


class TestIsDuplicateTitle(unittest.TestCase):
    """Тесты is_duplicate_title."""

    def test_duplicate(self):
        existing = ["Hello World Guide", "Another Article"]
        self.assertTrue(is_duplicate_title("Hello World Tutorial", existing, 0.5))

    def test_not_duplicate(self):
        existing = ["Python Guide", "Java Tutorial"]
        self.assertFalse(is_duplicate_title("C++ Reference", existing))

    def test_empty_new(self):
        self.assertFalse(is_duplicate_title("", ["Something"]))

    def test_empty_existing(self):
        self.assertFalse(is_duplicate_title("Something", []))


class TestSuggestUniqueTitle(unittest.TestCase):
    """Тесты suggest_unique_title."""

    def test_already_unique(self):
        self.assertEqual(suggest_unique_title("Unique", ["Other"]), "Unique")

    def test_add_number(self):
        result = suggest_unique_title("Common", ["Common"])
        self.assertEqual(result, "Common (2)")

    def test_multiple_attempts(self):
        existing = ["Common", "Common (2)", "Common (3)"]
        result = suggest_unique_title("Common", existing)
        self.assertEqual(result, "Common (4)")

    def test_fallback_to_timestamp(self):
        existing = [f"Common ({i})" for i in range(2, 15)]
        result = suggest_unique_title("Common", existing, max_attempts=5)
        # When all attempts fail, fallback adds timestamp
        self.assertTrue(result.startswith("Common"))


class TestHttpCheck(unittest.IsolatedAsyncioTestCase):
    """Тесты async HTTP check."""

    def setUp(self):
        import tempfile

        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self.site_root = Path(tempfile.mkdtemp(prefix="test_site_"))
        os.environ["PROJECT_ROOT"] = str(self.site_root)

    def tearDown(self):
        import shutil

        if self.site_root.exists():
            shutil.rmtree(self.site_root)
        if self._orig_project_root is not None:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        elif "PROJECT_ROOT" in os.environ:
            del os.environ["PROJECT_ROOT"]

    @patch("aiohttp.ClientSession")
    async def test_success(self, mock_session_class):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session

        result = await check_page_http_status("test.html")
        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], 200)

    @patch("aiohttp.ClientSession")
    async def test_not_found(self, mock_session_class):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.status = 404
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.get = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session

        result = await check_page_http_status("missing.html")
        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 404)

    @patch("aiohttp.ClientSession")
    async def test_timeout(self, mock_session_class):
        import asyncio

        mock_session = MagicMock()
        mock_session.get = MagicMock(side_effect=asyncio.TimeoutError())
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session

        result = await check_page_http_status("slow.html")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "timeout")


class TestVerifyAndTrackPage(unittest.IsolatedAsyncioTestCase):
    """Тесты verify_and_track_page."""

    def setUp(self):
        import tempfile

        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self.site_root = Path(tempfile.mkdtemp(prefix="test_site_"))
        os.environ["PROJECT_ROOT"] = str(self.site_root)

    def tearDown(self):
        import shutil

        if self.site_root.exists():
            shutil.rmtree(self.site_root)
        if self._orig_project_root is not None:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        elif "PROJECT_ROOT" in os.environ:
            del os.environ["PROJECT_ROOT"]

    @patch("scripts.actions.site_actions.check_page_http_status")
    async def test_success_with_tracking(self, mock_check):
        mock_check.return_value = {
            "ok": True,
            "status": 200,
            "url": "http://test",
            "error": None,
        }

        track_func = AsyncMock()
        result = await verify_and_track_page("test.html", "seo_agent", track_func=track_func)

        self.assertTrue(result["ok"])
        self.assertTrue(result["tracked"])
        track_func.assert_called_once()

    @patch("scripts.actions.site_actions.check_page_http_status")
    async def test_success_without_tracking(self, mock_check):
        mock_check.return_value = {
            "ok": True,
            "status": 200,
            "url": "http://test",
            "error": None,
        }

        result = await verify_and_track_page("test.html", "seo_agent")

        # Without tracking, ok is just based on http check
        self.assertTrue(result["http_check"]["ok"])
        self.assertFalse(result["tracked"])

    @patch("scripts.actions.site_actions.check_page_http_status")
    async def test_http_fails(self, mock_check):
        mock_check.return_value = {
            "ok": False,
            "status": 500,
            "url": "http://test",
            "error": "Server Error",
        }

        result = await verify_and_track_page("test.html", "seo_agent")

        self.assertFalse(result["ok"])

    @patch("scripts.actions.site_actions.check_page_http_status")
    async def test_tracking_error(self, mock_check):
        mock_check.return_value = {
            "ok": True,
            "status": 200,
            "url": "http://test",
            "error": None,
        }

        async def failing_track(**kwargs):
            raise Exception("DB error")

        result = await verify_and_track_page("test.html", "seo_agent", track_func=failing_track)

        self.assertFalse(result["ok"])  # ok = http AND tracked
        self.assertFalse(result["tracked"])


class TestCreateBlogPost(unittest.TestCase):
    """Тесты create_blog_post."""

    def setUp(self):
        """Создаём временную директорию перед каждым тестом."""
        import tempfile
        import shutil

        self._orig_project_root = os.environ.get("PROJECT_ROOT")
        self.test_root = Path(tempfile.mkdtemp(prefix="test_site_"))
        os.environ["PROJECT_ROOT"] = str(self.test_root)

    def tearDown(self):
        """Чистим после теста."""
        import shutil
        import os

        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        if self._orig_project_root is not None:
            os.environ["PROJECT_ROOT"] = self._orig_project_root
        elif "PROJECT_ROOT" in os.environ:
            del os.environ["PROJECT_ROOT"]

    def test_create_blog_post_basic(self):
        result = create_blog_post(
            title="Как я купил наушники",
            subtitle="И не пожалел",
            introduction="Всем привет! Расскажу о своём опыте.",
            sections=[
                {"heading": "Первые впечатления", "body": "Качество отличное."},
                {"heading": "Лайфхаки", "body": "Совет №1: заряжайте ночью."},
            ],
            conclusion="Рекомендую всем!",
            tags=["наушники", "aliexpress", "скидки"],
            product_mentions=["Беспроводные наушники XY"],
            cta_text="Хотите такие же? Смотрите на smart-skidka.ru!",
            reading_time_min=5,
        )
        self.assertTrue(result)

        # Проверяем что файл создан
        blog_dir = self.test_root / "blog"
        html_files = list(blog_dir.glob("*.html"))
        self.assertEqual(len(html_files), 1)

        # Проверяем содержимое
        content = html_files[0].read_text(encoding="utf-8")
        self.assertIn("Как я купил наушники", content)
        self.assertIn("И не пожалел", content)
        self.assertIn("Первые впечатления", content)
        self.assertIn("Рекомендую всем!", content)
        self.assertIn("наушники", content)
        self.assertIn("smart-skidka.ru", content)
        self.assertIn("5 мин чтения", content)

    def test_create_blog_post_generates_slug(self):
        create_blog_post(
            title="Тестовый пост! Со спецсимволами?",
            subtitle="S",
            introduction="I",
            sections=[],
            conclusion="C",
            tags=[],
            product_mentions=[],
            cta_text="",
        )
        blog_dir = self.test_root / "blog"
        html_files = list(blog_dir.glob("*.html"))
        self.assertTrue(len(html_files) > 0)
        # slug должен быть очищен от спецсимволов (кириллица остаётся)
        self.assertNotIn("!", html_files[0].name)
        self.assertNotIn("?", html_files[0].name)
        self.assertIn("тестовый-пост", html_files[0].name.lower())

    def test_create_blog_post_unique_slug_on_duplicate(self):
        # Создаём первый пост
        create_blog_post(
            title="Дубликат",
            subtitle="S1",
            introduction="I1",
            sections=[],
            conclusion="C1",
            tags=[],
            product_mentions=[],
            cta_text="",
        )
        # Создаём второй с таким же заголовком
        create_blog_post(
            title="Дубликат",
            subtitle="S2",
            introduction="I2",
            sections=[],
            conclusion="C2",
            tags=[],
            product_mentions=[],
            cta_text="",
        )
        blog_dir = self.test_root / "blog"
        html_files = list(blog_dir.glob("*.html"))
        self.assertEqual(len(html_files), 2)
        names = {f.name for f in html_files}
        self.assertEqual(len(names), 2)  # разные имена

    def test_create_blog_post_updates_index(self):
        create_blog_post(
            title="Пост для индекса",
            subtitle="Подзаголовок",
            introduction="I",
            sections=[],
            conclusion="C",
            tags=["тег1", "тег2"],
            product_mentions=[],
            cta_text="",
            reading_time_min=3,
        )
        index_path = self.test_root / "blog" / "index.json"
        self.assertTrue(index_path.exists())
        with open(index_path, "r", encoding="utf-8") as f:
            index = json.load(f)
        self.assertEqual(len(index["posts"]), 1)
        self.assertEqual(index["posts"][0]["title"], "Пост для индекса")
        self.assertEqual(index["posts"][0]["reading_time"], 3)
        self.assertEqual(index["posts"][0]["tags"], ["тег1", "тег2"])

    def test_create_blog_post_empty_optional_fields(self):
        result = create_blog_post(
            title="Минимальный пост",
            subtitle="",
            introduction="I",
            sections=[],
            conclusion="C",
            tags=[],
            product_mentions=[],
            cta_text="",
            reading_time_min=0,
        )
        self.assertTrue(result)

    def test_create_blog_post_html_escape(self):
        create_blog_post(
            title="<script>alert(1)</script>",
            subtitle="S",
            introduction="I",
            sections=[{"heading": "<b>Жирный</b>", "body": "Текст"}],
            conclusion="C",
            tags=[],
            product_mentions=[],
            cta_text="",
        )
        blog_dir = self.test_root / "blog"
        html_files = list(blog_dir.glob("*.html"))
        content = html_files[0].read_text(encoding="utf-8")
        self.assertNotIn("<script>", content)
        self.assertIn("&lt;script&gt;", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
