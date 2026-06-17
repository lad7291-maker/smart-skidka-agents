#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                   ACTION REGISTRY — Плагинная система                ║
║                         smart-skidka.ru                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  Реестр действий агентов. Позволяет динамически регистрировать       ║
║  и вызывать actions без хардкода в orchestrator.py.                  ║
║                                                                      ║
║  P3-1: Плагинная система для actions                                 ║
╚══════════════════════════════════════════════════════════════════════╝

Использование:
    # Регистрация action (в модуле actions)
    from actions.action_registry import register_action
    
    @register_action("post_discount", agent_types=["smm"])
    async def post_discount(product: dict) -> bool:
        ...

    # Вызов из orchestrator (динамически по конфигу)
    from actions.action_registry import ActionDispatcher
    dispatcher = ActionDispatcher()
    result = await dispatcher.execute("post_discount", {"product": {...}})
"""

from __future__ import annotations

import asyncio
import functools
import importlib
import inspect
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

import structlog

logger = structlog.get_logger("action_registry")


# ═══════════════════════════════════════════════════════════════════════════════
# Реестр действий
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ActionDef:
    """Определение зарегистрированного action."""
    name: str
    func: Callable
    agent_types: List[str] = field(default_factory=list)
    description: str = ""
    is_async: bool = False


# Глобальный реестр: имя action → ActionDef
_REGISTRY: Dict[str, ActionDef] = {}


def register_action(
    name: str,
    agent_types: Optional[List[str]] = None,
    description: str = "",
):
    """
    Декоратор для регистрации action в глобальном реестре.

    Args:
        name: Уникальное имя action (например, "post_discount")
        agent_types: Список типов агентов, которым разрешён этот action
        description: Описание для документации

    Example:
        @register_action("update_meta_tags", agent_types=["seo"])
        def update_meta_tags(title: str, description: str, keywords: str = "") -> bool:
            ...
    """
    def decorator(func: Callable) -> Callable:
        is_async = asyncio.iscoroutinefunction(func)
        _REGISTRY[name] = ActionDef(
            name=name,
            func=func,
            agent_types=agent_types or [],
            description=description or func.__doc__ or "",
            is_async=is_async,
        )
        logger.debug("action_registered", name=name, agent_types=agent_types, is_async=is_async)
        return func
    return decorator


def get_action(name: str) -> Optional[ActionDef]:
    """Возвращает ActionDef по имени или None."""
    return _REGISTRY.get(name)


def list_actions(agent_type: Optional[str] = None) -> List[ActionDef]:
    """
    Возвращает список зарегистрированных actions.

    Args:
        agent_type: Если задан — фильтрует по типу агента
    """
    if agent_type:
        return [a for a in _REGISTRY.values() if agent_type in a.agent_types]
    return list(_REGISTRY.values())


def discover_actions(modules: Optional[List[str]] = None) -> int:
    """
    Авто-обнаружение action-модулей через импорт.

    Args:
        modules: Список имён модулей для импорта (например, ["actions.telegram_actions"]).
                 Если None — импортирует все стандартные модули.

    Returns:
        Количество зарегистрированных actions
    """
    default_modules = [
        "actions.telegram_actions",
        "actions.site_actions",
        "actions.browser_actions",
        "actions.data_tools",
    ]
    to_import = modules or default_modules

    registered_before = len(_REGISTRY)
    for module_name in to_import:
        try:
            importlib.import_module(module_name)
            logger.debug("actions_discovered", module=module_name)
        except Exception as e:
            logger.warning("action_module_import_failed", module=module_name, error=str(e))

    registered_after = len(_REGISTRY)
    logger.info("actions_discovery_complete", count=registered_after - registered_before)
    return registered_after - registered_before


# ═══════════════════════════════════════════════════════════════════════════════
# ActionDispatcher — диспетчер выполнения actions
# ═══════════════════════════════════════════════════════════════════════════════

class ActionDispatcher:
    """
    Диспетчер для выполнения actions по конфигурации агента.

    Читает список actions из JSON-конфигурации агента, маппит поля
    результата LLM на аргументы функций и выполняет.
    """

    def __init__(self) -> None:
        self.logger = structlog.get_logger("action_dispatcher")

    async def execute(
        self,
        action_name: str,
        params: Dict[str, Any],
        agent_type: Optional[str] = None,
    ) -> Any:
        """
        Выполняет один action по имени с заданными параметрами.

        Args:
            action_name: Имя зарегистрированного action
            params: Словарь аргументов для функции
            agent_type: Тип агента для RBAC-проверки (например, "seo", "smm")

        Returns:
            Результат выполнения action

        Raises:
            ValueError: Если action не найден
            PermissionError: Если агенту не разрешён этот action
        """
        action_def = get_action(action_name)
        if action_def is None:
            raise ValueError(f"Action '{action_name}' not found in registry. "
                           f"Available: {list(_REGISTRY.keys())}")

        # RBAC-проверка: агент должен быть в списке разрешённых типов
        if agent_type is not None and action_def.agent_types:
            if agent_type not in action_def.agent_types:
                self.logger.warning(
                    "rbac_denied",
                    action=action_name,
                    agent_type=agent_type,
                    allowed=action_def.agent_types,
                )
                raise PermissionError(
                    f"Agent type '{agent_type}' is not allowed to execute action '{action_name}'. "
                    f"Allowed types: {action_def.agent_types}"
                )

        self.logger.debug("executing_action", name=action_name, params_keys=list(params.keys()), agent_type=agent_type)

        # Фильтруем параметры — оставляем только те, что принимает функция
        sig = inspect.signature(action_def.func)
        valid_params = {}
        for param_name in sig.parameters:
            if param_name in params:
                valid_params[param_name] = params[param_name]

        # Вызов функции (async или sync)
        if action_def.is_async:
            return await action_def.func(**valid_params)
        else:
            # Sync функции из async кода — запускаем в thread pool
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(None, functools.partial(action_def.func, **valid_params))

    async def execute_agent_actions(
        self,
        agent_config: Dict[str, Any],
        agent_data: Dict[str, Any],
    ) -> List[str]:
        """
        Выполняет все actions для агента согласно его конфигурации.

        Args:
            agent_config: Конфигурация агента (из JSON)
            agent_data: Данные результата LLM (result["data"])

        Returns:
            Список строк лога действий
        """
        action_log: List[str] = []
        actions_config = agent_config.get("actions", [])

        if not actions_config:
            self.logger.debug("no_actions_configured", agent=agent_config.get("agent_name"))
            return action_log

        for action_cfg in actions_config:
            action_name = action_cfg.get("name")
            if not action_name:
                continue

            # Проверяем, что action зарегистрирован
            action_def = get_action(action_name)
            if action_def is None:
                action_log.append(f"{action_name}:NOT_FOUND")
                self.logger.warning("action_not_found", name=action_name)
                continue

            # Формируем параметры из data по input_map
            input_map = action_cfg.get("input_map", {})
            params: Dict[str, Any] = {}

            for param_name, data_key in input_map.items():
                # data_key может быть простым ключом или путём (items.0.id)
                value = self._resolve_data_key(agent_data, data_key)
                if value is not None:
                    params[param_name] = value

            # Дополнительные статические параметры
            static_params = action_cfg.get("params", {})
            params.update(static_params)

            # Проверяем condition (если задано)
            condition = action_cfg.get("condition")
            if condition and not self._eval_condition(condition, agent_data):
                action_log.append(f"{action_name}:SKIPPED")
                continue

            # Определяем тип агента из конфигурации для RBAC
            agent_type = agent_config.get("agent_type") or agent_config.get("agent_name", "").split("-")[0]

            # Выполняем action с RBAC-проверкой
            try:
                result = await self.execute(action_name, params, agent_type=agent_type)
                action_log.append(f"{action_name}:{result}")
            except PermissionError as e:
                action_log.append(f"{action_name}:RBAC_DENIED:{str(e)[:50]}")
                self.logger.warning("action_execution_denied", name=action_name, agent_type=agent_type, error=str(e))
            except Exception as e:
                action_log.append(f"{action_name}:ERROR:{str(e)[:50]}")
                self.logger.error("action_execution_failed", name=action_name, error=str(e))

        return action_log

    def _resolve_data_key(self, data: Dict[str, Any], key: str) -> Any:
        """
        Извлекает значение из data по ключу с поддержкой вложенности.

        Examples:
            "title" → data["title"]
            "items.0.id" → data["items"][0]["id"]
        """
        if not key:
            return None

        parts = key.split(".")
        current: Any = data

        for part in parts:
            if current is None:
                return None
            if isinstance(current, dict):
                current = current.get(part)
            elif isinstance(current, list):
                try:
                    idx = int(part)
                    current = current[idx] if 0 <= idx < len(current) else None
                except (ValueError, IndexError):
                    return None
            else:
                return None

        return current

    def _eval_condition(self, condition: str, data: Dict[str, Any]) -> bool:
        """
        Простая оценка условия.

        Поддерживает: key_exists, key_not_empty
        """
        if condition == "always":
            return True
        if condition.startswith("has_"):
            key = condition[4:]
            return self._resolve_data_key(data, key) is not None
        if condition.startswith("not_empty_"):
            key = condition[10:]
            val = self._resolve_data_key(data, key)
            return val is not None and val != [] and val != ""
        return True


# ═══════════════════════════════════════════════════════════════════════════════
# Удобные функции
# ═══════════════════════════════════════════════════════════════════════════════

def get_registry_stats() -> Dict[str, Any]:
    """Возвращает статистику реестра."""
    by_agent_type: Dict[str, List[str]] = {}
    for action_def in _REGISTRY.values():
        for at in action_def.agent_types:
            by_agent_type.setdefault(at, []).append(action_def.name)

    return {
        "total_actions": len(_REGISTRY),
        "action_names": sorted(_REGISTRY.keys()),
        "by_agent_type": {k: sorted(v) for k, v in by_agent_type.items()},
    }
