#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Публикация контента в Telegram канал @dealshub_ali_bot.

Добавлен rate limiting (P2-8): debounce между постами,
не чаще 1 поста в TELEGRAM_POST_COOLDOWN_MINUTES (default 30 мин).
"""

from __future__ import annotations

import os
import asyncio
import time
from typing import Optional, Dict
from dataclasses import dataclass, field

import aiohttp

from . import with_retry

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-100")  # если канал
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1718706291")
API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ═══════════════════════════════════════════════════════════════════════════════
# P2-8: Rate limiting для Telegram-постинга
# ═══════════════════════════════════════════════════════════════════════════════

# Интервал между постами в секундах (default 30 минут)
TELEGRAM_POST_COOLDOWN_SECONDS: int = int(
    os.getenv("TELEGRAM_POST_COOLDOWN_MINUTES", "30")
) * 60

# Максимум постов в сутки
TELEGRAM_POST_DAILY_LIMIT: int = int(
    os.getenv("TELEGRAM_POST_DAILY_LIMIT", "10")
)


@dataclass
class _RateLimiter:
    """
    In-memory rate limiter для Telegram-постинга.
    
    Отслеживает:
    - last_post_time: время последнего поста (cooldown)
    - daily_posts: список постов за сегодня
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
        """
        Проверяет, можно ли сделать пост сейчас.
        
        Returns: (allowed, reason)
        """
        async with self._lock:
            now = time.time()
            
            # 1. Проверка cooldown
            elapsed = now - self.last_post_time
            if elapsed < TELEGRAM_POST_COOLDOWN_SECONDS:
                wait = int(TELEGRAM_POST_COOLDOWN_SECONDS - elapsed)
                return False, f"Cooldown active: wait {wait}s before next post"
            
            # 2. Проверка дневного лимита
            self._cleanup_old_posts()
            if len(self.daily_posts) >= TELEGRAM_POST_DAILY_LIMIT:
                return False, (
                    f"Daily limit reached: {len(self.daily_posts)}/"
                    f"{TELEGRAM_POST_DAILY_LIMIT} posts today"
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
        }


# Singleton rate limiter
_tg_rate_limiter = _RateLimiter()


async def get_telegram_rate_limit_status() -> Dict[str, any]:
    """Возвращает статус rate limiter для мониторинга."""
    return _tg_rate_limiter.get_status()


@with_retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
async def post_to_channel(text: str, photo_url: Optional[str] = None) -> bool:
    """
    Публикует пост (текст + опционально фото) в Telegram.
    
    P2-8: Rate limiting — не чаще 1 поста в N минут,
    не более M постов в сутки.
    """
    if not BOT_TOKEN:
        print("[SKIP] TELEGRAM_BOT_TOKEN not set")
        return False

    # Rate limiting check
    allowed, reason = await _tg_rate_limiter.can_post()
    if not allowed:
        print(f"[RATE_LIMIT] Telegram post blocked: {reason}")
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
                    print(f"[OK] Posted to Telegram: {data['result']['message_id']}")
                    await _tg_rate_limiter.record_post()
                    return True
                else:
                    print(f"[ERROR] Telegram API: {data}")
                    return False
        except Exception as e:
            print(f"[ERROR] post_to_channel: {e}")
            return False


@with_retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(Exception,))
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
