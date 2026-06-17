#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ReportGenerator — генерация отчётов и метрик.

P1-1: Выделен из Orchestrator.
Отвечает за:
- Ежедневные отчёты
- Health status
- Validation history
- Content metrics
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

import structlog


class ReportGenerator:
    """Генерирует отчёты и метрики оркестратора."""

    def __init__(self, memory_store: Any, reporter: Any = None) -> None:
        self.memory = memory_store
        self.reporter = reporter
        self.logger = structlog.get_logger("report_generator")

    async def generate_daily_report(
        self,
        agents: List[Any],
        cycle_count: int,
        total_errors: int,
        start_time: Optional[datetime],
    ) -> Dict[str, Any]:
        """Генерирует ежедневный отчёт о работе оркестратора."""
        today = datetime.now().strftime("%Y-%m-%d")

        if not self.memory:
            return {
                "date": today,
                "total_agents": len(agents),
                "successful_runs": 0,
                "failed_runs": 0,
                "avg_validation_score": 0.0,
                "agent_details": [],
            }

        pool = await self.memory._get_db_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT
                    agent_name,
                    COUNT(*) as run_count,
                    AVG(validation_score) as avg_score,
                    SUM(CASE WHEN validation_status = 'failed' THEN 1 ELSE 0 END) as fail_count
                FROM agent_results
                WHERE timestamp >= $1
                GROUP BY agent_name
                """,
                datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
            )

        agent_details = []
        total_success = 0
        total_fail = 0
        total_score = 0.0

        for row in rows:
            fail_count = row["fail_count"] or 0
            run_count = row["run_count"] or 0
            success_count = run_count - fail_count
            avg_score = row["avg_score"] or 0.0

            agent_details.append(
                {
                    "name": row["agent_name"],
                    "runs": run_count,
                    "successful": success_count,
                    "failed": fail_count,
                    "avg_score": round(avg_score, 3),
                    "status": ("success" if fail_count == 0 else "partial" if success_count > 0 else "failed"),
                    "validation_score": avg_score,
                }
            )

            total_success += success_count
            total_fail += fail_count
            total_score += avg_score

        avg_total = total_score / len(rows) if rows else 0.0

        report = {
            "date": today,
            "total_agents": len(agents),
            "successful_runs": total_success,
            "failed_runs": total_fail,
            "avg_validation_score": round(avg_total, 3),
            "agent_details": agent_details,
            "cycle_count": cycle_count,
            "total_errors": total_errors,
            "uptime_hours": ((datetime.now() - start_time).total_seconds() / 3600 if start_time else 0),
        }

        if self.reporter:
            await self.reporter.send_daily_report(report)

        self.logger.info("Ежедневный отчёт сгенерирован", date=today)
        return report

    def get_health_status(
        self,
        running: bool,
        cycle_count: int,
        total_errors: int,
        start_time: Optional[datetime],
        agents: List[Any],
        paused_agents: set,
    ) -> Dict[str, Any]:
        """P2-4: Возвращает статус здоровья оркестратора."""
        uptime_seconds = 0
        if start_time:
            uptime_seconds = int((datetime.now() - start_time).total_seconds())
        status = "unhealthy"
        if running:
            from scripts.orchestrator import HEALTH_ERROR_THRESHOLD

            if total_errors > HEALTH_ERROR_THRESHOLD:
                status = "degraded"
            else:
                status = "healthy"
        return {
            "status": status,
            "running": running,
            "cycle_count": cycle_count,
            "errors_total": total_errors,
            "uptime_seconds": uptime_seconds,
            "agents_total": len(agents),
            "agents_paused": len(paused_agents),
        }

    async def get_validation_history(
        self,
        limit: int = 20,
        agent_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """P2-6: Возвращает историю валидации агентов."""
        if not self.memory:
            return {
                "total": 0,
                "results": [],
                "summary": {"passed": 0, "failed": 0, "avg_score": 0.0},
            }

        pool = await self.memory._get_db_pool()
        async with pool.acquire() as conn:
            if agent_name:
                rows = await conn.fetch(
                    """SELECT cycle_id, agent_name, status, validation_score, created_at
                       FROM agent_results WHERE agent_name = $1 ORDER BY created_at DESC LIMIT $2""",
                    agent_name,
                    limit,
                )
                total = (
                    await conn.fetchrow(
                        "SELECT COUNT(*) FROM agent_results WHERE agent_name = $1",
                        agent_name,
                    )
                )[0] or 0
            else:
                rows = await conn.fetch(
                    """SELECT cycle_id, agent_name, status, validation_score, created_at
                       FROM agent_results ORDER BY created_at DESC LIMIT $1""",
                    limit,
                )
                total = (await conn.fetchrow("SELECT COUNT(*) FROM agent_results"))[0] or 0

        results = []
        passed, failed = 0, 0
        scores = []
        for row in rows:
            score = row["validation_score"] or 0.0
            status = row["status"] or "unknown"
            if status == "completed":
                passed += 1
            elif status == "failed":
                failed += 1
            if score:
                scores.append(score)
            results.append(
                {
                    "cycle_id": str(row["cycle_id"]),
                    "agent_name": row["agent_name"],
                    "status": status,
                    "validation_score": score,
                    "created_at": (row["created_at"].isoformat() if row["created_at"] else None),
                }
            )

        avg_score = round(sum(scores) / len(scores), 3) if scores else 0.0
        return {
            "total": total,
            "results": results,
            "summary": {"passed": passed, "failed": failed, "avg_score": avg_score},
        }

    async def get_metrics(
        self,
        cycle_count: int,
        total_errors: int = 0,
        agents_count: int = 0,
        paused_count: int = 0,
    ) -> Dict[str, Any]:
        """P2-7 + COS-2: Возвращает метрики в формате Prometheus + контент-метрики."""
        content = await self._get_content_metrics()
        return {
            "cycles_total": cycle_count,
            "errors_total": total_errors,
            "agents_total": agents_count,
            "agents_paused": paused_count,
            **content,
        }

    async def _get_content_metrics(self) -> Dict[str, Any]:
        """COS-2: Контент-метрики из БД."""
        if not self.memory:
            return {
                "pages_total": 0,
                "pages_today": 0,
                "pages_this_week": 0,
                "pages_this_month": 0,
                "avg_validation_score": 0.0,
                "published_content_count": 0,
                "by_agent": {},
            }

        try:
            pool = await self.memory._get_db_pool()
            async with pool.acquire() as conn:
                today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
                week_start = today_start - __import__("datetime").timedelta(days=today_start.weekday())
                month_start = today_start.replace(day=1)

                pages_total = (await conn.fetchrow("SELECT COUNT(*) FROM agent_pages WHERE status = 'active'"))[0] or 0
                pages_today = (
                    await conn.fetchrow(
                        "SELECT COUNT(*) FROM agent_pages WHERE created_at >= $1",
                        today_start,
                    )
                )[0] or 0
                pages_week = (
                    await conn.fetchrow(
                        "SELECT COUNT(*) FROM agent_pages WHERE created_at >= $1",
                        week_start,
                    )
                )[0] or 0
                pages_month = (
                    await conn.fetchrow(
                        "SELECT COUNT(*) FROM agent_pages WHERE created_at >= $1",
                        month_start,
                    )
                )[0] or 0
                avg_score_row = await conn.fetchrow(
                    "SELECT AVG(validation_score) FROM agent_results WHERE created_at >= $1 AND validation_score IS NOT NULL",
                    today_start,
                )
                avg_score = avg_score_row[0] if avg_score_row and avg_score_row[0] else 0.0
                published = (await conn.fetchrow("SELECT COUNT(*) FROM content_registry WHERE status = 'published'"))[
                    0
                ] or 0

                rows = await conn.fetch("""SELECT agent_name, status, validation_score, created_at
                       FROM agent_results ORDER BY created_at DESC LIMIT 100""")

            by_agent: Dict[str, Any] = {}
            for row in rows:
                agent = row["agent_name"]
                if agent not in by_agent:
                    by_agent[agent] = {
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                        "scores": [],
                    }
                by_agent[agent]["total"] += 1
                if row["status"] == "completed":
                    by_agent[agent]["passed"] += 1
                elif row["status"] == "failed":
                    by_agent[agent]["failed"] += 1
                if row["validation_score"]:
                    by_agent[agent]["scores"].append(row["validation_score"])

            for agent, data in by_agent.items():
                scores = data["scores"]
                data["avg_score"] = round(sum(scores) / len(scores), 3) if scores else 0.0
                del data["scores"]

            return {
                "pages_total": pages_total,
                "pages_today": pages_today,
                "pages_this_week": pages_week,
                "pages_this_month": pages_month,
                "avg_validation_score": round(avg_score, 3),
                "published_content_count": published,
                "by_agent": by_agent,
            }
        except Exception as e:
            self.logger.error("content_metrics_failed", error=str(e))
            return {
                "pages_total": 0,
                "pages_today": 0,
                "pages_this_week": 0,
                "pages_this_month": 0,
                "avg_validation_score": 0.0,
                "published_content_count": 0,
                "by_agent": {},
            }
