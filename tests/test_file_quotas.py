#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для квот на создание файлов (P2-9).
"""

import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

from scripts.actions.site_actions import (
    DAILY_CATEGORY_PAGE_LIMIT,
    _cleanup_old_entries,
    _load_quota_tracker,
    _save_quota_tracker,
    check_category_page_quota,
    get_quota_status,
    record_category_page_creation,
)


class TestFileQuotas(unittest.TestCase):
    """Тесты квот на создание файлов."""

    def setUp(self):
        """Чистим tracker перед каждым тестом."""
        tracker = {"created_pages": [], "updated_meta": [], "updated_products": []}
        _save_quota_tracker(tracker)

    def test_quota_allowed_when_empty(self):
        """Создание разрешено когда квота пустая."""
        allowed, reason, tracker = check_category_page_quota()
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_quota_blocks_when_limit_reached(self):
        """Создание блокируется при превышении лимита."""
        # Заполняем квоту
        for i in range(DAILY_CATEGORY_PAGE_LIMIT):
            record_category_page_creation(f"page-{i}.html")

        allowed, reason, tracker = check_category_page_quota()
        self.assertFalse(allowed)
        self.assertIn("limit reached", reason.lower())

    def test_record_creation_updates_tracker(self):
        """Запись создания обновляет tracker."""
        result = record_category_page_creation("test-category.html")
        self.assertTrue(result)

        tracker = _load_quota_tracker()
        self.assertEqual(len(tracker["created_pages"]), 1)
        self.assertEqual(tracker["created_pages"][0]["page"], "test-category.html")

    def test_cleanup_old_entries(self):
        """Старые записи (>24ч) удаляются."""
        tracker = {
            "created_pages": [
                {
                    "page": "old.html",
                    "timestamp": (datetime.now() - timedelta(hours=25)).isoformat(),
                },
                {"page": "new.html", "timestamp": datetime.now().isoformat()},
            ]
        }
        cleaned = _cleanup_old_entries(tracker)
        self.assertEqual(len(cleaned["created_pages"]), 1)
        self.assertEqual(cleaned["created_pages"][0]["page"], "new.html")

    def test_quota_status_structure(self):
        """get_quota_status возвращает корректную структуру."""
        status = get_quota_status()
        self.assertIn("daily_category_page_limit", status)
        self.assertIn("created_pages_today", status)
        self.assertIn("remaining_category_pages", status)
        self.assertEqual(status["daily_category_page_limit"], DAILY_CATEGORY_PAGE_LIMIT)

    def test_remaining_pages_calculated_correctly(self):
        """Оставшиеся страницы считаются правильно."""
        for i in range(3):
            record_category_page_creation(f"page-{i}.html")

        status = get_quota_status()
        self.assertEqual(status["created_pages_today"], 3)
        self.assertEqual(status["remaining_category_pages"], DAILY_CATEGORY_PAGE_LIMIT - 3)

    def test_quota_resets_after_24h(self):
        """Квота сбрасывается после 24 часов."""
        # Создаём старую запись
        tracker = {
            "created_pages": [
                {
                    "page": "old.html",
                    "timestamp": (datetime.now() - timedelta(hours=25)).isoformat(),
                },
            ]
        }
        _save_quota_tracker(tracker)

        # Проверяем — должно быть разрешено
        allowed, reason, _ = check_category_page_quota()
        self.assertTrue(allowed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
