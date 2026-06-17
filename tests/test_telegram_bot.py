#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для telegram_bot.py.
Мокают Telegram API, Redis, subprocess, asyncpg.
"""

import sys
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

import pytest

from scripts.telegram_bot import (
    AGENTS,
    ALLOWED_USERS,
    OWNER_ID,
    is_allowed,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Sync функции
# ═══════════════════════════════════════════════════════════════════════════════


class TestIsAllowed:
    def test_owner_allowed(self):
        assert is_allowed(OWNER_ID) is True

    def test_allowed_user(self):
        user = list(ALLOWED_USERS)[0] if ALLOWED_USERS else OWNER_ID
        assert is_allowed(user) is True

    def test_not_allowed(self):
        assert is_allowed("999999999") is False


class TestAgentsList:
    def test_agents_not_empty(self):
        assert len(AGENTS) > 0

    def test_agents_structure(self):
        for agent_id, name in AGENTS:
            assert isinstance(agent_id, str)
            assert isinstance(name, str)
            assert "-agent" in agent_id


class TestKeyboards:
    def test_main_menu_keyboard(self):
        from scripts.telegram_bot import main_menu_keyboard

        kb = main_menu_keyboard()
        assert "inline_keyboard" in kb
        assert len(kb["inline_keyboard"]) > 0

    def test_agents_menu_keyboard(self):
        from scripts.telegram_bot import agents_menu_keyboard

        kb = agents_menu_keyboard()
        assert "inline_keyboard" in kb
        assert len(kb["inline_keyboard"]) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Async Telegram API helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestSendMessage:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock, return_value={"ok": True}):
            from scripts.telegram_bot import send_message

            result = await send_message("123", "Hello")
            assert result is True

    @pytest.mark.asyncio
    async def test_failure(self):
        with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock, return_value={"ok": False}):
            from scripts.telegram_bot import send_message

            result = await send_message("123", "Hello")
            assert result is False

    @pytest.mark.asyncio
    async def test_long_text_truncated(self):
        with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock, return_value={"ok": True}) as mock:
            from scripts.telegram_bot import send_message

            long_text = "A" * 5000
            await send_message("123", long_text)
            call_text = mock.call_args[0][1]["text"]
            assert len(call_text) <= 4096

    @pytest.mark.asyncio
    async def test_with_reply_markup(self):
        with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock, return_value={"ok": True}) as mock:
            from scripts.telegram_bot import send_message

            kb = {"inline_keyboard": []}
            await send_message("123", "Hello", reply_markup=kb)
            assert mock.call_args[0][1]["reply_markup"] == kb


class TestEditMessageText:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock, return_value={"ok": True}):
            from scripts.telegram_bot import edit_message_text

            result = await edit_message_text("123", 1, "Updated")
            assert result is True

    @pytest.mark.asyncio
    async def test_with_reply_markup(self):
        with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock, return_value={"ok": True}) as mock:
            from scripts.telegram_bot import edit_message_text

            kb = {"inline_keyboard": []}
            await edit_message_text("123", 1, "Updated", reply_markup=kb)
            assert mock.call_args[0][1]["reply_markup"] == kb


class TestSendTyping:
    @pytest.mark.asyncio
    async def test_success(self):
        with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock, return_value={"ok": True}) as mock:
            from scripts.telegram_bot import send_typing

            await send_typing("123")
            mock.assert_called_once()


class TestApiPost:
    @pytest.mark.asyncio
    async def test_api_post(self):
        mock_resp = AsyncMock()
        mock_resp.json = AsyncMock(return_value={"ok": True})
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = MagicMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        with patch("aiohttp.ClientSession", return_value=mock_session):
            from scripts.telegram_bot import api_post

            result = await api_post("sendMessage", {"chat_id": "123"})
            assert result == {"ok": True}


# ═══════════════════════════════════════════════════════════════════════════════
# Command handlers
# ═══════════════════════════════════════════════════════════════════════════════


class TestHandleStatus:
    @pytest.mark.asyncio
    async def test_format(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True):
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                with patch("scripts.telegram_bot.asyncpg.connect", new_callable=AsyncMock) as mock_conn:
                    mock_conn.return_value.fetch = AsyncMock(return_value=[])
                    mock_conn.return_value.close = AsyncMock()
                    from scripts.telegram_bot import handle_status

                    result = await handle_status("123")
                    # handle_status не возвращает значение
                    assert result is None

    @pytest.mark.asyncio
    async def test_with_edit_msg_id(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True) as mock_edit:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                with patch("scripts.telegram_bot.asyncpg.connect", new_callable=AsyncMock) as mock_conn:
                    mock_conn.return_value.fetch = AsyncMock(return_value=[])
                    mock_conn.return_value.close = AsyncMock()
                    from scripts.telegram_bot import handle_status

                    result = await handle_status("123", edit_msg_id=42)
                    assert result is None
                    mock_edit.assert_called_once()


class TestHandleHelp:
    @pytest.mark.asyncio
    async def test_format(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True):
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                from scripts.telegram_bot import handle_help

                result = await handle_help("123")
                assert result is None

    @pytest.mark.asyncio
    async def test_with_edit_msg_id(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True) as mock_edit:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                from scripts.telegram_bot import handle_help

                result = await handle_help("123", edit_msg_id=42)
                assert result is None
                mock_edit.assert_called_once()


class TestHandleMainMenu:
    @pytest.mark.asyncio
    async def test_format(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True) as mock_edit:
            from scripts.telegram_bot import handle_main_menu

            result = await handle_main_menu("123", 1)
            assert result is None
            mock_edit.assert_called_once()


class TestHandleMenuAgents:
    @pytest.mark.asyncio
    async def test_format(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True):
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                from scripts.telegram_bot import handle_menu_agents

                result = await handle_menu_agents("123")
                assert result is None

    @pytest.mark.asyncio
    async def test_with_edit_msg_id(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True) as mock_edit:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                from scripts.telegram_bot import handle_menu_agents

                result = await handle_menu_agents("123", edit_msg_id=42)
                assert result is None
                mock_edit.assert_called_once()


class TestHandlePause:
    @pytest.mark.asyncio
    async def test_calls_redis(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True):
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                with patch("scripts.telegram_bot.redis_pause", new_callable=AsyncMock) as mock_redis:
                    from scripts.telegram_bot import handle_pause

                    result = await handle_pause("123", "seo-agent")
                    mock_redis.assert_called_once_with("seo-agent")

    @pytest.mark.asyncio
    async def test_with_edit_msg_id(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True) as mock_edit:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                with patch("scripts.telegram_bot.redis_pause", new_callable=AsyncMock):
                    from scripts.telegram_bot import handle_pause

                    await handle_pause("123", "seo-agent", edit_msg_id=42)
                    mock_edit.assert_called_once()


class TestHandleResume:
    @pytest.mark.asyncio
    async def test_calls_redis(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True):
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                with patch("scripts.telegram_bot.redis_resume", new_callable=AsyncMock) as mock_redis:
                    from scripts.telegram_bot import handle_resume

                    result = await handle_resume("123", "seo-agent")
                    mock_redis.assert_called_once_with("seo-agent")


class TestHandleRunNow:
    @pytest.mark.asyncio
    async def test_calls_redis(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True):
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                with patch("scripts.telegram_bot.redis_run_now", new_callable=AsyncMock) as mock_redis:
                    from scripts.telegram_bot import handle_run_now

                    result = await handle_run_now("123", "seo-agent")
                    mock_redis.assert_called_once_with("seo-agent")


class TestHandleLogs:
    @pytest.mark.asyncio
    async def test_format(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True):
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                with patch("scripts.telegram_bot.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
                    mock_proc.return_value.communicate = AsyncMock(return_value=(b"log line 1\nlog line 2", b""))
                    from scripts.telegram_bot import handle_logs

                    result = await handle_logs("123", 10)
                    assert result is None

    @pytest.mark.asyncio
    async def test_with_edit_msg_id(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True) as mock_edit:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                with patch("scripts.telegram_bot.asyncio.create_subprocess_exec", new_callable=AsyncMock) as mock_proc:
                    mock_proc.return_value.communicate = AsyncMock(return_value=(b"log line 1\nlog line 2", b""))
                    from scripts.telegram_bot import handle_logs

                    await handle_logs("123", 10, edit_msg_id=42)
                    mock_edit.assert_called_once()


class TestHandlePauseAll:
    @pytest.mark.asyncio
    async def test_calls_redis_for_all(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True):
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                with patch("scripts.telegram_bot.redis_pause", new_callable=AsyncMock) as mock_redis:
                    from scripts.telegram_bot import handle_pause_all

                    result = await handle_pause_all("123")
                    assert mock_redis.call_count == len(AGENTS)


class TestHandleRunAll:
    @pytest.mark.asyncio
    async def test_calls_redis_for_all(self):
        with patch("scripts.telegram_bot.edit_message_text", new_callable=AsyncMock, return_value=True):
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True):
                with patch("scripts.telegram_bot.redis_resume", new_callable=AsyncMock) as mock_resume:
                    with patch("scripts.telegram_bot.redis_run_now", new_callable=AsyncMock) as mock_run:
                        from scripts.telegram_bot import handle_run_all

                        result = await handle_run_all("123")
                        assert mock_resume.call_count == len(AGENTS)
                        assert mock_run.call_count == len(AGENTS)


# ═══════════════════════════════════════════════════════════════════════════════
# Redis helpers
# ═══════════════════════════════════════════════════════════════════════════════


class TestRedisHelpers:
    @pytest.mark.asyncio
    async def test_get_redis_singleton(self):
        with patch("redis.asyncio.from_url", new_callable=AsyncMock) as mock:
            import scripts.telegram_bot as tb

            tb._redis_client = None
            from scripts.telegram_bot import _get_redis

            r1 = await _get_redis()
            r2 = await _get_redis()
            mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_redis_pause(self):
        mock_redis = AsyncMock()
        with patch("scripts.telegram_bot._get_redis", new_callable=AsyncMock, return_value=mock_redis):
            from scripts.telegram_bot import redis_pause

            await redis_pause("seo-agent", hours=12)
            mock_redis.set.assert_called_once()
            args = mock_redis.set.call_args[0]
            assert args[0] == "agent:pause:seo-agent"
            assert args[1] == "1"
            # ex=12*3600=43200
            assert mock_redis.set.call_args[1].get("ex") == 43200

    @pytest.mark.asyncio
    async def test_redis_resume(self):
        mock_redis = AsyncMock()
        with patch("scripts.telegram_bot._get_redis", new_callable=AsyncMock, return_value=mock_redis):
            from scripts.telegram_bot import redis_resume

            await redis_resume("seo-agent")
            mock_redis.delete.assert_called_once_with("agent:pause:seo-agent")

    @pytest.mark.asyncio
    async def test_redis_run_now(self):
        mock_redis = AsyncMock()
        with patch("scripts.telegram_bot._get_redis", new_callable=AsyncMock, return_value=mock_redis):
            from scripts.telegram_bot import redis_run_now

            await redis_run_now("seo-agent")
            mock_redis.set.assert_called_once()
            args = mock_redis.set.call_args[0]
            assert args[0] == "agent:run_now:seo-agent"
            assert args[1] == "1"
            assert mock_redis.set.call_args[1].get("ex") == 3600

    @pytest.mark.asyncio
    async def test_redis_close(self):
        mock_redis = MagicMock()
        mock_redis.aclose = AsyncMock()
        with patch("scripts.telegram_bot._get_redis", new_callable=AsyncMock, return_value=mock_redis):
            import scripts.telegram_bot as tb

            tb._redis_client = mock_redis
            from scripts.telegram_bot import redis_close

            await redis_close()
            mock_redis.aclose.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════════
# Process update
# ═══════════════════════════════════════════════════════════════════════════════


class TestProcessUpdate:
    @pytest.mark.asyncio
    async def test_unauthorized_user(self):
        with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True) as mock:
            from scripts.telegram_bot import process_update

            update = {"message": {"chat": {"id": "999999"}, "from": {"id": "999999"}, "text": "/status"}}
            await process_update(update)
            mock.assert_called_once()
            assert "доступ" in mock.call_args[0][1].lower()

    @pytest.mark.asyncio
    async def test_status_command(self):
        with patch("scripts.telegram_bot.handle_status", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_typing", new_callable=AsyncMock):
                from scripts.telegram_bot import process_update

                update = {"message": {"chat": {"id": OWNER_ID}, "from": {"id": OWNER_ID}, "text": "/status"}}
                await process_update(update)
                mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_help_command(self):
        with patch("scripts.telegram_bot.handle_help", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_typing", new_callable=AsyncMock):
                from scripts.telegram_bot import process_update

                update = {"message": {"chat": {"id": OWNER_ID}, "from": {"id": OWNER_ID}, "text": "/help"}}
                await process_update(update)
                mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_command(self):
        with patch("scripts.telegram_bot.handle_help", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_typing", new_callable=AsyncMock):
                from scripts.telegram_bot import process_update

                update = {"message": {"chat": {"id": OWNER_ID}, "from": {"id": OWNER_ID}, "text": "/start"}}
                await process_update(update)
                mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_logs_command(self):
        with patch("scripts.telegram_bot.handle_logs", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_typing", new_callable=AsyncMock):
                from scripts.telegram_bot import process_update

                update = {"message": {"chat": {"id": OWNER_ID}, "from": {"id": OWNER_ID}, "text": "/logs 50"}}
                await process_update(update)
                mock.assert_called_once()
                assert mock.call_args[0][1] == 50

    @pytest.mark.asyncio
    async def test_logs_command_default(self):
        with patch("scripts.telegram_bot.handle_logs", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_typing", new_callable=AsyncMock):
                from scripts.telegram_bot import process_update

                update = {"message": {"chat": {"id": OWNER_ID}, "from": {"id": OWNER_ID}, "text": "/logs"}}
                await process_update(update)
                mock.assert_called_once()
                assert mock.call_args[0][1] == 20

    @pytest.mark.asyncio
    async def test_pause_command_redirect(self):
        with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_typing", new_callable=AsyncMock):
                from scripts.telegram_bot import process_update

                update = {"message": {"chat": {"id": OWNER_ID}, "from": {"id": OWNER_ID}, "text": "/pause"}}
                await process_update(update)
                mock.assert_called_once()
                assert "кнопки" in mock.call_args[0][1].lower()

    @pytest.mark.asyncio
    async def test_resume_command_redirect(self):
        with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_typing", new_callable=AsyncMock):
                from scripts.telegram_bot import process_update

                update = {"message": {"chat": {"id": OWNER_ID}, "from": {"id": OWNER_ID}, "text": "/resume"}}
                await process_update(update)
                mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_run_now_command_redirect(self):
        with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_typing", new_callable=AsyncMock):
                from scripts.telegram_bot import process_update

                update = {"message": {"chat": {"id": OWNER_ID}, "from": {"id": OWNER_ID}, "text": "/run_now"}}
                await process_update(update)
                mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_typing", new_callable=AsyncMock):
                from scripts.telegram_bot import process_update

                update = {"message": {"chat": {"id": OWNER_ID}, "from": {"id": OWNER_ID}, "text": "hello"}}
                await process_update(update)
                mock.assert_called_once()
                assert "/start" in mock.call_args[0][1]

    @pytest.mark.asyncio
    async def test_callback_pause(self):
        with patch("scripts.telegram_bot.handle_pause", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock):
                with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock):
                    from scripts.telegram_bot import process_update

                    update = {
                        "callback_query": {
                            "id": "cq1",
                            "message": {"chat": {"id": OWNER_ID}, "message_id": 1},
                            "from": {"id": OWNER_ID},
                            "data": "pause:seo-agent",
                        }
                    }
                    await process_update(update)
                    mock.assert_called_once()
                    assert mock.call_args[0][1] == "seo-agent"

    @pytest.mark.asyncio
    async def test_callback_run(self):
        with patch("scripts.telegram_bot.handle_run_now", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock):
                with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock):
                    from scripts.telegram_bot import process_update

                    update = {
                        "callback_query": {
                            "id": "cq1",
                            "message": {"chat": {"id": OWNER_ID}, "message_id": 1},
                            "from": {"id": OWNER_ID},
                            "data": "run:seo-agent",
                        }
                    }
                    await process_update(update)
                    mock.assert_called_once()
                    assert mock.call_args[0][1] == "seo-agent"

    @pytest.mark.asyncio
    async def test_callback_status(self):
        with patch("scripts.telegram_bot.handle_status", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock):
                with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock):
                    from scripts.telegram_bot import process_update

                    update = {
                        "callback_query": {
                            "id": "cq1",
                            "message": {"chat": {"id": OWNER_ID}, "message_id": 1},
                            "from": {"id": OWNER_ID},
                            "data": "status",
                        }
                    }
                    await process_update(update)
                    mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_logs(self):
        with patch("scripts.telegram_bot.handle_logs", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock):
                with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock):
                    from scripts.telegram_bot import process_update

                    update = {
                        "callback_query": {
                            "id": "cq1",
                            "message": {"chat": {"id": OWNER_ID}, "message_id": 1},
                            "from": {"id": OWNER_ID},
                            "data": "logs",
                        }
                    }
                    await process_update(update)
                    mock.assert_called_once()
                    assert mock.call_args[0][1] == 20

    @pytest.mark.asyncio
    async def test_callback_help(self):
        with patch("scripts.telegram_bot.handle_help", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock):
                with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock):
                    from scripts.telegram_bot import process_update

                    update = {
                        "callback_query": {
                            "id": "cq1",
                            "message": {"chat": {"id": OWNER_ID}, "message_id": 1},
                            "from": {"id": OWNER_ID},
                            "data": "help",
                        }
                    }
                    await process_update(update)
                    mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_main_menu(self):
        with patch("scripts.telegram_bot.handle_main_menu", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock):
                with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock):
                    from scripts.telegram_bot import process_update

                    update = {
                        "callback_query": {
                            "id": "cq1",
                            "message": {"chat": {"id": OWNER_ID}, "message_id": 1},
                            "from": {"id": OWNER_ID},
                            "data": "main_menu",
                        }
                    }
                    await process_update(update)
                    mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_menu_agents(self):
        with patch("scripts.telegram_bot.handle_menu_agents", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock):
                with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock):
                    from scripts.telegram_bot import process_update

                    update = {
                        "callback_query": {
                            "id": "cq1",
                            "message": {"chat": {"id": OWNER_ID}, "message_id": 1},
                            "from": {"id": OWNER_ID},
                            "data": "menu_agents",
                        }
                    }
                    await process_update(update)
                    mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_pause_all(self):
        with patch("scripts.telegram_bot.handle_pause_all", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock):
                with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock):
                    from scripts.telegram_bot import process_update

                    update = {
                        "callback_query": {
                            "id": "cq1",
                            "message": {"chat": {"id": OWNER_ID}, "message_id": 1},
                            "from": {"id": OWNER_ID},
                            "data": "pause_all",
                        }
                    }
                    await process_update(update)
                    mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_run_all(self):
        with patch("scripts.telegram_bot.handle_run_all", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock):
                with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock):
                    from scripts.telegram_bot import process_update

                    update = {
                        "callback_query": {
                            "id": "cq1",
                            "message": {"chat": {"id": OWNER_ID}, "message_id": 1},
                            "from": {"id": OWNER_ID},
                            "data": "run_all",
                        }
                    }
                    await process_update(update)
                    mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_unauthorized(self):
        with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock, return_value=True) as mock:
            with patch("scripts.telegram_bot.api_post", new_callable=AsyncMock):
                from scripts.telegram_bot import process_update

                update = {
                    "callback_query": {
                        "id": "cq1",
                        "message": {"chat": {"id": "999999"}, "message_id": 1},
                        "from": {"id": "999999"},
                        "data": "status",
                    }
                }
                await process_update(update)
                mock.assert_called_once()
                assert "доступ" in mock.call_args[0][1].lower()

    @pytest.mark.asyncio
    async def test_empty_message(self):
        with patch("scripts.telegram_bot.send_message", new_callable=AsyncMock) as mock:
            with patch("scripts.telegram_bot.send_typing", new_callable=AsyncMock):
                from scripts.telegram_bot import process_update

                update = {"message": {"chat": {"id": OWNER_ID}, "from": {"id": OWNER_ID}}}
                await process_update(update)
                mock.assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════


class TestMain:
    def test_bot_token_check(self):
        import scripts.telegram_bot as tb

        # BOT_TOKEN may be set from env; just verify the module loaded
        assert hasattr(tb, "BOT_TOKEN")
        assert hasattr(tb, "main")

    def test_main_is_callable(self):
        import scripts.telegram_bot as tb

        assert callable(tb.main)
        assert callable(tb.polling_loop)
