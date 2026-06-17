#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для rate limiting Telegram-постинга (P2-8).
"""

import sys
import asyncio
import unittest

sys.path.insert(0, '/opt/smart-skidka-agents')
sys.path.insert(0, '/opt/smart-skidka-agents/scripts')

from scripts.actions.telegram_actions import (
    _MemoryRateLimiter,
    get_telegram_rate_limit_status,
    TELEGRAM_POST_COOLDOWN_SECONDS,
    TELEGRAM_POST_DAILY_LIMIT,
)


class TestRateLimiter(unittest.IsolatedAsyncioTestCase):
    """Тесты rate limiter для Telegram."""

    async def asyncSetUp(self):
        self.limiter = _MemoryRateLimiter()
        self.limiter.last_post_time = 0.0
        self.limiter.daily_posts = []

    async def test_can_post_when_empty(self):
        """Первый пост разрешён."""
        allowed, reason = await self.limiter.can_post()
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    async def test_cooldown_blocks_second_post(self):
        """Второй пост во время cooldown блокируется."""
        await self.limiter.record_post()
        allowed, reason = await self.limiter.can_post()
        self.assertFalse(allowed)
        self.assertIn("Cooldown", reason)

    async def test_daily_limit_blocks(self):
        """Превышение дневного лимита блокируется."""
        import time
        now = time.time()
        # Заполняем лимит
        self.limiter.daily_posts = [now - i for i in range(TELEGRAM_POST_DAILY_LIMIT)]
        self.limiter.last_post_time = now - TELEGRAM_POST_COOLDOWN_SECONDS - 1
        
        allowed, reason = await self.limiter.can_post()
        self.assertFalse(allowed)
        self.assertIn("Daily limit", reason)

    async def test_record_post_updates_state(self):
        """Запись поста обновляет состояние."""
        await self.limiter.record_post()
        self.assertGreater(self.limiter.last_post_time, 0)
        self.assertEqual(len(self.limiter.daily_posts), 1)

    async def test_cleanup_old_posts(self):
        """Старые посты (>24ч) удаляются."""
        import time
        now = time.time()
        self.limiter.daily_posts = [
            now - 25 * 3600,  # 25 часов назад — старый
            now - 1,           # 1 секунду назад — свежий
        ]
        self.limiter._cleanup_old_posts()
        self.assertEqual(len(self.limiter.daily_posts), 1)

    async def test_get_status_structure(self):
        """get_status возвращает корректную структуру."""
        status = self.limiter.get_status()
        self.assertIn("last_post_time", status)
        self.assertIn("cooldown_remaining_seconds", status)
        self.assertIn("daily_posts_count", status)
        self.assertIn("daily_limit", status)
        self.assertEqual(status["daily_limit"], TELEGRAM_POST_DAILY_LIMIT)


class TestGlobalRateLimitStatus(unittest.IsolatedAsyncioTestCase):
    """Тесты глобальной функции статуса."""

    async def test_get_telegram_rate_limit_status(self):
        """get_telegram_rate_limit_status возвращает словарь."""
        # P2-7 fix: Мокаем Redis для теста без подключения
        import os
        os.environ["REDIS_URL"] = "redis://localhost:9999/1"  # Несуществующий порт
        status = await get_telegram_rate_limit_status()
        self.assertIsInstance(status, dict)
        self.assertIn("daily_posts_count", status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
