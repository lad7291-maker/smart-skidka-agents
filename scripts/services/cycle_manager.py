#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CycleManager — управление жизненным циклом агентов.

P1-1: Выделен из Orchestrator.
Отвечает за:
- Инициализацию компонентов
- Загрузку агентов
- Запуск циклов (run_cycle)
- Валидацию результатов
- Обработку ошибок
- Feedback loop
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock

from scripts.services._shared import _get_agent_type

if False:  # noqa: F821 workaround — flake8 doesn't see nested imports
    from scripts.orchestrator import AgentConfig, AgentRunner, LLMClient

import structlog

# P1-1: Избегаем циклических зависимостей — константы дублируем
DEFAULT_CYCLE_INTERVAL: int = int(os.getenv("CYCLE_INTERVAL", "3600"))
DEFAULT_LLM_MODEL: str = os.getenv("DEFAULT_LLM_MODEL", "deepseek/deepseek-chat-v3.1")


class CycleManager:
    """Управляет жизненным циклом агентов."""

    def __init__(
        self,
        config_path: str = "./configs",
        db_url: Optional[str] = None,
        redis_url: Optional[str] = None,
    ) -> None:
        self.config_path: str = config_path
        self.db_url: str = db_url or os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/agents")
        self.redis_url: str = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379")

        self.llm_client: Optional["Any"] = None
        self.memory: Optional["Any"] = None
        self.reporter: Optional["Any"] = None
        self.validator: Optional["Any"] = None

        self.agents: List["Any"] = []
        self.agent_runners: Dict[str, "Any"] = {}
        self.running: bool = False
        self.paused_agents: set = set()

        self.cycle_count: int = 0
        self.total_errors: int = 0
        self.start_time: Optional[datetime] = None

        self.logger = structlog.get_logger("cycle_manager")

    async def _get_last_run_time(self, agent_name: str) -> Optional[datetime]:
        """Возвращает время последнего успешного запуска агента из БД."""
        if not self.memory:
            return None
        try:
            pool = await self.memory._get_db_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    """SELECT MAX(created_at) as last_run
                        FROM agent_results
                        WHERE agent_name = $1 AND status = 'success'""",
                    agent_name,
                )
                if row and row["last_run"]:
                    return row["last_run"]
        except Exception as e:
            self.logger.warning("Failed to get last run time", agent=agent_name, error=str(e))
        return None

    async def _should_run_agent(self, agent: "AgentConfig") -> bool:
        """Проверяет, пора ли запускать агента (учитывая interval из конфига)."""
        schedule = agent.get_schedule()
        interval = schedule.get("interval", DEFAULT_CYCLE_INTERVAL)
        # Handle mock objects in tests — MagicMock from unittest.mock
        if type(interval).__name__ == "MagicMock" or type(interval).__name__ == "Mock":
            interval = DEFAULT_CYCLE_INTERVAL
        run_once = schedule.get("run_once", False)

        # Если run_once и уже запускался — пропускаем
        if run_once:
            last_run = await self._get_last_run_time(agent.agent_name)
            if last_run:
                self.logger.info("Agent run_once already executed", agent=agent.agent_name)
                return False

        # Проверяем interval
        last_run = await self._get_last_run_time(agent.agent_name)
        if not last_run:
            return True  # Никогда не запускался

        elapsed = (datetime.now(timezone.utc) - last_run).total_seconds()
        should_run = elapsed >= interval

        if not should_run:
            self.logger.info(
                "Agent skipped — interval not elapsed",
                agent=agent.agent_name,
                elapsed_seconds=int(elapsed),
                interval_seconds=interval,
            )
        return should_run

    async def initialize(self) -> None:
        """Инициализирует все компоненты."""
        # P1-1: Ленивый импорт для избежания циклических зависимостей
        from scripts.orchestrator import (
            AgentConfig,
            AgentRunner,
            LLMClient,
            MemoryStore,
            ResultValidator,
        )

        self.logger.info("Инициализация CycleManager")

        self.llm_client = LLMClient(
            api_key=os.getenv("LLM_API_KEY"),
            model=os.getenv("DEFAULT_LLM_MODEL", DEFAULT_LLM_MODEL),
            base_url=os.getenv("LLM_API_URL"),
        )

        self.memory = MemoryStore(self.db_url, self.redis_url)
        await self.memory.init_schema()

        self.reporter = None
        self.validator = ResultValidator(rules={})

        await self.load_agents()

        self.logger.info("CycleManager инициализирован", agents_count=len(self.agents))

    async def load_agents(self) -> List["Any"]:
        """Загружает конфигурации всех агентов."""
        # P1-1: Ленивый импорт для избежания циклических зависимостей
        from scripts.orchestrator import AgentConfig, AgentRunner, LLMClient

        config_dir = Path(self.config_path)
        if not config_dir.exists():
            self.logger.warning("Директория конфигураций не найдена", path=str(config_dir))
            config_dir.mkdir(parents=True, exist_ok=True)
            return []

        self.agents = []
        self.agent_runners = {}

        for config_file in sorted(config_dir.glob("*.json")):
            agent_name = config_file.stem
            # Skip non-agent config files (schema, secrets, backups, etc.)
            if agent_name in ("agent-config.schema", "secrets.enc") or agent_name.endswith(".bak"):
                continue
            try:
                config = AgentConfig(agent_name, str(config_dir))
                config.load_config()

                if not config.is_enabled():
                    self.logger.info("Агент отключён", agent=agent_name)
                    continue

                self.agents.append(config)

                # P1-X: Приоритет выбора модели:
                # 1. Env-переменная агента (SEO_AGENT_MODEL)
                # 2. Модель из конфига агента (llm_settings.model)
                # 3. Глобальная DEFAULT_LLM_MODEL
                # 4. Встроенный default
                config_llm = config.get_llm_settings()
                agent_model = os.getenv(
                    f"{agent_name.upper().replace('-', '_')}_MODEL",
                    config_llm.get("model", os.getenv("DEFAULT_LLM_MODEL", DEFAULT_LLM_MODEL)),
                )
                agent_llm = LLMClient(
                    api_key=os.getenv("LLM_API_KEY"),
                    model=agent_model,
                    base_url=os.getenv("LLM_API_URL"),
                )
                self.agent_runners[agent_name] = AgentRunner(config, agent_llm)

                self.logger.info("Агент загружен", agent=agent_name, model=agent_model)

            except Exception as e:
                self.logger.error("Ошибка загрузки агента", agent=agent_name, error=str(e))

        self.logger.info("Загрузка агентов завершена", total=len(self.agents))
        return self.agents

    async def run_cycle(
        self,
        action_executor: Any,
        task_dispatcher: Any,
        critic_audit_fn: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Выполняет один цикл — запускает всех агентов.

        Args:
            action_executor: ActionExecutor для выполнения действий
            task_dispatcher: TaskDispatcher для задач
            critic_audit_fn: Функция аудита (опционально)
        """
        cycle_id = f"cycle-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.cycle_count += 1

        self.logger.info(
            "=== НАЧАЛО ЦИКЛА ===",
            cycle_id=cycle_id,
            cycle_number=self.cycle_count,
            agents_count=len(self.agents),
        )

        cycle_start = time.monotonic()
        cycle_results: List[Dict[str, Any]] = []
        cycle_errors: List[str] = []

        # Запись о начале цикла
        if self.memory:
            pool = await self.memory._get_db_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO orchestrator_cycles (cycle_id, agents_count) VALUES ($1, $2)",
                    cycle_id,
                    len(self.agents),
                )

        # P1-2: Параллельный запуск агентов через asyncio.gather() с Semaphore
        # Приоритезация: trend → seo/smm/performance → analytics → email → content
        semaphore = asyncio.Semaphore(int(os.getenv("MAX_PARALLEL_AGENTS", "3")))

        async def _run_with_semaphore(agent_name: str) -> Dict[str, Any]:
            async with semaphore:
                agent_start = time.monotonic()
                try:
                    result = await self._run_agent(
                        agent_name,
                        action_executor,
                        task_dispatcher,
                    )
                    agent_elapsed = (time.monotonic() - agent_start) * 1000
                    return {
                        "agent_name": agent_name,
                        "success": result["success"],
                        "elapsed_ms": agent_elapsed,
                        "validation_score": result.get("validation", {}).get("score", 0.0),
                        "actions": result.get("actions", []),
                        "result": result.get("data", {}),
                        "error": result.get("error", ""),
                    }
                except Exception as e:
                    agent_elapsed = (time.monotonic() - agent_start) * 1000
                    self.logger.error("Критическая ошибка агента", agent=agent_name, error=str(e))
                    await self.handle_failure(agent_name, str(e), {})
                    return {
                        "agent_name": agent_name,
                        "success": False,
                        "elapsed_ms": agent_elapsed,
                        "error": str(e),
                    }

        # Группируем по приоритету
        priority_order = {
            "trend": 0,
            "seo": 1,
            "smm": 1,
            "performance": 1,
            "analytics": 2,
            "email": 3,
            "content": 4,
        }
        sorted_agents = sorted(
            self.agents,
            key=lambda a: priority_order.get(_get_agent_type(a.agent_name), 99),
        )

        # P1-20: Per-agent scheduling — фильтруем агентов по interval
        due_agents = []
        for agent in sorted_agents:
            should_run = await self._should_run_agent(agent)
            if should_run:
                due_agents.append(agent)
            else:
                self.logger.info(
                    "Agent skipped by schedule",
                    agent=agent.agent_name,
                )

        if not due_agents:
            self.logger.info("No agents due for this cycle")
            return {
                "cycle_id": cycle_id,
                "results": [],
                "duration_ms": 0,
                "errors": [],
                "timestamp": datetime.now().isoformat(),
                "critic_report": None,
            }

        # Запускаем только due агентов параллельно (с семафором на N одновременных)
        agent_tasks = [_run_with_semaphore(a.agent_name) for a in due_agents]
        results = await asyncio.gather(*agent_tasks, return_exceptions=True)

        # Обрабатываем результаты
        for r in results:
            if isinstance(r, Exception):
                self.logger.error("Agent task raised exception", error=str(r))
                self.total_errors += 1
                cycle_errors.append(str(r))
                continue
            cycle_results.append(r)
            if not r["success"]:
                cycle_errors.append(f"{r['agent_name']}: {r.get('error', '')}")
                self.total_errors += 1
            self.logger.info(
                "Агент завершён",
                agent=r["agent_name"],
                success=r["success"],
                elapsed_ms=round(r["elapsed_ms"], 2),
            )

        # Итоги цикла
        cycle_duration = (time.monotonic() - cycle_start) * 1000
        success_count = sum(1 for r in cycle_results if r["success"])

        # Обновление записи о цикле
        if self.memory:
            pool = await self.memory._get_db_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE orchestrator_cycles
                    SET completed_at = NOW(), status = $1, errors_count = $2
                    WHERE cycle_id = $3
                    """,
                    "completed" if not cycle_errors else "completed_with_errors",
                    len(cycle_errors),
                    cycle_id,
                )

        # Critic audit
        critic_report = None
        if critic_audit_fn:
            critic_report = await critic_audit_fn(cycle_id, cycle_results)

        # Отправка сводки
        if self.reporter:
            await self.reporter.send_summary(
                {
                    "cycle_id": cycle_id,
                    "results": cycle_results,
                    "duration_ms": cycle_duration,
                }
            )

        self.logger.info(
            "=== ЦИКЛ ЗАВЕРШЁН ===",
            cycle_id=cycle_id,
            duration_ms=round(cycle_duration, 2),
            success=success_count,
            failed=len(cycle_results) - success_count,
        )

        return {
            "cycle_id": cycle_id,
            "results": cycle_results,
            "duration_ms": cycle_duration,
            "errors": cycle_errors,
            "timestamp": datetime.now().isoformat(),
            "critic_report": critic_report,
        }

    async def _run_agent(
        self,
        agent_name: str,
        action_executor: Any,
        task_dispatcher: Any,
    ) -> Dict[str, Any]:
        """Запускает одного агента."""
        # Проверка паузы
        if self.memory:
            try:
                redis = await self.memory._get_redis()
                paused = await redis.get(f"agent:pause:{agent_name}")
                if paused:
                    self.logger.info("Агент на паузе", agent=agent_name)
                    return {
                        "success": True,
                        "data": {"status": "paused_by_user"},
                        "actions": ["paused"],
                    }
            except Exception:
                pass

            # Срочный запуск
            try:
                redis = await self.memory._get_redis()
                run_now = await redis.get(f"agent:run_now:{agent_name}")
                if run_now:
                    await redis.delete(f"agent:run_now:{agent_name}")
                    self.logger.info("Срочный запуск агента", agent=agent_name)
            except Exception:
                pass

        # Контекст
        context = {}
        if self.memory:
            context = await self.memory.get_context(agent_name)

            # Feedback loop
            try:
                feedback = await self._get_feedback_for_agent(agent_name, limit=5)
                if feedback:
                    context["feedback"] = feedback
            except Exception as e:
                self.logger.warning("feedback_loop_failed", agent=agent_name, error=str(e))

        # Запуск
        runner = self.agent_runners.get(agent_name)
        if not runner:
            self.logger.warning("Раннер не найден", agent=agent_name)
            return {"success": False, "error": "Runner not found", "data": {}}

        result = await runner.run(context=context)

        # Retry
        if not result["success"]:
            self.logger.info("Повторная попытка", agent=agent_name)
            result = await runner.retry(
                previous_result=result,
                error=result.get("error", "Unknown error"),
            )

        # Валидация
        if result["success"] and self.validator:
            agent_type = _get_agent_type(agent_name)
            validation = self.validator.validate(result["data"], agent_type)
            result["validation"] = {
                "status": validation.status.value,
                "score": validation.score,
                "errors": validation.errors,
                "warnings": validation.warnings,
            }
            result["validation_result"] = validation

            # Trend recommendations
            if agent_name == "trend_agent" and validation.is_valid:
                dispatch_result = await task_dispatcher.dispatch_trend_recommendations(result["data"])
                self.logger.info("trend_recommendations_dispatched", **dispatch_result)

            # Analytics tasks
            if agent_name == "analytics_agent" and validation.is_valid:
                task_count = await task_dispatcher.dispatch_analytics_tasks(result["data"])
                self.logger.info("analytics_tasks_dispatched", count=task_count)

        # Actions
        if result["success"] and action_executor:
            try:
                agent_config_obj = next((a for a in self.agents if a.agent_name == agent_name), None)
                agent_type = _get_agent_type(agent_name)
                action_log = await action_executor.execute_actions(
                    agent_name,
                    agent_type,
                    result.get("data", {}),
                    agent_config_obj._config if agent_config_obj else None,
                )
                if action_log:
                    result["actions"] = action_log
                    self.logger.info("Agent actions executed", agent=agent_name, actions=action_log)

                # Mark tasks completed
                # P2-7: Передаём только реально выполненные actions
                completed_actions = result.get("actions", [])
                if isinstance(completed_actions, list) and completed_actions:
                    # Извлекаем имена выполненных actions
                    action_names = []
                    for a in completed_actions:
                        if isinstance(a, dict):
                            name = a.get("name") or a.get("action")
                            if name:
                                action_names.append(name)
                        elif isinstance(a, str):
                            action_names.append(a)
                    if action_names:
                        await task_dispatcher.mark_completed_tasks(
                            agent_name, agent_type, completed_actions=action_names
                        )
            except Exception as e:
                self.logger.error("Action execution failed", agent=agent_name, error=str(e))

        # Сохранение (после выполнения actions, чтобы actions попали в БД)
        if self.memory:
            await self.memory.save_result(agent_name, result, f"cycle-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
            if "validation_result" in result:
                await self.memory.update_validation_status(
                    agent_name,
                    f"cycle-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
                    result["validation_result"],
                )

        # Обработка ошибок
        if not result["success"]:
            await self.handle_failure(agent_name, result.get("error", "Unknown"), result)

        return result

    async def _get_feedback_for_agent(
        self,
        agent_name: str,
        limit: int = 5,
    ) -> Optional[Dict[str, Any]]:
        """COS-4: Feedback loop — анализ предыдущих запусков."""
        if not self.memory:
            return None

        pool = await self.memory._get_db_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT cycle_id, created_at, validation_score, validation_errors, status, result, execution_time_ms
                    FROM agent_results WHERE agent_name = $1 ORDER BY created_at DESC LIMIT $2""",
                agent_name,
                limit,
            )

        if not rows:
            return None

        runs, high_scores, low_scores, error_patterns, action_history = (
            [],
            [],
            [],
            {},
            [],
        )
        for row in rows:
            score = row["validation_score"] or 0.0
            status = row["status"] or "unknown"
            errors = row["validation_errors"] or []
            result_data = row["result"]
            if isinstance(result_data, str):
                try:
                    result_data = __import__("json").loads(result_data)
                except Exception:
                    result_data = {}
            elif not isinstance(result_data, dict):
                result_data = {}

            run_info = {
                "cycle_id": str(row["cycle_id"]),
                "timestamp": (row["created_at"].isoformat() if row["created_at"] else None),
                "validation_score": score,
                "status": status,
                "execution_time_ms": row["execution_time_ms"],
            }
            runs.append(run_info)

            actions = result_data.get("actions", []) if isinstance(result_data, dict) else []
            if actions:
                action_history.extend(actions[:3])
            if score >= 0.8:
                high_scores.append(run_info)
            elif score < 0.5 or status == "failed":
                low_scores.append(run_info)
            if errors:
                for err in errors[:3]:
                    key = str(err)[:30]
                    error_patterns[key] = error_patterns.get(key, 0) + 1

        patterns = []
        if high_scores:
            patterns.append(
                {
                    "type": "success_pattern",
                    "message": f"{len(high_scores)} из {len(runs)} запусков с высоким score (≥0.8)",
                    "count": len(high_scores),
                }
            )
        if low_scores:
            patterns.append(
                {
                    "type": "failure_pattern",
                    "message": f"{len(low_scores)} из {len(runs)} запусков с низким score (<0.5) или failed",
                    "count": len(low_scores),
                }
            )
        if error_patterns:
            for err_key, count in sorted(error_patterns.items(), key=lambda x: x[1], reverse=True)[:2]:
                patterns.append(
                    {
                        "type": "recurring_error",
                        "message": f"Ошибка повторяется {count} раз(а): {err_key}...",
                        "count": count,
                    }
                )

        recommendations = []
        if len(low_scores) > len(high_scores):
            recommendations.append("Последние запуски показывают снижение качества.")
        if error_patterns:
            recommendations.append("Обнаружены повторяющиеся ошибки.")
        if not action_history:
            recommendations.append("В последних запусках не зафиксировано действий.")

        return {
            "runs": runs,
            "patterns": patterns,
            "recommendations": recommendations,
            "action_history": action_history[:5],
            "avg_score": (round(sum(r["validation_score"] for r in runs) / len(runs), 3) if runs else 0.0),
        }

    async def handle_failure(
        self,
        agent_name: str,
        error: str,
        result: Dict[str, Any],
    ) -> None:
        """Обрабатывает ошибку агента."""
        self.logger.error("Ошибка агента", agent=agent_name, error=error)
        if self.reporter:
            await self.reporter.send_alert(agent_name, error)

    def pause_agent(self, agent_name: str) -> bool:
        """Приостанавливает агента."""
        for config in self.agents:
            if config.agent_name == agent_name:
                self.paused_agents.add(agent_name)
                self.logger.info("Агент приостановлен", agent=agent_name)
                return True
        return False

    def resume_agent(self, agent_name: str) -> bool:
        """Возобновляет работу агента."""
        if agent_name in self.paused_agents:
            self.paused_agents.discard(agent_name)
            self.logger.info("Агент возобновлён", agent=agent_name)
            return True
        return False

    def stop(self) -> None:
        """Останавливает менеджер."""
        self.logger.info("Получена команда остановки")
        self.running = False

    async def close(self) -> None:
        """Закрывает все ресурсы."""
        self.stop()
        if self.llm_client:
            await self.llm_client.close()
        if self.memory:
            await self.memory.close()
        if self.reporter:
            await self.reporter.close()
        self.logger.info("Все ресурсы освобождены")
