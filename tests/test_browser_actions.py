#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для browser-based агента (P1-8).
"""

import asyncio
import sys
import unittest

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

from scripts.actions.browser_actions import (
    BrowserManager,
    CompetitorData,
    PageMetrics,
    batch_check_competitors,
    batch_check_pages,
    check_competitor,
    check_page_render,
    close_browser,
    measure_core_vitals,
    screenshot_product,
)


class TestBrowserActions(unittest.TestCase):
    """Тесты browser-based агента."""

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        # Close browser after each test
        try:
            self.loop.run_until_complete(close_browser())
        except Exception:
            pass
        self.loop.close()

    def test_check_page_render(self):
        """Проверка рендеринга страницы возвращает метрики."""
        metrics = self.loop.run_until_complete(check_page_render("https://example.com", take_screenshot=False))
        self.assertIsInstance(metrics, PageMetrics)
        self.assertEqual(metrics.url, "https://example.com")
        self.assertEqual(metrics.status, 200)
        self.assertEqual(metrics.title, "Example Domain")
        self.assertGreater(metrics.load_time_ms, 0)
        self.assertIn("h1", metrics.headings)

    def test_page_render_to_dict(self):
        """PageMetrics.to_dict() возвращает корректную структуру."""
        metrics = self.loop.run_until_complete(check_page_render("https://example.com", take_screenshot=False))
        d = metrics.to_dict()
        self.assertIn("url", d)
        self.assertIn("load_time_ms", d)
        self.assertIn("meta_tags", d)
        self.assertIn("headings", d)
        self.assertIn("timestamp", d)

    def test_measure_core_vitals(self):
        """Core Web Vitals возвращает оценки."""
        vitals = self.loop.run_until_complete(measure_core_vitals("https://example.com"))
        self.assertIn("lcp_ms", vitals)
        self.assertIn("lcp_rating", vitals)
        self.assertIn("cls_score", vitals)
        self.assertIn("cls_rating", vitals)
        self.assertIn("overall_rating", vitals)
        self.assertIn("recommendations", vitals)
        self.assertIn(vitals["overall_rating"], ["good", "needs_improvement", "poor"])

    def test_screenshot_product(self):
        """Скриншот сохраняется и путь возвращается."""
        import os

        path = self.loop.run_until_complete(screenshot_product("https://example.com", full_page=True))
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith(".png"))
        os.remove(path)

    def test_check_competitor(self):
        """Проверка конкурента возвращает данные."""
        data = self.loop.run_until_complete(check_competitor("https://example.com", timeout=8000))
        self.assertIsInstance(data, CompetitorData)
        self.assertEqual(data.url, "https://example.com")
        self.assertIsNotNone(data.meta_title)

    def test_competitor_to_dict(self):
        """CompetitorData.to_dict() возвращает корректную структуру."""
        data = self.loop.run_until_complete(check_competitor("https://example.com", timeout=8000))
        d = data.to_dict()
        self.assertIn("url", d)
        self.assertIn("product_name", d)
        self.assertIn("price", d)
        self.assertIn("timestamp", d)

    def test_batch_check_pages(self):
        """Пакетная проверка страниц работает."""
        urls = ["https://example.com"]
        results = self.loop.run_until_complete(batch_check_pages(urls, take_screenshots=False, max_concurrent=1))
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], PageMetrics)
        self.assertEqual(results[0].status, 200)

    def test_batch_check_competitors(self):
        """Пакетная проверка конкурентов работает."""
        urls = ["https://example.com"]
        results = self.loop.run_until_complete(batch_check_competitors(urls, max_concurrent=1))
        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], CompetitorData)

    def test_browser_manager_singleton(self):
        """BrowserManager — singleton."""
        m1 = BrowserManager()
        m2 = BrowserManager()
        self.assertIs(m1, m2)

    def test_error_handling_bad_url(self):
        """Невалидный URL обрабатывается без краша."""
        metrics = self.loop.run_until_complete(
            check_page_render("https://this-domain-does-not-exist-12345.xyz", timeout=5000)
        )
        self.assertIsInstance(metrics, PageMetrics)
        # Should have error in meta_tags or status 0
        self.assertTrue(metrics.status == 0 or "error" in metrics.meta_tags)


if __name__ == "__main__":
    unittest.main(verbosity=2)
