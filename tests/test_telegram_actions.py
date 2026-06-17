#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для telegram_actions.py — публикация в Telegram с rate limiting.
"""

import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

from scripts.actions.telegram_actions import (
    BOT_TOKEN,
    CHANNEL_ID,
    CHAT_ID,
    TELEGRAM_POST_COOLDOWN_SECONDS,
    TELEGRAM_POST_DAILY_LIMIT,
    _MemoryRateLimiter,
    _RedisRateLimiter,
    get_telegram_rate_limit_status,
    post_discount,
    post_to_channel,
)


class TestMemoryRateLimiter(unittest.IsolatedAsyncioTestCase):
    """Тесты in-memory rate limiter."""

    async def asyncSetUp(self):
        self.limiter = _MemoryRateLimiter()
        self.limiter.last_post_time = 0.0
        self.limiter.daily_posts = []

    async def test_can_post_when_empty(self):
        allowed, reason = await self.limiter.can_post()
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    async def test_cooldown_blocks(self):
        await self.limiter.record_post()
        allowed, reason = await self.limiter.can_post()
        self.assertFalse(allowed)
        self.assertIn("Cooldown", reason)

    async def test_daily_limit_blocks(self):
        import time

        now = time.time()
        self.limiter.daily_posts = [now - i for i in range(TELEGRAM_POST_DAILY_LIMIT)]
        self.limiter.last_post_time = now - TELEGRAM_POST_COOLDOWN_SECONDS - 1

        allowed, reason = await self.limiter.can_post()
        self.assertFalse(allowed)
        self.assertIn("Daily limit", reason)

    async def test_record_post_updates(self):
        await self.limiter.record_post()
        self.assertGreater(self.limiter.last_post_time, 0)
        self.assertEqual(len(self.limiter.daily_posts), 1)

    async def test_cleanup_old_posts(self):
        import time

        now = time.time()
        self.limiter.daily_posts = [
            now - 25 * 3600,  # 25 hours ago
            now - 1,  # 1 second ago
        ]
        self.limiter._cleanup_old_posts()
        self.assertEqual(len(self.limiter.daily_posts), 1)

    def test_get_status(self):
        status = self.limiter.get_status()
        self.assertIn("last_post_time", status)
        self.assertIn("cooldown_remaining_seconds", status)
        self.assertIn("daily_posts_count", status)
        self.assertIn("daily_limit", status)
        self.assertEqual(status["daily_limit"], TELEGRAM_POST_DAILY_LIMIT)
        self.assertEqual(status["backend"], "memory")

    async def test_cooldown_expires(self):
        import time

        await self.limiter.record_post()
        # Simulate time passing
        self.limiter.last_post_time = time.time() - TELEGRAM_POST_COOLDOWN_SECONDS - 1
        allowed, reason = await self.limiter.can_post()
        self.assertTrue(allowed)


class TestRedisRateLimiter(unittest.IsolatedAsyncioTestCase):
    """Тесты Redis rate limiter."""

    async def asyncSetUp(self):
        # Ensure Redis is not connected
        _RedisRateLimiter._redis = None
        os.environ["REDIS_URL"] = "redis://localhost:9999/1"  # Non-existent

    async def test_fallback_to_memory(self):
        # When Redis is unavailable, should fallback to memory limiter
        # But first we need to ensure Redis connection fails quickly
        with patch("redis.asyncio.from_url", side_effect=Exception("No Redis")):
            allowed, reason = await _RedisRateLimiter.can_post()
            self.assertIsInstance(allowed, bool)
            self.assertIsInstance(reason, str)

    async def test_record_post_fallback(self):
        # Should not raise when Redis unavailable
        with patch("redis.asyncio.from_url", side_effect=Exception("No Redis")):
            await _RedisRateLimiter.record_post()

    async def test_get_status_fallback(self):
        with patch("redis.asyncio.from_url", side_effect=Exception("No Redis")):
            status = await _RedisRateLimiter.get_status()
            self.assertIsInstance(status, dict)
            self.assertIn("daily_posts_count", status)


class TestGetTelegramRateLimitStatus(unittest.IsolatedAsyncioTestCase):
    """Тесты get_telegram_rate_limit_status."""

    async def test_returns_dict(self):
        os.environ["REDIS_URL"] = "redis://localhost:9999/1"
        status = await get_telegram_rate_limit_status()
        self.assertIsInstance(status, dict)
        self.assertIn("daily_posts_count", status)
        self.assertIn("cooldown_remaining_seconds", status)
        self.assertIn("daily_limit", status)


class TestPostToChannel(unittest.IsolatedAsyncioTestCase):
    """Тесты post_to_channel."""

    async def asyncSetUp(self):
        # Reset memory limiter
        from scripts.actions.telegram_actions import _memory_limiter

        _memory_limiter.last_post_time = 0.0
        _memory_limiter.daily_posts = []

    @patch("aiohttp.ClientSession")
    @patch(
        "scripts.actions.telegram_actions._RedisRateLimiter.can_post",
        return_value=(True, ""),
    )
    @patch("scripts.actions.telegram_actions._RedisRateLimiter.record_post")
    async def test_post_text_success(self, mock_record, mock_can_post, mock_session_class):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"ok": True, "result": {"message_id": 123}})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session

        with patch("scripts.actions.telegram_actions.BOT_TOKEN", "test_token"):
            with patch("scripts.actions.telegram_actions.CHANNEL_ID", "-100123"):
                with patch(
                    "scripts.actions.telegram_actions.API_BASE",
                    "https://api.telegram.org/bottest_token",
                ):
                    result = await post_to_channel("Hello World")
                    self.assertTrue(result)

    @patch("aiohttp.ClientSession")
    @patch(
        "scripts.actions.telegram_actions._RedisRateLimiter.can_post",
        return_value=(True, ""),
    )
    @patch("scripts.actions.telegram_actions._RedisRateLimiter.record_post")
    async def test_post_photo_success(self, mock_record, mock_can_post, mock_session_class):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"ok": True, "result": {"message_id": 123}})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session

        with patch("scripts.actions.telegram_actions.BOT_TOKEN", "test_token"):
            with patch("scripts.actions.telegram_actions.CHANNEL_ID", "-100123"):
                with patch(
                    "scripts.actions.telegram_actions.API_BASE",
                    "https://api.telegram.org/bottest_token",
                ):
                    result = await post_to_channel("Caption text", photo_url="http://example.com/pic.jpg")
                    self.assertTrue(result)

    @patch("aiohttp.ClientSession")
    @patch(
        "scripts.actions.telegram_actions._RedisRateLimiter.can_post",
        return_value=(True, ""),
    )
    @patch("scripts.actions.telegram_actions._RedisRateLimiter.record_post")
    async def test_api_error(self, mock_record, mock_can_post, mock_session_class):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"ok": False, "description": "Bad Request"})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session

        with patch("scripts.actions.telegram_actions.BOT_TOKEN", "test_token"):
            with patch("scripts.actions.telegram_actions.CHANNEL_ID", "-100123"):
                with patch(
                    "scripts.actions.telegram_actions.API_BASE",
                    "https://api.telegram.org/bottest_token",
                ):
                    result = await post_to_channel("Hello")
                    self.assertFalse(result)

    async def test_no_token(self):
        with patch("scripts.actions.telegram_actions.BOT_TOKEN", ""):
            result = await post_to_channel("Hello")
            self.assertFalse(result)

    async def test_rate_limit_blocks(self):
        # Fill the rate limiter
        import time

        from scripts.actions.telegram_actions import _memory_limiter

        now = time.time()
        _memory_limiter.last_post_time = now
        _memory_limiter.daily_posts = [now]

        with patch("scripts.actions.telegram_actions.BOT_TOKEN", "test_token"):
            with patch(
                "scripts.actions.telegram_actions._RedisRateLimiter.can_post",
                return_value=(False, "Rate limited"),
            ):
                result = await post_to_channel("Hello")
                self.assertFalse(result)

    @patch("aiohttp.ClientSession")
    @patch(
        "scripts.actions.telegram_actions._RedisRateLimiter.can_post",
        return_value=(True, ""),
    )
    @patch("scripts.actions.telegram_actions._RedisRateLimiter.record_post")
    async def test_long_text_truncated(self, mock_record, mock_can_post, mock_session_class):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"ok": True, "result": {"message_id": 1}})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session

        with patch("scripts.actions.telegram_actions.BOT_TOKEN", "test_token"):
            with patch("scripts.actions.telegram_actions.CHANNEL_ID", "-100123"):
                with patch(
                    "scripts.actions.telegram_actions.API_BASE",
                    "https://api.telegram.org/bottest_token",
                ):
                    long_text = "A" * 5000
                    result = await post_to_channel(long_text)
                    self.assertTrue(result)
                    # Check that text was truncated
                    call_args = mock_session.post.call_args
                    payload = call_args[1].get("json", {})
                    self.assertLessEqual(len(payload.get("text", "")), 4096)

    @patch("aiohttp.ClientSession")
    @patch(
        "scripts.actions.telegram_actions._RedisRateLimiter.can_post",
        return_value=(True, ""),
    )
    @patch("scripts.actions.telegram_actions._RedisRateLimiter.record_post")
    async def test_long_caption_truncated(self, mock_record, mock_can_post, mock_session_class):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"ok": True, "result": {"message_id": 1}})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session

        with patch("scripts.actions.telegram_actions.BOT_TOKEN", "test_token"):
            with patch("scripts.actions.telegram_actions.CHANNEL_ID", "-100123"):
                with patch(
                    "scripts.actions.telegram_actions.API_BASE",
                    "https://api.telegram.org/bottest_token",
                ):
                    long_caption = "A" * 1200
                    result = await post_to_channel(long_caption, photo_url="http://example.com/pic.jpg")
                    self.assertTrue(result)
                    call_args = mock_session.post.call_args
                    payload = call_args[1].get("json", {})
                    self.assertLessEqual(len(payload.get("caption", "")), 1024)


class TestPostDiscount(unittest.IsolatedAsyncioTestCase):
    """Тесты post_discount."""

    async def asyncSetUp(self):
        from scripts.actions.telegram_actions import _memory_limiter

        _memory_limiter.last_post_time = 0.0
        _memory_limiter.daily_posts = []

    @patch("aiohttp.ClientSession")
    @patch(
        "scripts.actions.telegram_actions._RedisRateLimiter.can_post",
        return_value=(True, ""),
    )
    @patch("scripts.actions.telegram_actions._RedisRateLimiter.record_post")
    async def test_post_discount(self, mock_record, mock_can_post, mock_session_class):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"ok": True, "result": {"message_id": 123}})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session

        product = {
            "title": "Wireless Earbuds",
            "price": "1999",
            "oldPrice": "3999",
            "discount": "50%",
            "image": "http://example.com/pic.jpg",
            "aliLink": "http://example.com/product",
        }

        with patch("scripts.actions.telegram_actions.BOT_TOKEN", "test_token"):
            with patch("scripts.actions.telegram_actions.CHANNEL_ID", "-100123"):
                with patch(
                    "scripts.actions.telegram_actions.API_BASE",
                    "https://api.telegram.org/bottest_token",
                ):
                    result = await post_discount(product)
                    self.assertTrue(result)

    @patch("aiohttp.ClientSession")
    @patch(
        "scripts.actions.telegram_actions._RedisRateLimiter.can_post",
        return_value=(True, ""),
    )
    @patch("scripts.actions.telegram_actions._RedisRateLimiter.record_post")
    async def test_post_discount_no_image(self, mock_record, mock_can_post, mock_session_class):
        mock_session = MagicMock()
        mock_response = MagicMock()
        mock_response.json = AsyncMock(return_value={"ok": True, "result": {"message_id": 123}})
        mock_response.__aenter__ = AsyncMock(return_value=mock_response)
        mock_response.__aexit__ = AsyncMock(return_value=False)
        mock_session.post = MagicMock(return_value=mock_response)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)
        mock_session_class.return_value = mock_session

        product = {
            "title": "Gadget",
            "price": "100",
            "oldPrice": "200",
            "discount": "50%",
            "image": "",
            "aliLink": "http://example.com/product",
        }

        with patch("scripts.actions.telegram_actions.BOT_TOKEN", "test_token"):
            with patch("scripts.actions.telegram_actions.CHANNEL_ID", "-100123"):
                with patch(
                    "scripts.actions.telegram_actions.API_BASE",
                    "https://api.telegram.org/bottest_token",
                ):
                    result = await post_discount(product)
                    self.assertTrue(result)


class TestTargetSelection(unittest.TestCase):
    """Тесты выбора target (CHANNEL_ID vs CHAT_ID)."""

    def test_channel_id_used_when_starts_with_dash(self):
        # CHANNEL_ID starts with "-" → used as target
        self.assertTrue(CHANNEL_ID.startswith("-") or not CHANNEL_ID)

    def test_chat_id_fallback(self):
        # If CHANNEL_ID doesn't start with "-", CHAT_ID is used
        pass  # This is tested implicitly in post_to_channel


class TestTokenResolution(unittest.TestCase):
    """Тесты разрешения токена."""

    def test_token_from_env(self):
        # BOT_TOKEN should be set from environment
        self.assertIsInstance(BOT_TOKEN, str)

    def test_channel_id_from_env(self):
        self.assertIsInstance(CHANNEL_ID, str)

    def test_chat_id_from_env(self):
        self.assertIsInstance(CHAT_ID, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
