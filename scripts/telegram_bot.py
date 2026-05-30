#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                   TELEGRAM BOT — Управление агентами                 ║
║                         smart-skidka.ru                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  Команды: /status /agents /pause /resume /run_now /logs /help       ║
╚══════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime

import aiohttp
import redis.asyncio as aioredis
import asyncpg

# ═══ Настройки ════════════════════════════════════════════════════════
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OWNER_ID = os.getenv("TELEGRAM_CHAT_ID", "1718706291")
DB_URL = os.getenv("DATABASE_URL", "postgresql://smartskidka:smartskidka123@localhost:5432/smartskidka")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

API_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"

ALLOWED_USERS = {OWNER_ID}

AGENTS = [
    ("content-agent", "📝 Контент"),
    ("seo-agent", "🔍 SEO"),
    ("smm-agent", "📱 SMM"),
    ("performance-agent", "⚡ Перформанс"),
    ("analytics-agent", "📊 Аналитика"),
    ("email-agent", "📧 Email"),
    ("trend-agent", "🔥 Тренды"),
]


def is_allowed(user_id: str) -> bool:
    return user_id in ALLOWED_USERS or user_id == OWNER_ID


# ═══ Telegram API helpers ═════════════════════════════════════════════

async def api_post(method: str, payload: dict) -> dict:
    url = f"{API_BASE}/{method}"
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            return await resp.json()


async def send_message(chat_id: str, text: str, parse_mode: str = "Markdown", reply_markup: dict = None) -> bool:
    payload = {"chat_id": chat_id, "text": text[:4096], "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    data = await api_post("sendMessage", payload)
    return data.get("ok", False)


async def edit_message_text(chat_id: str, message_id: int, text: str, reply_markup: dict = None) -> bool:
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text[:4096], "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    data = await api_post("editMessageText", payload)
    return data.get("ok", False)


async def send_typing(chat_id: str):
    await api_post("sendChatAction", {"chat_id": chat_id, "action": "typing"})


# ═══ Keyboards ════════════════════════════════════════════════════════

def main_menu_keyboard() -> dict:
    """Главное меню — 2 кнопки в ряд"""
    return {
        "inline_keyboard": [
            [
                {"text": "🚀 Запустить всех", "callback_data": "run_all"},
                {"text": "⏸ Остановить всех", "callback_data": "pause_all"},
            ],
            [
                {"text": "🤖 Агенты по одному", "callback_data": "menu_agents"},
                {"text": "📊 Статус", "callback_data": "status"},
            ],
            [
                {"text": "📜 Логи", "callback_data": "logs"},
                {"text": "❓ Помощь", "callback_data": "help"},
            ],
        ]
    }


def agents_menu_keyboard() -> dict:
    """Меню управления отдельными агентами"""
    keyboard = []
    for name, label in AGENTS:
        keyboard.append([
            {"text": f"▶ {label}", "callback_data": f"run:{name}"},
            {"text": f"⏸ {label}", "callback_data": f"pause:{name}"},
        ])
    keyboard.append([{"text": "🔙 Назад", "callback_data": "main_menu"}])
    return {"inline_keyboard": keyboard}


# ═══ Redis helpers (singleton connection) ═════════════════════════════

_redis_client: aioredis.Redis | None = None


async def _get_redis() -> aioredis.Redis:
    """Возвращает singleton подключение к Redis."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client


async def redis_close() -> None:
    """Закрывает singleton подключение к Redis."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def redis_pause(agent: str, hours: int = 12):
    redis = await _get_redis()
    await redis.set(f"agent:pause:{agent}", "1", ex=hours * 3600)


async def redis_resume(agent: str):
    redis = await _get_redis()
    await redis.delete(f"agent:pause:{agent}")


async def redis_run_now(agent: str):
    redis = await _get_redis()
    await redis.set(f"agent:run_now:{agent}", "1", ex=3600)


# ═══ Handlers ═════════════════════════════════════════════════════════

async def handle_status(chat_id: str, edit_msg_id: int = None):
    lines = ["📊 *Статус системы*\n\n"]

    try:
        proc = await asyncio.create_subprocess_exec(
            "systemctl", "is-active", "smart-skidka-agents",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        status = stdout.decode().strip()
        emoji = "🟢" if status == "active" else "🔴"
        lines.append(f"{emoji} Оркестратор: `{status}`\n")
    except Exception:
        lines.append("⚠️ Не удалось проверить статус\n")

    try:
        conn = await asyncpg.connect(DB_URL)
        rows = await conn.fetch(
            """
            SELECT agent_name, cycle_id, timestamp, validation_score, data
            FROM agent_results
            ORDER BY timestamp DESC
            LIMIT 10
            """
        )
        await conn.close()

        if rows:
            lines.append("\n🤖 *Последние агенты:*\n")
            for r in rows:
                ts = r["timestamp"].strftime("%H:%M") if r["timestamp"] else "?"
                score = r["validation_score"] or 0
                name = r["agent_name"]
                data = r["data"]
                actions = ""
                if isinstance(data, dict):
                    acts = data.get("actions", [])
                    if acts:
                        ok_count = sum(1 for a in acts if ":True" in str(a))
                        actions = f" ({ok_count}✅)"
                lines.append(f"• `{name}` — {ts}, качество {score:.0%}{actions}\n")
        else:
            lines.append("\n⚠️ Нет данных в БД\n")
    except Exception as e:
        lines.append(f"\n⚠️ Ошибка БД: `{str(e)[:100]}`\n")

    text = "".join(lines)
    kb = main_menu_keyboard()
    if edit_msg_id:
        await edit_message_text(chat_id, edit_msg_id, text, kb)
    else:
        await send_message(chat_id, text, reply_markup=kb)


async def handle_pause(chat_id: str, agent: str, edit_msg_id: int = None):
    await redis_pause(agent)
    text = f"⏸ Агент `{agent}` *приостановлен* на 12 часов.\n\nЧтобы возобновить — нажми ▶ в меню агентов."
    kb = main_menu_keyboard()
    if edit_msg_id:
        await edit_message_text(chat_id, edit_msg_id, text, kb)
    else:
        await send_message(chat_id, text, reply_markup=kb)


async def handle_resume(chat_id: str, agent: str, edit_msg_id: int = None):
    await redis_resume(agent)
    text = f"▶ Агент `{agent}` *возобновлён*."
    kb = main_menu_keyboard()
    if edit_msg_id:
        await edit_message_text(chat_id, edit_msg_id, text, kb)
    else:
        await send_message(chat_id, text, reply_markup=kb)


async def handle_run_now(chat_id: str, agent: str, edit_msg_id: int = None):
    await redis_run_now(agent)
    text = f"🚀 Агент `{agent}` поставлен в *срочную очередь*.\n\nСледующий цикл запустит его первым."
    kb = main_menu_keyboard()
    if edit_msg_id:
        await edit_message_text(chat_id, edit_msg_id, text, kb)
    else:
        await send_message(chat_id, text, reply_markup=kb)


async def handle_pause_all(chat_id: str, edit_msg_id: int = None):
    for name, _ in AGENTS:
        await redis_pause(name)
    text = "⏸ *Все агенты приостановлены* на 12 часов.\n\nНажми 🚀 чтобы запустить всех."
    kb = main_menu_keyboard()
    if edit_msg_id:
        await edit_message_text(chat_id, edit_msg_id, text, kb)
    else:
        await send_message(chat_id, text, reply_markup=kb)


async def handle_run_all(chat_id: str, edit_msg_id: int = None):
    for name, _ in AGENTS:
        await redis_resume(name)
        await redis_run_now(name)
    text = "🚀 *Все агенты запущены* и поставлены в срочную очередь!"
    kb = main_menu_keyboard()
    if edit_msg_id:
        await edit_message_text(chat_id, edit_msg_id, text, kb)
    else:
        await send_message(chat_id, text, reply_markup=kb)


async def handle_logs(chat_id: str, lines_count: int = 20, edit_msg_id: int = None):
    try:
        proc = await asyncio.create_subprocess_exec(
            "journalctl", "-u", "smart-skidka-agents", "-n", str(lines_count), "--no-pager",
            stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        stdout, _ = await proc.communicate()
        logs = stdout.decode()

        if len(logs) > 3500:
            logs = logs[-3500:] + "\n... (обрезано)"

        text = f"📜 *Последние {lines_count} строк логов:*\n```\n{logs}\n```"
    except Exception as e:
        text = f"❌ Ошибка: `{str(e)[:200]}`"

    kb = main_menu_keyboard()
    if edit_msg_id:
        await edit_message_text(chat_id, edit_msg_id, text, kb)
    else:
        await send_message(chat_id, text, reply_markup=kb)


async def handle_help(chat_id: str, edit_msg_id: int = None):
    text = (
        "🎮 *SmartSkidka — Управление агентами*\n\n"
        "🚀 *Запустить всех* — снять паузу со всех агентов\n"
        "⏸ *Остановить всех* — приостановить всех на 12ч\n"
        "🤖 *Агенты по одному* — управление каждым агентом\n"
        "📊 *Статус* — кто работал, результаты\n"
        "📜 *Логи* — последние строки журнала\n\n"
        "Интервал: *раз в 12 часов*\n"
        "Модель: Claude Opus"
    )
    kb = main_menu_keyboard()
    if edit_msg_id:
        await edit_message_text(chat_id, edit_msg_id, text, kb)
    else:
        await send_message(chat_id, text, reply_markup=kb)


async def handle_menu_agents(chat_id: str, edit_msg_id: int = None):
    text = "🤖 *Управление агентами*\n\nВыбери агента:"
    kb = agents_menu_keyboard()
    if edit_msg_id:
        await edit_message_text(chat_id, edit_msg_id, text, kb)
    else:
        await send_message(chat_id, text, reply_markup=kb)


async def handle_main_menu(chat_id: str, edit_msg_id: int):
    text = "🏠 *Главное меню*\n\nВыбери действие:"
    await edit_message_text(chat_id, edit_msg_id, text, main_menu_keyboard())


# ═══ Message / Callback router ════════════════════════════════════════

async def process_update(update: dict):
    # Callback query (inline buttons)
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = str(cq["message"]["chat"]["id"])
        user_id = str(cq["from"]["id"])
        data = cq["data"]
        msg_id = cq["message"]["message_id"]

        if not is_allowed(user_id):
            await send_message(chat_id, "⛔ У вас нет доступа.")
            return

        # Answer callback to remove loading spinner
        await api_post("answerCallbackQuery", {"callback_query_id": cq["id"]})

        if data == "status":
            await handle_status(chat_id, msg_id)
        elif data == "logs":
            await handle_logs(chat_id, 20, msg_id)
        elif data == "help":
            await handle_help(chat_id, msg_id)
        elif data == "main_menu":
            await handle_main_menu(chat_id, msg_id)
        elif data == "menu_agents":
            await handle_menu_agents(chat_id, msg_id)
        elif data == "pause_all":
            await handle_pause_all(chat_id, msg_id)
        elif data == "run_all":
            await handle_run_all(chat_id, msg_id)
        elif data.startswith("pause:"):
            agent = data.split(":", 1)[1]
            await handle_pause(chat_id, agent, msg_id)
        elif data.startswith("run:"):
            agent = data.split(":", 1)[1]
            await handle_run_now(chat_id, agent, msg_id)
        return

    # Regular message
    message = update.get("message", {})
    chat_id = str(message.get("chat", {}).get("id", ""))
    user_id = str(message.get("from", {}).get("id", ""))
    text = message.get("text", "")

    if not text:
        return
    if not is_allowed(user_id):
        await send_message(chat_id, "⛔ У вас нет доступа к управлению.")
        return

    await send_typing(chat_id)

    cmd = text.split(maxsplit=1)[0].split("@")[0].lower()

    if cmd == "/start":
        await handle_help(chat_id)
    elif cmd == "/help":
        await handle_help(chat_id)
    elif cmd == "/status":
        await handle_status(chat_id)
    elif cmd == "/logs":
        arg = text.split(maxsplit=1)[1] if len(text.split(maxsplit=1)) > 1 else "20"
        n = int(arg) if arg.isdigit() else 20
        await handle_logs(chat_id, n)
    elif cmd in ("/pause", "/resume", "/run_now"):
        await send_message(chat_id, "Используй кнопки в меню /start для управления агентами.")
    else:
        await send_message(chat_id, "Напиши /start чтобы открыть меню управления.")


# ═══ Polling loop ═════════════════════════════════════════════════════

async def report_poller_task():
    """Фоновая задача: читает БД и отправляет отчёты о новых циклах."""
    last_cycle_id = ""
    while True:
        try:
            await asyncio.sleep(60)  # проверяем каждую минуту
            conn = await asyncpg.connect(DB_URL)
            row = await conn.fetchrow(
                """
                SELECT cycle_id, timestamp, data
                FROM orchestrator_cycles
                ORDER BY timestamp DESC
                LIMIT 1
                """
            )
            if not row:
                await conn.close()
                continue

            cycle_id = row["cycle_id"]
            if cycle_id == last_cycle_id:
                await conn.close()
                continue
            last_cycle_id = cycle_id

            # Получаем результаты агентов за этот цикл
            results = await conn.fetch(
                """
                SELECT agent_name, data, metrics, validation_score, timestamp
                FROM agent_results
                WHERE cycle_id = $1
                ORDER BY timestamp
                """,
                cycle_id,
            )
            await conn.close()

            # Формируем отчёт
            ts = row["timestamp"].strftime("%H:%M") if row["timestamp"] else "?"
            lines = [
                f"🔄 *Сводка по циклу*\n",
                f"🆔 ID: `{cycle_id}`\n",
                f"🕐 {ts}\n\n",
            ]

            for r in results:
                name = r["agent_name"]
                score = (r["validation_score"] or 0) * 100
                data = r["data"]
                actions = []
                if isinstance(data, dict):
                    acts = data.get("actions", [])
                    for a in acts:
                        if isinstance(a, str):
                            if a.startswith("tg_post:True"):
                                actions.append("✅ Пост в Telegram")
                            elif a.startswith("meta_updated:True"):
                                actions.append("✅ Meta-теги обновлены")
                            elif a.startswith("prioritized:True"):
                                actions.append("✅ Приоритеты товаров")
                            elif a.startswith("category_page:"):
                                cat = a.split(":")[1] if ":" in a else "?"
                                actions.append(f"✅ Страница `{cat}`")
                            elif a.startswith("item_desc:"):
                                iid = a.split(":")[1] if ":" in a else "?"
                                actions.append(f"✅ Описание товара `{iid}`")
                            elif a == "paused":
                                actions.append("⏸ На паузе")

                lines.append(f"*{name}* — качество {score:.0f}%\n")
                for act in actions[:4]:
                    lines.append(f"  {act}\n")
                lines.append("\n")

            text = "".join(lines)[:4000]
            await send_message(OWNER_ID, text, reply_markup=main_menu_keyboard())

        except Exception as e:
            print(f"[ERROR] report_poller: {e}")


async def polling_loop():
    offset = 0
    print(f"[{datetime.now()}] Bot polling started")

    # Запускаем фоновый poller отчётов
    asyncio.create_task(report_poller_task())

    async with aiohttp.ClientSession() as session:
        while True:
            try:
                url = f"{API_BASE}/getUpdates"
                params = {"offset": offset, "limit": 10, "timeout": 30}

                async with session.get(url, params=params) as resp:
                    data = await resp.json()

                if not data.get("ok"):
                    print(f"[ERROR] getUpdates failed: {data}")
                    await asyncio.sleep(5)
                    continue

                for update in data.get("result", []):
                    offset = max(offset, update["update_id"] + 1)
                    try:
                        await process_update(update)
                    except Exception as e:
                        print(f"[ERROR] process_update: {e}")

            except Exception as e:
                print(f"[ERROR] polling: {e}")
                await asyncio.sleep(5)


def main():
    if not BOT_TOKEN:
        print("[FATAL] TELEGRAM_BOT_TOKEN not set")
        sys.exit(1)
    print(f"[INFO] Owner ID: {OWNER_ID}")
    asyncio.run(polling_loop())


if __name__ == "__main__":
    main()
