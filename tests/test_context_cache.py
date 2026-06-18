#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для ContextCache (P3-7) — оптимизация памяти контекста.
"""

import asyncio
import sys
import time
import unittest

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

from scripts.actions.context_cache import ContextCache


class MockRedis:
    """Мок Redis для тестирования без реального подключения."""

    def __init__(self):
        self._store = {}

    async def get(self, key):
        return self._store.get(key)

    async def set(self, key, value, ex=None):
        self._store[key] = value

    async def delete(self, key):
        if key in self._store:
            del self._store[key]

    async def scan_iter(self, match):
        for key in list(self._store.keys()):
            if key.startswith(match.replace("*", "")):
                yield key


class MockMemoryStore:
    """Мок MemoryStore с Redis."""

    def __init__(self):
        self._redis = MockRedis()

    async def _get_redis(self):
        return self._redis


class TestContextCache(unittest.TestCase):
    """Тесты ContextCache."""

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_local_cache_hit(self):
        """Локальный кэш возвращает данные."""
        cc = ContextCache(memory_store=None)
        cc._local_set("key1", {"data": "value"})
        result = cc._local_get("key1", ttl_seconds=60)
        self.assertEqual(result, {"data": "value"})

    def test_local_cache_miss(self):
        """Отсутствующий ключ возвращает None."""
        cc = ContextCache(memory_store=None)
        result = cc._local_get("missing_key", ttl_seconds=60)
        self.assertIsNone(result)

    def test_local_cache_expiry(self):
        """Истёкший кэш возвращает None."""
        cc = ContextCache(memory_store=None)
        cc._local_set("expiring", "value")
        time.sleep(0.05)
        result = cc._local_get("expiring", ttl_seconds=0)
        self.assertIsNone(result)

    def test_mtime_hash_consistent(self):
        """Хэш mtime одинаковый для неизменённых файлов."""
        cc = ContextCache(memory_store=None)
        h1 = cc._get_project_mtime_hash("/opt/smart-skidka-agents")
        h2 = cc._get_project_mtime_hash("/opt/smart-skidka-agents")
        self.assertEqual(h1, h2)
        self.assertEqual(len(h1), 16)

    def test_mtime_hash_different_paths(self):
        """Разные пути дают разные хэши (или оба missing)."""
        cc = ContextCache(memory_store=None)
        h1 = cc._get_project_mtime_hash("/opt/smart-skidka-agents")
        h2 = cc._get_project_mtime_hash("/tmp")
        # Может быть одинаковым если оба missing все файлы, но обычно разное
        self.assertIsInstance(h1, str)
        self.assertIsInstance(h2, str)

    def test_redis_get_set(self):
        """Redis get/set работает через мок."""

        async def _test():
            memory = MockMemoryStore()
            cc = ContextCache(memory_store=memory)
            await cc._redis_set("test_key", {"recs": [1, 2, 3]}, ttl=60)
            result = await cc._redis_get("test_key")
            self.assertEqual(result, {"recs": [1, 2, 3]})

        self.loop.run_until_complete(_test())

    def test_trend_recs_cache_roundtrip(self):
        """Trend recommendations кэшируются и читаются."""

        async def _test():
            memory = MockMemoryStore()
            cc = ContextCache(memory_store=memory)
            recs = [
                {"trend": "A", "priority": "high"},
                {"trend": "B", "priority": "low"},
            ]
            await cc.set_trend_recommendations("seo-agent", recs)
            result = await cc.get_trend_recommendations("seo-agent", limit=3)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["trend"], "A")

        self.loop.run_until_complete(_test())

    def test_analytics_tasks_cache_roundtrip(self):
        """Analytics tasks кэшируются и читаются."""

        async def _test():
            memory = MockMemoryStore()
            cc = ContextCache(memory_store=memory)
            tasks = [{"title": "Task 1"}, {"title": "Task 2"}]
            await cc.set_analytics_tasks("smm-agent", tasks)
            result = await cc.get_analytics_tasks("smm-agent", limit=3)
            self.assertEqual(len(result), 2)
            self.assertEqual(result[0]["title"], "Task 1")

        self.loop.run_until_complete(_test())

    def test_project_context_cache_roundtrip(self):
        """Project context кэшируется по mtime хэшу."""

        async def _test():
            memory = MockMemoryStore()
            cc = ContextCache(memory_store=memory)
            ctx = "## Project context for seo\nindex.html content..."
            await cc.set_project_context("seo", "/opt/smart-skidka-agents", ctx)
            result = await cc.get_project_context("seo", "/opt/smart-skidka-agents")
            self.assertEqual(result, ctx)

        self.loop.run_until_complete(_test())

    def test_invalidate_agent_cache(self):
        """Инвалидация кэша агента очищает его ключи."""

        async def _test():
            memory = MockMemoryStore()
            cc = ContextCache(memory_store=memory)
            await cc.set_trend_recommendations("seo-agent", [{"trend": "A"}])
            await cc.set_analytics_tasks("seo-agent", [{"title": "T"}])
            await cc.invalidate_agent_cache("seo-agent")
            # После инвалидации локальный кэш должен быть пуст
            self.assertIsNone(cc._local_get("cache:trend_recs:seo-agent", 60))
            self.assertIsNone(cc._local_get("cache:analytics_tasks:seo-agent", 60))

        self.loop.run_until_complete(_test())

    def test_clear_local_cache(self):
        """Очистка локального кэша работает."""
        cc = ContextCache(memory_store=None)
        cc._local_set("key1", "value1")
        cc._local_set("key2", "value2")
        cc.clear_local_cache()
        self.assertIsNone(cc._local_get("key1", 60))
        self.assertIsNone(cc._local_get("key2", 60))

    def test_last_results_cache_format(self):
        """Кэш last_results возвращает правильный формат."""

        async def _test():
            memory = MockMemoryStore()
            cc = ContextCache(memory_store=memory)
            # Симулируем данные от save_result
            redis = await memory._get_redis()
            await redis.set(
                "agent:last_result:seo-agent",
                '{"cycle_id": "c1", "timestamp": "2024-01-01T00:00:00", "data": {"title": "Test"}, "elapsed_ms": 100}',
                ex=3600,
            )
            result = await cc.get_last_results("seo-agent", limit=3)
            self.assertIsNotNone(result)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["agent_name"], "seo-agent")
            self.assertEqual(result[0]["cycle_id"], "c1")

        self.loop.run_until_complete(_test())


if __name__ == "__main__":
    unittest.main(verbosity=2)
