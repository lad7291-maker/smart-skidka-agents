#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Публикация контента в Telegram канал @dealshub_ali_bot.
"""

import os
import asyncio
import aiohttp
from typing import Optional

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "-100")  # если канал

# Если CHANNEL_ID не задан — используем личный чат владельца
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "1718706291")

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def post_to_channel(text: str, photo_url: Optional[str] = None) -> bool:
    """Публикует пост (текст + опционально фото) в Telegram."""
    if not BOT_TOKEN:
        print("[SKIP] TELEGRAM_BOT_TOKEN not set")
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
                    return True
                else:
                    print(f"[ERROR] Telegram API: {data}")
                    return False
        except Exception as e:
            print(f"[ERROR] post_to_channel: {e}")
            return False

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
