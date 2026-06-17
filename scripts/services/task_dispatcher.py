#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TaskDispatcher — диспетчеризация задач между агентами.

P1-1: Выделен из Orchestrator.
Отвечает за:
- Рассылку trend-рекомендаций
- Создание analytics-задач
- Сохранение приоритетных задач
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import structlog

from scripts.services._shared import AGENT_NAMES


class TaskDispatcher:
    """Диспетчеризует задачи между агентами."""

    def __init__(self, memory_store: Any) -> None:
        self.memory = memory_store
        self.logger = structlog.get_logger("task_dispatcher")

    async def save_priority_task(self, task: Dict[str, Any]) -> None:
        """Сохраняет приоритетную задачу в очередь."""
        if self.memory:
            await self.memory.save_task(task)
        else:
            self.logger.warning("Хранилище памяти не инициализировано, задача не сохранена")

    async def dispatch_trend_recommendations(
        self,
        trend_result: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Рассылка рекомендаций от Trend Agent другим агентам.
        """
        actions = trend_result.get("recommended_actions", [])
        dispatched: List[Dict[str, Any]] = []

        pool = await self.memory._get_db_pool()
        async with pool.acquire() as conn:
            for action in actions:
                target_agent = action.get("agent")
                if target_agent not in AGENT_NAMES or target_agent == "trend_agent":
                    self.logger.warning(
                        "Пропуск рекомендации — некорректный целевой агент",
                        target_agent=target_agent,
                        action=action.get("action"),
                    )
                    continue

                await conn.execute(
                    """
                    INSERT INTO trend_recommendations 
                    (trend_id, target_agent, action, priority, deadline, confidence, trend_title, trend_description, metrics, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'pending')
                    ON CONFLICT DO NOTHING
                    """,
                    trend_result.get("trend_id"),
                    target_agent,
                    action.get("action"),
                    action.get("priority", "medium"),
                    action.get("deadline"),
                    trend_result.get("confidence"),
                    trend_result.get("title"),
                    trend_result.get("description"),
                    (json.dumps(trend_result.get("metrics", {})) if trend_result.get("metrics") else None),
                )

                task = {
                    "agent": target_agent,
                    "trend_title": trend_result.get("title"),
                    "action": action.get("action"),
                    "priority": action.get("priority"),
                }
                dispatched.append(task)

                self.logger.info(
                    "trend_recommendation_saved",
                    target_agent=target_agent,
                    trend=trend_result.get("title"),
                    priority=action.get("priority"),
                )

        return {
            "trend": trend_result.get("title"),
            "total_recommendations": len(actions),
            "dispatched": len(dispatched),
            "tasks": dispatched,
        }

    async def dispatch_analytics_tasks(
        self,
        analytics_result: Dict[str, Any],
    ) -> int:
        """
        Создание задач из рекомендаций Analytics Agent для других агентов.
        """
        tasks = analytics_result.get("tasks", [])

        if not tasks and "recommendations" in analytics_result:
            recs = analytics_result.get("recommendations", [])
            for rec in recs:
                if isinstance(rec, dict):
                    target = rec.get("executor", rec.get("target_agent", ""))
                    agent_map = {
                        "marketing": "smm_agent",
                        "content": "content_agent",
                        "seo": "seo_agent",
                        "smm": "smm_agent",
                    }
                    target_agent = agent_map.get(target, target)
                    if target_agent in AGENT_NAMES and target_agent != "analytics_agent":
                        tasks.append(
                            {
                                "target_agent": target_agent,
                                "title": rec.get("problem", rec.get("title", "")),
                                "description": f"{rec.get('cause', '')}\n\nДействие: {rec.get('action', '')}",
                                "priority": "medium",
                                "metrics": rec.get("expected_effect", {}),
                            }
                        )

        if not tasks:
            return 0

        pool = await self.memory._get_db_pool()
        saved_count = 0
        async with pool.acquire() as conn:
            for task in tasks:
                target_agent = task.get("target_agent", "")
                if target_agent not in AGENT_NAMES or target_agent == "analytics_agent":
                    continue

                await conn.execute(
                    """
                    INSERT INTO agent_tasks 
                    (source_agent, target_agent, title, description, priority, deadline, status, metrics)
                    VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7)
                    ON CONFLICT DO NOTHING
                    """,
                    "analytics_agent",
                    target_agent,
                    task.get("title", "")[:200],
                    task.get("description", "")[:2000],
                    task.get("priority", "medium"),
                    task.get("deadline"),
                    (json.dumps(task.get("metrics", {})) if task.get("metrics") else None),
                )
                saved_count += 1

        self.logger.info("analytics_tasks_dispatched", count=saved_count)
        return saved_count

    async def mark_completed_tasks(
        self,
        agent_name: str,
        agent_type: str,
        completed_actions: Optional[List[str]] = None,
    ) -> None:
        """
        Помечает trend-рекомендации и analytics-задачи как выполненные.

        P2-7: Теперь принимает completed_actions — только конкретные выполненные
        действия помечаются completed, остальные остаются pending.
        """
        if not self.memory:
            return

        if agent_type in ("smm", "seo", "content"):
            # P2-7: Если не переданы конкретные действия — не помечаем ничего
            if not completed_actions:
                self.logger.debug(
                    "no_completed_actions_provided",
                    agent=agent_name,
                    message="Skipping mark_completed — no actions to mark",
                )
                return

            # Помечаем только конкретные выполненные действия
            await self.memory.mark_trend_recommendations_completed(agent_name, completed_actions)
            self.logger.info(
                "trend_recommendations_marked_completed",
                agent=agent_name,
                count=len(completed_actions),
                actions=completed_actions,
            )

            # Analytics tasks — аналогично, только если есть результат
            analytics_tasks = await self.memory.get_analytics_tasks(agent_name, limit=10)
            if analytics_tasks:
                # Помечаем только задачи, связанные с выполненными действиями
                completed_titles = [
                    t["title"] for t in analytics_tasks if any(a in t.get("description", "") for a in completed_actions)
                ]
                if completed_titles:
                    await self.memory.mark_analytics_tasks_completed(agent_name, completed_titles)
                    self.logger.info(
                        "analytics_tasks_marked_completed",
                        agent=agent_name,
                        count=len(completed_titles),
                    )
