#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TaskDispatcher — диспетчеризация задач между агентами с зависимостями.

Отвечает за:
- Dependency graph — кто от кого зависит
- Очередь задач с зависимостями
- Рассылку рекомендаций между агентами
- Отслеживание статуса выполнения
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set

import structlog

from scripts.services._shared import AGENT_NAMES


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"  # Все зависимости выполнены, можно запускать
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class AgentTask:
    """Задача агента в цикле."""

    agent_name: str
    agent_type: str
    status: TaskStatus = TaskStatus.PENDING
    depends_on: List[str] = field(default_factory=list)  # Список agent_name, от которых зависит
    blocked_by: List[str] = field(default_factory=list)  # Кто ещё не выполнился
    output_for: List[str] = field(default_factory=list)  # Кому передаёт результат
    context: Dict[str, Any] = field(default_factory=dict)  # Данные от предыдущих агентов
    result: Dict[str, Any] = field(default_factory=dict)  # Результат выполнения
    cycle_id: str = ""


class DependencyGraph:
    """
    Граф зависимостей агентов.

    Определяет порядок выполнения: агент может запуститься только когда
    все агенты из depends_on выполнены.
    """

    # Стандартные зависимости для каждого типа агента
    DEFAULT_DEPS = {
        # trend анализирует рынок — нет зависимостей (первый)
        "trend": [],
        # feed зависит от trend (чтобы знать что скачивать)
        "feed": ["trend"],
        # analytics анализирует загруженные товары
        "analytics": ["feed"],
        # performance зависит от analytics (какие товары топовые)
        "performance": ["analytics"],
        # seo зависит от performance (какие товары приоритетные)
        "seo": ["performance"],
        # content зависит от seo (мета-данные) и trend (темы)
        "content": ["seo", "trend"],
        # smm зависит от content (что публиковать)
        "smm": ["content"],
        # email зависит от smm (что уже опубликовано) и analytics (топ товары)
        "email": ["smm", "analytics"],
    }

    # Кто получает результат от кого
    OUTPUT_CHAIN = {
        "trend": ["feed"],
        "feed": ["analytics"],
        "analytics": ["performance", "email"],
        "performance": ["seo"],
        "seo": ["content"],
        "content": ["smm"],
        "smm": ["email"],
        "email": [],
    }

    def __init__(self):
        self.logger = structlog.get_logger("dependency_graph")

    def get_dependencies(self, agent_type: str) -> List[str]:
        """Возвращает список зависимостей для агента."""
        return self.DEFAULT_DEPS.get(agent_type, [])

    def get_outputs(self, agent_type: str) -> List[str]:
        """Возвращает список агентов, которым передаётся результат."""
        return self.OUTPUT_CHAIN.get(agent_type, [])

    def build_execution_plan(self, agents: List[Any]) -> List[AgentTask]:
        """
        Строит план выполнения из списка агентов.

        Returns:
            Список AgentTask в порядке топологической сортировки
        """
        tasks = []
        agent_types_present = set()

        # Создаём задачи для всех агентов
        for agent in agents:
            agent_type = self._get_agent_type(agent.agent_name)
            agent_types_present.add(agent_type)

            deps = self.get_dependencies(agent_type)
            outputs = self.get_outputs(agent_type)

            task = AgentTask(
                agent_name=agent.agent_name,
                agent_type=agent_type,
                depends_on=deps,
                output_for=outputs,
                blocked_by=list(deps),  # Изначально заблокирован всеми зависимостями
            )
            tasks.append(task)
            self.logger.info(
                "task_created",
                agent=agent.agent_name,
                type=agent_type,
                depends_on=deps,
                output_for=outputs,
            )

        # Фильтруем зависимости — оставляем только тех, кто есть в плане
        for task in tasks:
            task.depends_on = [d for d in task.depends_on if d in agent_types_present]
            task.blocked_by = list(task.depends_on)
            if not task.blocked_by:
                task.status = TaskStatus.READY

        return tasks

    def mark_completed(self, task: AgentTask, all_tasks: List[AgentTask]) -> List[AgentTask]:
        """
        Отмечает задачу выполненной и разблокирует зависимые.

        Returns:
            Список задач, которые стали READY
        """
        task.status = TaskStatus.COMPLETED
        ready_tasks = []

        # Находим все задачи, которые ждут этого агента
        for other in all_tasks:
            if task.agent_type in other.blocked_by:
                other.blocked_by.remove(task.agent_type)
                # Копируем контекст от выполненного агента
                other.context[task.agent_type] = task.result

                self.logger.info(
                    "dependency_resolved",
                    agent=other.agent_name,
                    unblocked_by=task.agent_name,
                    remaining_deps=other.blocked_by,
                )

                # Если все зависимости выполнены — задача готова
                if not other.blocked_by and other.status == TaskStatus.PENDING:
                    other.status = TaskStatus.READY
                    ready_tasks.append(other)
                    self.logger.info(
                        "task_ready",
                        agent=other.agent_name,
                        context_sources=list(other.context.keys()),
                    )

        return ready_tasks

    def get_ready_tasks(self, tasks: List[AgentTask]) -> List[AgentTask]:
        """Возвращает задачи, которые готовы к запуску."""
        return [t for t in tasks if t.status == TaskStatus.READY]

    def get_execution_order(self, tasks: List[AgentTask]) -> List[str]:
        """Возвращает порядок выполнения для логирования."""
        return [t.agent_name for t in tasks]

    @staticmethod
    def _get_agent_type(agent_name: str) -> str:
        """Возвращает тип агента из имени."""
        return agent_name.split("-")[0] if "-" in agent_name else agent_name


class TaskDispatcher:
    """Диспетчеризует задачи между агентами с учётом зависимостей."""

    def __init__(self, memory_store: Any) -> None:
        self.memory = memory_store
        self.logger = structlog.get_logger("task_dispatcher")
        self.graph = DependencyGraph()
        self.current_tasks: List[AgentTask] = []
        self.cycle_id: str = ""

    async def initialize_cycle(self, agents: List[Any], cycle_id: str) -> List[AgentTask]:
        """
        Инициализирует цикл — строит граф зависимостей.

        Returns:
            Список задач в порядке выполнения
        """
        self.cycle_id = cycle_id
        self.current_tasks = self.graph.build_execution_plan(agents)

        ready = self.graph.get_ready_tasks(self.current_tasks)
        self.logger.info(
            "cycle_initialized",
            cycle_id=cycle_id,
            total_agents=len(agents),
            ready_now=len(ready),
            execution_order=self.graph.get_execution_order(self.current_tasks),
        )

        return ready

    async def complete_task(self, agent_name: str, result: Dict[str, Any]) -> List[AgentTask]:
        """
        Отмечает задачу выполненной и возвращает следующие готовые задачи.

        Args:
            agent_name: Имя выполненного агента
            result: Результат работы агента

        Returns:
            Список задач, которые стали READY
        """
        task = self._find_task(agent_name)
        if not task:
            self.logger.warning("task_not_found", agent=agent_name)
            return []

        task.result = result
        ready_tasks = self.graph.mark_completed(task, self.current_tasks)

        self.logger.info(
            "task_completed",
            agent=agent_name,
            type=task.agent_type,
            new_ready_tasks=[t.agent_name for t in ready_tasks],
            cycle_progress=self._get_progress(),
        )

        return ready_tasks

    async def get_task_context(self, agent_name: str) -> Dict[str, Any]:
        """Возвращает контекст (данные от предыдущих агентов) для задачи."""
        task = self._find_task(agent_name)
        if not task:
            return {}
        return task.context

    def _find_task(self, agent_name: str) -> Optional[AgentTask]:
        """Находит задачу по имени агента."""
        for task in self.current_tasks:
            if task.agent_name == agent_name:
                return task
        return None

    def _get_progress(self) -> Dict[str, Any]:
        """Возвращает прогресс выполнения цикла."""
        total = len(self.current_tasks)
        completed = sum(1 for t in self.current_tasks if t.status == TaskStatus.COMPLETED)
        ready = sum(1 for t in self.current_tasks if t.status == TaskStatus.READY)
        pending = sum(1 for t in self.current_tasks if t.status == TaskStatus.PENDING)

        return {
            "total": total,
            "completed": completed,
            "ready": ready,
            "pending": pending,
            "percent": round(completed / total * 100, 1) if total > 0 else 0,
        }

    def is_cycle_complete(self) -> bool:
        """Проверяет, все ли задачи выполнены."""
        return all(
            t.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED, TaskStatus.FAILED) for t in self.current_tasks
        )

    # ─── Legacy methods (backward compatibility) ───────────────────

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
        """Рассылка рекомендаций от Trend Agent другим агентам."""
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
        """Создание задач из рекомендаций Analytics Agent для других агентов."""
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
        """Помечает trend-рекомендации и analytics-задачи как выполненные."""
        if not self.memory:
            return

        if agent_type in ("smm", "seo", "content"):
            if not completed_actions:
                self.logger.debug(
                    "no_completed_actions_provided",
                    agent=agent_name,
                    message="Skipping mark_completed — no actions to mark",
                )
                return

            await self.memory.mark_trend_recommendations_completed(agent_name, completed_actions)
            self.logger.info(
                "trend_recommendations_marked_completed",
                agent=agent_name,
                count=len(completed_actions),
                actions=completed_actions,
            )

            analytics_tasks = await self.memory.get_analytics_tasks(agent_name, limit=10)
            if analytics_tasks:
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
