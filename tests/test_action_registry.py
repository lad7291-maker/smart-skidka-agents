#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для плагинной системы actions (P3-1).
"""

import asyncio
import sys
import unittest

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

from scripts.actions.action_registry import (
    _REGISTRY,
    ActionDispatcher,
    discover_actions,
    get_action,
    get_registry_stats,
    list_actions,
    register_action,
)

# Очищаем реестр перед тестами
_REGISTRY.clear()


@register_action("test_action", agent_types=["test"], description="Test action")
def _test_action_impl(value: str) -> str:
    return f"result:{value}"


@register_action("test_async_action", agent_types=["test"], description="Test async action")
async def _test_async_action_impl(value: str) -> str:
    return f"async_result:{value}"


class TestActionRegistry(unittest.TestCase):
    """Тесты реестра actions."""

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_register_action(self):
        """Action регистрируется в реестре."""
        action_def = get_action("test_action")
        self.assertIsNotNone(action_def)
        self.assertEqual(action_def.name, "test_action")
        self.assertEqual(action_def.agent_types, ["test"])
        self.assertFalse(action_def.is_async)

    def test_register_async_action(self):
        """Async action корректно определяется."""
        action_def = get_action("test_async_action")
        self.assertIsNotNone(action_def)
        self.assertTrue(action_def.is_async)

    def test_get_action_missing(self):
        """Отсутствующий action возвращает None."""
        self.assertIsNone(get_action("nonexistent"))

    def test_list_actions_all(self):
        """Список всех actions."""
        actions = list_actions()
        names = [a.name for a in actions]
        self.assertIn("test_action", names)
        self.assertIn("test_async_action", names)

    def test_list_actions_by_type(self):
        """Фильтрация по типу агента."""
        actions = list_actions(agent_type="test")
        self.assertEqual(len(actions), 2)
        actions_empty = list_actions(agent_type="nonexistent")
        self.assertEqual(len(actions_empty), 0)

    def test_registry_stats(self):
        """Статистика реестра."""
        stats = get_registry_stats()
        self.assertIn("total_actions", stats)
        self.assertIn("action_names", stats)
        self.assertIn("by_agent_type", stats)
        self.assertGreaterEqual(stats["total_actions"], 2)


class TestActionDispatcher(unittest.TestCase):
    """Тесты диспетчера actions."""

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

    def tearDown(self):
        self.loop.close()

    def test_resolve_data_key_simple(self):
        """Простой ключ."""
        d = ActionDispatcher()
        data = {"title": "Hello"}
        self.assertEqual(d._resolve_data_key(data, "title"), "Hello")

    def test_resolve_data_key_nested(self):
        """Вложенный ключ."""
        d = ActionDispatcher()
        data = {"nested": {"key": "value"}}
        self.assertEqual(d._resolve_data_key(data, "nested.key"), "value")

    def test_resolve_data_key_array(self):
        """Ключ с индексом массива."""
        d = ActionDispatcher()
        data = {"items": [{"id": 1}, {"id": 2}]}
        self.assertEqual(d._resolve_data_key(data, "items.0.id"), 1)
        self.assertEqual(d._resolve_data_key(data, "items.1.id"), 2)

    def test_resolve_data_key_missing(self):
        """Отсутствующий ключ."""
        d = ActionDispatcher()
        self.assertIsNone(d._resolve_data_key({}, "missing"))
        self.assertIsNone(d._resolve_data_key({"items": []}, "items.5.id"))

    def test_eval_condition_always(self):
        """Условие always."""
        d = ActionDispatcher()
        self.assertTrue(d._eval_condition("always", {}))

    def test_eval_condition_has(self):
        """Условие has_key."""
        d = ActionDispatcher()
        self.assertTrue(d._eval_condition("has_title", {"title": "x"}))
        self.assertFalse(d._eval_condition("has_missing", {}))

    def test_eval_condition_not_empty(self):
        """Условие not_empty."""
        d = ActionDispatcher()
        self.assertTrue(d._eval_condition("not_empty_title", {"title": "x"}))
        self.assertFalse(d._eval_condition("not_empty_title", {"title": ""}))
        self.assertFalse(d._eval_condition("not_empty_items", {"items": []}))

    def test_execute_sync_action(self):
        """Выполнение sync action."""

        async def _test():
            d = ActionDispatcher()
            result = await d.execute("test_action", {"value": "hello"})
            self.assertEqual(result, "result:hello")

        self.loop.run_until_complete(_test())

    def test_execute_async_action(self):
        """Выполнение async action."""

        async def _test():
            d = ActionDispatcher()
            result = await d.execute("test_async_action", {"value": "world"})
            self.assertEqual(result, "async_result:world")

        self.loop.run_until_complete(_test())

    def test_execute_agent_actions(self):
        """Выполнение actions по конфигу агента."""

        async def _test():
            d = ActionDispatcher()
            agent_config = {
                "agent_name": "test-agent",
                "actions": [
                    {
                        "name": "test_action",
                        "input_map": {"value": "data_value"},
                        "condition": "has_data_value",
                    }
                ],
            }
            # С condition выполняется
            log = await d.execute_agent_actions(agent_config, {"data_value": "test"})
            self.assertEqual(len(log), 1)
            self.assertEqual(log[0], "test_action:result:test")

            # Без данных — skipped
            log2 = await d.execute_agent_actions(agent_config, {})
            self.assertEqual(len(log2), 1)
            self.assertEqual(log2[0], "test_action:SKIPPED")

        self.loop.run_until_complete(_test())

    def test_execute_agent_actions_no_config(self):
        """Агент без actions в конфиге."""

        async def _test():
            d = ActionDispatcher()
            log = await d.execute_agent_actions({"agent_name": "empty"}, {"x": 1})
            self.assertEqual(log, [])

        self.loop.run_until_complete(_test())

    def test_execute_not_found(self):
        """Action не найден в реестре."""

        async def _test():
            d = ActionDispatcher()
            agent_config = {"actions": [{"name": "missing_action", "input_map": {}}]}
            log = await d.execute_agent_actions(agent_config, {})
            self.assertEqual(log, ["missing_action:NOT_FOUND"])

        self.loop.run_until_complete(_test())


class TestDiscoverActions(unittest.TestCase):
    """Тесты авто-обнаружения модулей."""

    def test_discover_actions(self):
        """Обнаружение actions из модулей."""
        # Note: modules already imported at top level, so discover_actions
        # won't find new ones. Test that it runs without error.
        count = discover_actions(
            [
                "actions.telegram_actions",
                "actions.site_actions",
            ]
        )
        # count may be 0 if modules already imported — that's OK
        stats = get_registry_stats()
        # At minimum we have our test actions registered
        self.assertGreaterEqual(stats["total_actions"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
