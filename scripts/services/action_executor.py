#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ActionExecutor — выполнение actions агентов.

P1-1: Выделен из Orchestrator.
Отвечает за:
- File operations (safe_write)
- Plugin actions через ActionDispatcher
- Legacy hardcoded actions (fallback)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import structlog

from scripts.actions.site_actions import (
    add_badge,
    create_category_page,
    prioritize_products,
    update_item_description,
    update_meta_tags,
)
from scripts.actions.telegram_actions import post_discount, post_to_channel


class ActionExecutor:
    """Выполняет действия агентов: file ops, plugin actions, legacy fallback."""

    def __init__(self) -> None:
        self.logger = structlog.get_logger("action_executor")

    async def execute_actions(
        self,
        agent_name: str,
        agent_type: str,
        data: Dict[str, Any],
        agent_config: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
        """
        Выполняет все действия агента.

        Args:
            agent_name: Имя агента
            agent_type: Тип агента
            data: Данные результата
            agent_config: Конфигурация агента (для plugin actions)

        Returns:
            Лог выполненных действий
        """
        action_log: List[str] = []

        # File operations
        file_ops = data.get("file_ops", data.get("files", []))
        if file_ops:
            file_log = await self._execute_file_ops(agent_name, file_ops)
            action_log.extend(file_log)

        # Plugin actions из конфига
        if agent_config and agent_config.get("actions"):
            plugin_log = await self._execute_plugin_actions(agent_config, data)
            action_log.extend(plugin_log)
        else:
            # Legacy fallback
            legacy_log = await self._execute_legacy_actions(agent_type, data)
            action_log.extend(legacy_log)

        return action_log

    async def _execute_file_ops(
        self,
        agent_name: str,
        file_ops: Any,
    ) -> List[str]:
        """Выполняет файловые операции."""
        action_log: List[str] = []

        try:
            from scripts.safe_project_context import safe_write_file, validate_write

            if isinstance(file_ops, list):
                for op in file_ops[:5]:  # макс 5 операций за раз
                    if isinstance(op, dict):
                        path = op.get("path", op.get("file", ""))
                        content = op.get("content", "")
                        mode = op.get("mode", "overwrite")
                        if path and content:
                            val = validate_write(path, mode)
                            if not val["valid"]:
                                action_log.append(f"file:{path}:BLOCKED")
                                self.logger.warning(
                                    "file_op_blocked",
                                    agent=agent_name,
                                    path=path,
                                    reason=val["error"],
                                )
                                continue
                            res = safe_write_file(path, content, append=(mode == "append"))
                            action_log.append(f"file:{path}:{res.get('success', False)}")
            elif isinstance(file_ops, dict):
                path = file_ops.get("path", file_ops.get("file", ""))
                content = file_ops.get("content", "")
                mode = file_ops.get("mode", "overwrite")
                if path and content:
                    val = validate_write(path, mode)
                    if not val["valid"]:
                        action_log.append(f"file:{path}:BLOCKED")
                        self.logger.warning(
                            "file_op_blocked",
                            agent=agent_name,
                            path=path,
                            reason=val["error"],
                        )
                    else:
                        res = safe_write_file(path, content, append=(mode == "append"))
                        action_log.append(f"file:{path}:{res.get('success', False)}")
        except Exception as e:
            self.logger.error("file_ops_failed", agent=agent_name, error=str(e))

        return action_log

    async def _execute_plugin_actions(
        self,
        agent_config: Dict[str, Any],
        data: Dict[str, Any],
    ) -> List[str]:
        """Выполняет plugin actions через ActionDispatcher."""
        action_log: List[str] = []

        try:
            from scripts.actions.action_registry import (
                ActionDispatcher,
                discover_actions,
            )

            discover_actions()
            dispatcher = ActionDispatcher()
            plugin_log = await dispatcher.execute_agent_actions(agent_config, data)
            action_log.extend(plugin_log)
        except Exception as e:
            self.logger.error("plugin_actions_failed", error=str(e))

        return action_log

    async def _execute_legacy_actions(
        self,
        agent_type: str,
        data: Dict[str, Any],
    ) -> List[str]:
        """
        P3-1: Fallback hardcoded actions для агентов без конфигурации actions.
        """
        action_log: List[str] = []

        if agent_type == "smm":
            # LLM может вернуть {"post": {...}} (единственное число) или {"posts": [...]}
            raw_post = data.get("post")
            posts = data.get("posts", data.get("content", []))
            if raw_post and isinstance(raw_post, dict):
                # Одиночный post — оборачиваем в список
                posts = [raw_post]
            elif isinstance(posts, dict):
                # Одиночный post под ключом posts/content
                posts = [posts]
            if isinstance(posts, list):
                for post in posts[:3]:
                    if isinstance(post, dict):
                        ok = await post_discount(post)
                    else:
                        ok = await post_to_channel(str(post))
                    action_log.append(f"tg_post:{ok}")
            elif isinstance(posts, str):
                ok = await post_to_channel(posts)
                action_log.append(f"tg_post:{ok}")

        elif agent_type == "seo":
            title = data.get("title", data.get("meta_title", ""))
            desc = data.get("description", data.get("meta_description", ""))
            keywords = data.get("keywords", "")
            if title and desc:
                ok = update_meta_tags(title, desc, keywords)
                action_log.append(f"meta_updated:{ok}")

        elif agent_type == "performance":
            top_ids = data.get("top_products", data.get("prioritize", []))
            if top_ids:
                ok = prioritize_products(top_ids)
                action_log.append(f"prioritized:{ok}")
            # Add badges for featured products
            featured = data.get("featured_products", [])
            for fid in featured[:10]:
                ok = add_badge(str(fid), "ХИТ")
                action_log.append(f"badge:{fid}:{ok}")
            new_items = data.get("new_products", [])
            for nid in new_items[:5]:
                ok = add_badge(str(nid), "NEW")
                action_log.append(f"badge:new:{nid}:{ok}")
            top_items = data.get("top_rated", [])
            for tid in top_items[:5]:
                ok = add_badge(str(tid), "ТОП")
                action_log.append(f"badge:top:{tid}:{ok}")
            hot_items = data.get("hot_discounts", data.get("hot", []))
            for hid in hot_items[:10]:
                ok = add_badge(str(hid), "🔥")
                action_log.append(f"badge:hot:{hid}:{ok}")

        elif agent_type == "analytics":
            # Analytics agent выдаёт рекомендации; применяем приоритизацию топ-товаров
            top_ids = data.get("top_products", [])
            if top_ids:
                ok = prioritize_products(top_ids)
                action_log.append(f"analytics_prioritized:{ok}")
            recommendations = data.get("recommendations", [])
            for rec in recommendations[:5]:
                if isinstance(rec, dict):
                    action_log.append(f"analytics_rec:{rec.get('action')}:{rec.get('category', 'none')}")

        elif agent_type == "email":
            # Email agent сохраняет HTML через file_ops; дополнительно приоритизирует товары
            products = data.get("products", [])
            if products:
                ok = prioritize_products(products)
                action_log.append(f"email_prioritized:{ok}")

        elif agent_type == "content":
            cat = data.get("category", data.get("page_category", ""))
            html = data.get("html", data.get("content", ""))
            if cat and html:
                ok = create_category_page(cat, html)
                action_log.append(f"category_page:{cat}:{ok}")
            items = data.get("items", data.get("product_descriptions", []))
            if isinstance(items, list):
                for item in items[:10]:  # обновляем до 10 товаров
                    if isinstance(item, dict):
                        iid = item.get("id", item.get("itemId", ""))
                        desc = item.get("description", "")
                        if iid and desc:
                            ok = update_item_description(str(iid), desc)
                            action_log.append(f"item_desc:{iid}:{ok}")

        return action_log
