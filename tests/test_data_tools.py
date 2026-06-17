#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для data_tools.py — реальных инструментов сбора данных.
"""

import sys
import unittest

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

from scripts.actions.data_tools import (
    close_session,
    forum_scanner,
    gather_trend_data,
    google_trends,
    marketplace_trends,
    news_monitor,
    yandex_wordstat,
)


class TestGoogleTrends(unittest.IsolatedAsyncioTestCase):
    """Тесты Google Trends RSS."""

    async def asyncTearDown(self):
        await close_session()

    async def test_google_trends_returns_structure(self):
        """google_trends возвращает корректную структуру."""
        result = await google_trends(region="RU", limit=3)
        self.assertIn("success", result)
        self.assertIn("trends", result)
        self.assertIsInstance(result["trends"], list)

    async def test_google_trends_has_titles(self):
        """Тренды содержат заголовки."""
        result = await google_trends(region="RU", limit=3)
        if result["success"]:
            for trend in result["trends"]:
                self.assertIn("title", trend)
                self.assertIsInstance(trend["title"], str)


class TestNewsMonitor(unittest.IsolatedAsyncioTestCase):
    """Тесты RSS-агрегатора новостей."""

    async def asyncTearDown(self):
        await close_session()

    async def test_news_monitor_vc_ru(self):
        """news_monitor собирает новости с VC.ru."""
        result = await news_monitor(sources=["vc_ru"], keywords=[], hours=168, limit=5)
        self.assertTrue(result["success"])
        self.assertGreaterEqual(result["total_found"], 0)
        self.assertIsInstance(result["articles"], list)

    async def test_news_monitor_with_keywords(self):
        """Фильтрация по ключевым словам работает."""
        result = await news_monitor(
            sources=["vc_ru"],
            keywords=["технологии", "бизнес"],
            hours=168,
            limit=10,
        )
        self.assertTrue(result["success"])
        # Не гарантируем совпадение, но проверяем структуру
        for article in result["articles"]:
            self.assertIn("title", article)
            self.assertIn("source", article)


class TestYandexWordstat(unittest.IsolatedAsyncioTestCase):
    """Тесты Яндекс подсказок."""

    async def asyncTearDown(self):
        await close_session()

    async def test_yandex_wordstat_returns_suggestions(self):
        """yandex_wordstat возвращает подсказки."""
        result = await yandex_wordstat("скидки", limit=5)
        self.assertTrue(result["success"])
        self.assertIsInstance(result["suggestions"], list)

    async def test_yandex_wordstat_suggestions_have_text(self):
        """Подсказки содержат текст."""
        result = await yandex_wordstat("промокоды", limit=3)
        if result["count"] > 0:
            for sugg in result["suggestions"]:
                self.assertIn("text", sugg)
                self.assertIsInstance(sugg["text"], str)
                self.assertGreater(len(sugg["text"]), 0)


class TestForumScanner(unittest.IsolatedAsyncioTestCase):
    """Тесты сканера форумов."""

    async def asyncTearDown(self):
        await close_session()

    async def test_forum_scanner_hackernews(self):
        """forum_scanner работает с HackerNews."""
        result = await forum_scanner(source="hackernews", limit=5)
        self.assertTrue(result["success"])
        self.assertIsInstance(result["posts"], list)
        self.assertEqual(result["source"], "hackernews")

    async def test_forum_scanner_posts_structure(self):
        """Посты имеют правильную структуру."""
        result = await forum_scanner(source="hackernews", limit=3)
        if result["count"] > 0:
            for post in result["posts"]:
                self.assertIn("title", post)
                self.assertIn("url", post)
                self.assertIn("score", post)


class TestMarketplaceTrends(unittest.IsolatedAsyncioTestCase):
    """Тесты скрейпинга маркетплейсов."""

    async def asyncTearDown(self):
        await close_session()

    async def test_marketplace_trends_wildberries(self):
        """marketplace_trends возвращает структуру для WB."""
        result = await marketplace_trends(marketplace="wildberries", category="наушники", limit=3)
        # Может вернуть 429, проверяем структуру в любом случае
        self.assertIn("success", result)
        self.assertIn("products", result)

    async def test_marketplace_unsupported(self):
        """Неподдерживаемый маркетплейс возвращает ошибку."""
        result = await marketplace_trends(marketplace="ozon", limit=3)
        self.assertFalse(result["success"])
        self.assertIn("not supported", result["error"].lower())


class TestGatherTrendData(unittest.IsolatedAsyncioTestCase):
    """Тесты комплексного сбора трендов."""

    async def asyncTearDown(self):
        await close_session()

    async def test_gather_trend_data_structure(self):
        """gather_trend_data возвращает объединённую структуру."""
        result = await gather_trend_data(keywords=[""], news_hours=168, limit=2)
        self.assertTrue(result["success"])
        self.assertIn("sources", result)
        self.assertIn("combined_insights", result)
        self.assertIsInstance(result["combined_insights"], list)

    async def test_gather_trend_data_sources(self):
        """Результат содержит данные из источников."""
        result = await gather_trend_data(keywords=[""], news_hours=168, limit=2)
        sources = result["sources"]
        self.assertIn("google_trends", sources)
        self.assertIn("news", sources)
        self.assertIn("marketplace", sources)
        self.assertIn("forum", sources)


if __name__ == "__main__":
    unittest.main(verbosity=2)
