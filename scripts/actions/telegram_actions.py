#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Публикация контента в Telegram канал @dealshub_ali_bot.

Добавлен rate limiting (P2-8): debounce между постами,
не чаще 1 поста в TELEGRAM_POST_COOLDOWN_MINUTES (default 30 мин).
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional

import aiohttp
import structlog

from . import with_retry
from .action_registry import register_action

_tg_logger = structlog.get_logger("telegram_actions")

# P1-13: Use secrets_manager instead of raw os.getenv
# Fallback to env vars is allowed for backward compatibility
_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-100")
_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1718706291")

try:
    from ..secrets_manager import get_secret

    BOT_TOKEN = get_secret("TELEGRAM_BOT_TOKEN", allow_env_fallback=True) or _BOT_TOKEN
    CHANNEL_ID = get_secret("TELEGRAM_CHANNEL_ID", allow_env_fallback=True) or _CHANNEL_ID
    CHAT_ID = get_secret("TELEGRAM_CHAT_ID", allow_env_fallback=True) or _CHAT_ID
except Exception:
    BOT_TOKEN = _BOT_TOKEN
    CHANNEL_ID = _CHANNEL_ID
    CHAT_ID = _CHAT_ID

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ═══════════════════════════════════════════════════════════════════════════════
# P2-8 + P1-14: Rate limiting для Telegram-постинга
# ═══════════════════════════════════════════════════════════════════════════════

# Интервал между постами в секундах (default 30 минут)
TELEGRAM_POST_COOLDOWN_SECONDS: int = int(os.getenv("TELEGRAM_POST_COOLDOWN_MINUTES", "30")) * 60

# Максимум постов в сутки
TELEGRAM_POST_DAILY_LIMIT: int = int(os.getenv("TELEGRAM_POST_DAILY_LIMIT", "10"))

# Redis URL для распределённого rate limiting (P1-14)
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")


class _RedisRateLimiter:
    """
    P1-14: Redis-based rate limiter для multi-instance.

    Отслеживает:
    - last_post_time: время последнего поста (cooldown)
    - daily_posts: список постов за сегодня (sorted set)
    """

    _redis: Optional[Any] = None
    _redis_lock = asyncio.Lock()

    @classmethod
    async def _get_redis(cls):
        if cls._redis is None:
            try:
                import redis.asyncio as aioredis

                cls._redis = await aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
            except Exception:
                cls._redis = None
        return cls._redis

    @classmethod
    async def can_post(cls) -> tuple[bool, str]:
        """Проверяет, можно ли сделать пост (через Redis)."""
        redis = await cls._get_redis()
        if not redis:
            # Fallback на in-memory
            return await _memory_limiter.can_post()

        now = time.time()
        pipe = redis.pipeline()

        # 1. Проверка cooldown
        last_post = await redis.get("tg:rate:last_post")
        if last_post:
            elapsed = now - float(last_post)
            if elapsed < TELEGRAM_POST_COOLDOWN_SECONDS:
                wait = int(TELEGRAM_POST_COOLDOWN_SECONDS - elapsed)
                return False, f"Cooldown active: wait {wait}s before next post"

        # 2. Проверка дневного лимита (sorted set с автоочисткой)
        day_key = f"tg:rate:daily:{datetime.now().strftime('%Y%m%d')}"
        cutoff = now - 24 * 3600
        await redis.zremrangebyscore(day_key, 0, cutoff)
        count = await redis.zcard(day_key)
        if count >= TELEGRAM_POST_DAILY_LIMIT:
            return (
                False,
                f"Daily limit reached: {count}/{TELEGRAM_POST_DAILY_LIMIT} posts today",
            )

        return True, ""

    @classmethod
    async def record_post(cls) -> None:
        """Записывает факт постинга в Redis."""
        redis = await cls._get_redis()
        if not redis:
            await _memory_limiter.record_post()
            return

        now = time.time()
        day_key = f"tg:rate:daily:{datetime.now().strftime('%Y%m%d')}"
        pipe = redis.pipeline()
        pipe.set("tg:rate:last_post", str(now))
        pipe.expire("tg:rate:last_post", TELEGRAM_POST_COOLDOWN_SECONDS + 60)
        pipe.zadd(day_key, {str(now): now})
        pipe.expire(day_key, 24 * 3600 + 60)
        await pipe.execute()

    @classmethod
    async def get_status(cls) -> Dict[str, any]:
        """Возвращает текущий статус rate limiter."""
        redis = await cls._get_redis()
        if not redis:
            return _memory_limiter.get_status()

        now = time.time()
        last_post = await redis.get("tg:rate:last_post")
        day_key = f"tg:rate:daily:{datetime.now().strftime('%Y%m%d')}"
        cutoff = now - 24 * 3600
        await redis.zremrangebyscore(day_key, 0, cutoff)
        count = await redis.zcard(day_key)

        last_post_time = float(last_post) if last_post else 0.0
        cooldown_remaining = max(0, TELEGRAM_POST_COOLDOWN_SECONDS - (now - last_post_time))
        return {
            "last_post_time": last_post_time,
            "cooldown_remaining_seconds": int(cooldown_remaining),
            "daily_posts_count": count,
            "daily_limit": TELEGRAM_POST_DAILY_LIMIT,
            "cooldown_seconds": TELEGRAM_POST_COOLDOWN_SECONDS,
            "backend": "redis",
        }


@dataclass
class _MemoryRateLimiter:
    """
    In-memory fallback rate limiter.
    Используется когда Redis недоступен.
    """

    last_post_time: float = 0.0
    daily_posts: list = field(default_factory=list)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def _cleanup_old_posts(self) -> None:
        """Удаляет посты старше 24 часов."""
        now = time.time()
        cutoff = now - 24 * 3600
        self.daily_posts = [t for t in self.daily_posts if t > cutoff]

    async def can_post(self) -> tuple[bool, str]:
        """Проверяет, можно ли сделать пост сейчас."""
        async with self._lock:
            now = time.time()
            elapsed = now - self.last_post_time
            if elapsed < TELEGRAM_POST_COOLDOWN_SECONDS:
                wait = int(TELEGRAM_POST_COOLDOWN_SECONDS - elapsed)
                return False, f"Cooldown active: wait {wait}s before next post"
            self._cleanup_old_posts()
            if len(self.daily_posts) >= TELEGRAM_POST_DAILY_LIMIT:
                return False, (
                    f"Daily limit reached: {len(self.daily_posts)}/" f"{TELEGRAM_POST_DAILY_LIMIT} posts today"
                )
            return True, ""

    async def record_post(self) -> None:
        """Записывает факт постинга."""
        async with self._lock:
            self.last_post_time = time.time()
            self.daily_posts.append(self.last_post_time)
            self._cleanup_old_posts()

    def get_status(self) -> Dict[str, any]:
        """Возвращает текущий статус rate limiter."""
        now = time.time()
        self._cleanup_old_posts()
        cooldown_remaining = max(0, TELEGRAM_POST_COOLDOWN_SECONDS - (now - self.last_post_time))
        return {
            "last_post_time": self.last_post_time,
            "cooldown_remaining_seconds": int(cooldown_remaining),
            "daily_posts_count": len(self.daily_posts),
            "daily_limit": TELEGRAM_POST_DAILY_LIMIT,
            "cooldown_seconds": TELEGRAM_POST_COOLDOWN_SECONDS,
            "backend": "memory",
        }


# Singleton rate limiters
_memory_limiter = _MemoryRateLimiter()


async def get_telegram_rate_limit_status() -> Dict[str, any]:
    """Возвращает статус rate limiter для мониторинга."""
    # P2-7 fix: Fallback на memory limiter если Redis недоступен
    try:
        return await _RedisRateLimiter.get_status()
    except Exception:
        return _memory_limiter.get_status()


@with_retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
@register_action(
    "post_to_channel",
    agent_types=["smm"],
    description="Публикует пост в Telegram канал",
)
async def post_to_channel(text: str, photo_url: Optional[str] = None) -> bool:
    """
    Публикует пост (текст + опционально фото) в Telegram.

    P2-8: Rate limiting — не чаще 1 поста в N минут,
    не более M постов в сутки.
    """
    if not BOT_TOKEN:
        _tg_logger.warning("TELEGRAM_BOT_TOKEN not set, skipping post")
        return False

    # Rate limiting check (P1-14: Redis-based)
    allowed, reason = await _RedisRateLimiter.can_post()
    if not allowed:
        _tg_logger.warning("Telegram post blocked by rate limiter", reason=reason)
        return False

    target = CHANNEL_ID if CHANNEL_ID.startswith("-") else CHAT_ID

    async with aiohttp.ClientSession() as session:
        try:
            if photo_url:
                url = f"{API_BASE}/sendPhoto"
                payload = {
                    "chat_id": target,
                    "photo": photo_url,
                    "caption": text[:1024],  # лимит caption
                    "parse_mode": "HTML",
                }
            else:
                url = f"{API_BASE}/sendMessage"
                payload = {
                    "chat_id": target,
                    "text": text[:4096],
                    "parse_mode": "HTML",
                    "disable_web_page_preview": False,
                }

            async with session.post(url, json=payload) as resp:
                data = await resp.json()
                if data.get("ok"):
                    _tg_logger.info("Posted to Telegram", message_id=data["result"]["message_id"])
                    await _RedisRateLimiter.record_post()
                    return True
                else:
                    _tg_logger.error("Telegram API error", response=data)
                    return False
        except Exception as e:
            _tg_logger.error("post_to_channel failed", error=str(e))
            return False


@with_retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
@register_action(
    "post_discount",
    agent_types=["smm"],
    description="Форматирует и публикует пост о скидке в Telegram",
)
async def post_discount(product: dict) -> bool:
    """Форматирует и публикует пост о скидке."""
    title = product.get("title", "Товар")
    price = product.get("price", "?")
    old_price = product.get("oldPrice", "?")
    discount = product.get("discount", "0%")
    image = product.get("image", "")
    link = product.get("aliLink", "")

    text = (
        f"🔥 <b>{title}</b>\n\n"
        f"💰 <s>{old_price}₽</s> → <b>{price}₽</b>\n"
        f"📉 Скидка: <b>{discount}</b>\n\n"
        f"👉 <a href='{link}'>Купить на AliExpress</a>"
    )

    return await post_to_channel(text, photo_url=image)
