#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                        DASHBOARD — Web UI                            ║
║                         smart-skidka.ru                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  Веб-дашборд для мониторинга multi-agent системы.                    ║
║  P3-2: Web UI для мониторинга агентов                                ║
║                                                                      ║
║  Запуск: python scripts/dashboard.py                                 ║
║  Endpoints:                                                          ║
║    GET  /health          — health status                             ║
║    GET  /metrics         — Prometheus-метрики                        ║
║    GET  /api/agents      — список агентов со статусом                ║
║    GET  /api/cycles      — последние циклы                           ║
║    GET  /api/validations — история валидации                         ║
║    GET  /api/errors      — неразрешённые ошибки                      ║
║    GET  /api/trends      — активные тренды                           ║
║    POST /api/agents/{name}/pause   — пауза агента                    ║
║    POST /api/agents/{name}/resume  — возобновление                   ║
║    POST /api/agents/{name}/run_now — запуск вне очереди              ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiohttp
from aiohttp import web
import asyncpg
import redis.asyncio as aioredis
import structlog

structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
    logger_factory=structlog.stdlib.LoggerFactory(),
)
logger = structlog.get_logger("dashboard")

# ═══════════════════════════════════════════════════════════════════════════════
# Конфигурация
# ═══════════════════════════════════════════════════════════════════════════════

DASHBOARD_PORT = int(os.getenv("DASHBOARD_PORT", "8080"))
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_API_KEY = os.getenv("DASHBOARD_API_KEY", "")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost/agents")
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")

# ═══════════════════════════════════════════════════════════════════════════════
# Database helpers
# ═══════════════════════════════════════════════════════════════════════════════

_db_pool: Optional[asyncpg.Pool] = None
_redis: Optional[aioredis.Redis] = None


async def _get_db() -> asyncpg.Pool:
    global _db_pool
    if _db_pool is None or _db_pool._closed:
        _db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=5, command_timeout=30)
    return _db_pool


async def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        _redis = await aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    return _redis


# ═══════════════════════════════════════════════════════════════════════════════
# Middleware
# ═══════════════════════════════════════════════════════════════════════════════

@web.middleware
async def api_key_middleware(request: web.Request, handler) -> web.Response:
    """Проверка API ключа для POST/DELETE запросов."""
    if request.method in ("POST", "DELETE", "PUT", "PATCH"):
        if DASHBOARD_API_KEY:
            header_key = request.headers.get("X-API-Key", "")
            query_key = request.query.get("api_key", "")
            if header_key != DASHBOARD_API_KEY and query_key != DASHBOARD_API_KEY:
                return web.json_response({"error": "Unauthorized"}, status=401)
    return await handler(request)


@web.middleware
async def cors_middleware(request: web.Request, handler) -> web.Response:
    """CORS headers для всех ответов."""
    response = await handler(request)
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
    return response


# ═══════════════════════════════════════════════════════════════════════════════
# Handlers
# ═══════════════════════════════════════════════════════════════════════════════

async def health_handler(request: web.Request) -> web.Response:
    """GET /health — health status оркестратора и подключений."""
    health = {"status": "healthy", "timestamp": datetime.now().isoformat(), "checks": {}}

    # DB check
    try:
        db = await _get_db()
        async with db.acquire() as conn:
            row = await conn.fetchrow("SELECT 1 as ok")
            health["checks"]["database"] = "ok" if row and row["ok"] == 1 else "error"
    except Exception as e:
        health["checks"]["database"] = f"error: {str(e)[:50]}"
        health["status"] = "degraded"

    # Redis check
    try:
        redis = await _get_redis()
        pong = await redis.ping()
        health["checks"]["redis"] = "ok" if pong else "error"
    except Exception as e:
        health["checks"]["redis"] = f"error: {str(e)[:50]}"
        health["status"] = "degraded"

    status_code = 200 if health["status"] == "healthy" else 503
    return web.json_response(health, status=status_code)


async def metrics_handler(request: web.Request) -> web.Response:
    """GET /metrics — Prometheus-совместимые метрики."""
    lines: List[str] = []

    try:
        db = await _get_db()
        async with db.acquire() as conn:
            # cycles_total
            row = await conn.fetchrow("SELECT COUNT(*) as c FROM orchestrator_cycles")
            cycles_total = row["c"] if row else 0
            lines.append(f"# HELP agent_cycles_total Total orchestrator cycles")
            lines.append(f"# TYPE agent_cycles_total counter")
            lines.append(f"agent_cycles_total {cycles_total}")

            # errors_total
            row = await conn.fetchrow("SELECT COUNT(*) as c FROM agent_errors WHERE resolved = FALSE")
            errors_total = row["c"] if row else 0
            lines.append(f"# HELP agent_errors_total Unresolved errors")
            lines.append(f"# TYPE agent_errors_total gauge")
            lines.append(f"agent_errors_total {errors_total}")

            # agents by status
            rows = await conn.fetch(
                """SELECT agent_name, status, COUNT(*) as c
                   FROM agent_results
                   WHERE created_at > NOW() - INTERVAL '24 hours'
                   GROUP BY agent_name, status"""
            )
            lines.append(f"# HELP agent_results_last_24h Results in last 24h by status")
            lines.append(f"# TYPE agent_results_last_24h gauge")
            for r in rows:
                lines.append(f'agent_results_last_24h{{agent="{r["agent_name"]}",status="{r["status"]}"}} {r["c"]}')

            # avg validation score
            row = await conn.fetchrow(
                """SELECT AVG(validation_score) as avg
                   FROM agent_results
                   WHERE created_at > NOW() - INTERVAL '24 hours' AND validation_score IS NOT NULL"""
            )
            avg_score = row["avg"] or 0.0
            lines.append(f"# HELP agent_avg_validation_score Average validation score (24h)")
            lines.append(f"# TYPE agent_avg_validation_score gauge")
            lines.append(f"agent_avg_validation_score {avg_score:.3f}")

    except Exception as e:
        lines.append(f"# ERROR: {str(e)[:100]}")

    return web.Response(text="\n".join(lines) + "\n", content_type="text/plain")


async def agents_handler(request: web.Request) -> web.Response:
    """GET /api/agents — список агентов с последними результатами."""
    try:
        db = await _get_db()
        redis = await _get_redis()

        async with db.acquire() as conn:
            # Последний результат каждого агента
            rows = await conn.fetch(
                """SELECT DISTINCT ON (agent_name)
                          agent_name, status, validation_score,
                          execution_time_ms, created_at,
                          result->>'actions' as actions
                   FROM agent_results
                   ORDER BY agent_name, created_at DESC"""
            )

        agents = []
        for r in rows:
            agent_name = r["agent_name"]
            # Проверяем паузу в Redis
            is_paused = await redis.exists(f"agent:pause:{agent_name}")
            is_run_now = await redis.exists(f"agent:run_now:{agent_name}")

            agents.append({
                "name": agent_name,
                "status": r["status"],
                "validation_score": round(r["validation_score"], 3) if r["validation_score"] else None,
                "execution_time_ms": r["execution_time_ms"],
                "last_run": r["created_at"].isoformat() if r["created_at"] else None,
                "paused": bool(is_paused),
                "run_now": bool(is_run_now),
            })

        return web.json_response({"agents": agents, "count": len(agents)})

    except Exception as e:
        logger.error("agents_handler_error", error=str(e))
        return web.json_response({"error": str(e)}, status=500)


async def cycles_handler(request: web.Request) -> web.Response:
    """GET /api/cycles — последние циклы оркестратора."""
    limit = int(request.query.get("limit", "20"))
    try:
        db = await _get_db()
        async with db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id, started_at, completed_at, status,
                          agents_total, agents_success, agents_failed
                   FROM orchestrator_cycles
                   ORDER BY started_at DESC
                   LIMIT $1""",
                limit,
            )

        cycles = []
        for r in rows:
            cycles.append({
                "id": str(r["id"]),
                "started_at": r["started_at"].isoformat() if r["started_at"] else None,
                "completed_at": r["completed_at"].isoformat() if r["completed_at"] else None,
                "status": r["status"],
                "agents_total": r["agents_total"],
                "agents_success": r["agents_success"],
                "agents_failed": r["agents_failed"],
            })

        return web.json_response({"cycles": cycles, "count": len(cycles)})

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def validations_handler(request: web.Request) -> web.Response:
    """GET /api/validations — история валидации."""
    limit = int(request.query.get("limit", "50"))
    agent_name = request.query.get("agent")
    try:
        db = await _get_db()
        async with db.acquire() as conn:
            if agent_name:
                rows = await conn.fetch(
                    """SELECT agent_name, cycle_id, status, validation_score,
                              validation_errors, execution_time_ms, created_at
                       FROM agent_results
                       WHERE agent_name = $1 AND validation_score IS NOT NULL
                       ORDER BY created_at DESC
                       LIMIT $2""",
                    agent_name, limit,
                )
            else:
                rows = await conn.fetch(
                    """SELECT agent_name, cycle_id, status, validation_score,
                              validation_errors, execution_time_ms, created_at
                       FROM agent_results
                       WHERE validation_score IS NOT NULL
                       ORDER BY created_at DESC
                       LIMIT $1""",
                    limit,
                )

            # Summary
            summary_row = await conn.fetchrow(
                """SELECT
                      COUNT(*) as total,
                      COUNT(*) FILTER (WHERE status = 'success') as passed,
                      COUNT(*) FILTER (WHERE status = 'failed') as failed,
                      AVG(validation_score) as avg_score
                   FROM agent_results
                   WHERE created_at > NOW() - INTERVAL '24 hours'"""
            )

        results = []
        for r in rows:
            results.append({
                "agent_name": r["agent_name"],
                "cycle_id": str(r["cycle_id"]) if r["cycle_id"] else None,
                "status": r["status"],
                "validation_score": round(r["validation_score"], 3) if r["validation_score"] else None,
                "execution_time_ms": r["execution_time_ms"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })

        summary = {
            "total_24h": summary_row["total"] if summary_row else 0,
            "passed_24h": summary_row["passed"] if summary_row else 0,
            "failed_24h": summary_row["failed"] if summary_row else 0,
            "avg_score_24h": round(summary_row["avg_score"], 3) if summary_row and summary_row["avg_score"] else 0.0,
        }

        return web.json_response({"results": results, "summary": summary})

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def errors_handler(request: web.Request) -> web.Response:
    """GET /api/errors — неразрешённые ошибки."""
    limit = int(request.query.get("limit", "20"))
    try:
        db = await _get_db()
        async with db.acquire() as conn:
            rows = await conn.fetch(
                """SELECT agent_name, error_type, error_message, retry_count, created_at
                   FROM agent_errors
                   WHERE resolved = FALSE
                   ORDER BY created_at DESC
                   LIMIT $1""",
                limit,
            )

        errors = []
        for r in rows:
            errors.append({
                "agent_name": r["agent_name"],
                "error_type": r["error_type"],
                "error_message": r["error_message"],
                "retry_count": r["retry_count"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })

        return web.json_response({"errors": errors, "count": len(errors)})

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def trends_handler(request: web.Request) -> web.Response:
    """GET /api/trends — активные тренды и источники."""
    try:
        db = await _get_db()
        async with db.acquire() as conn:
            trends = await conn.fetch(
                """SELECT trend_type, confidence, title, status,
                          competition_level, validated, created_at
                   FROM trend_detections
                   WHERE status IN ('rising', 'peak')
                   ORDER BY confidence DESC
                   LIMIT 20"""
            )

            sources = await conn.fetch(
                """SELECT source_name, source_type, last_fetch_at,
                          fetch_status, is_active
                   FROM trend_data_sources
                   ORDER BY source_name"""
            )

        trend_list = []
        for r in trends:
            trend_list.append({
                "type": r["trend_type"],
                "confidence": round(r["confidence"], 2) if r["confidence"] else None,
                "title": r["title"],
                "status": r["status"],
                "competition": r["competition_level"],
                "validated": r["validated"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            })

        source_list = []
        for r in sources:
            source_list.append({
                "name": r["source_name"],
                "type": r["source_type"],
                "last_fetch": r["last_fetch_at"].isoformat() if r["last_fetch_at"] else None,
                "status": r["fetch_status"],
                "active": r["is_active"],
            })

        return web.json_response({"trends": trend_list, "sources": source_list})

    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def agent_pause_handler(request: web.Request) -> web.Response:
    """POST /api/agents/{name}/pause — пауза агента."""
    agent_name = request.match_info["name"]
    try:
        redis = await _get_redis()
        await redis.setex(f"agent:pause:{agent_name}", 86400, "1")  # 24h max
        logger.info("agent_paused_via_dashboard", agent=agent_name)
        return web.json_response({"agent": agent_name, "paused": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def agent_resume_handler(request: web.Request) -> web.Response:
    """POST /api/agents/{name}/resume — возобновление агента."""
    agent_name = request.match_info["name"]
    try:
        redis = await _get_redis()
        await redis.delete(f"agent:pause:{agent_name}")
        logger.info("agent_resumed_via_dashboard", agent=agent_name)
        return web.json_response({"agent": agent_name, "paused": False})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def agent_run_now_handler(request: web.Request) -> web.Response:
    """POST /api/agents/{name}/run_now — запуск вне очереди."""
    agent_name = request.match_info["name"]
    try:
        redis = await _get_redis()
        await redis.setex(f"agent:run_now:{agent_name}", 300, "1")  # 5min window
        logger.info("agent_run_now_via_dashboard", agent=agent_name)
        return web.json_response({"agent": agent_name, "run_now": True})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=500)


async def index_handler(request: web.Request) -> web.Response:
    """GET / — простая HTML страница с ссылками на API."""
    html = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Smart-Skidka Agents Dashboard</title>
    <style>
        body { font-family: system-ui, sans-serif; max-width: 900px; margin: 40px auto; padding: 20px; }
        h1 { color: #333; }
        .endpoint { background: #f5f5f5; padding: 10px 15px; margin: 8px 0; border-radius: 6px; }
        .endpoint a { color: #0066cc; text-decoration: none; font-family: monospace; }
        .endpoint a:hover { text-decoration: underline; }
        .method { display: inline-block; width: 60px; font-weight: bold; color: #666; }
        .get { color: #28a745; }
        .post { color: #fd7e14; }
    </style>
</head>
<body>
    <h1>🔧 Smart-Skidka Agents Dashboard</h1>
    <p>Multi-Agent System Monitoring API</p>

    <h2>Health & Metrics</h2>
    <div class="endpoint"><span class="method get">GET</span> <a href="/health">/health</a> — system health</div>
    <div class="endpoint"><span class="method get">GET</span> <a href="/metrics">/metrics</a> — Prometheus metrics</div>

    <h2>Agents</h2>
    <div class="endpoint"><span class="method get">GET</span> <a href="/api/agents">/api/agents</a> — agent list with status</div>
    <div class="endpoint"><span class="method post">POST</span> /api/agents/{name}/pause — pause agent</div>
    <div class="endpoint"><span class="method post">POST</span> /api/agents/{name}/resume — resume agent</div>
    <div class="endpoint"><span class="method post">POST</span> /api/agents/{name}/run_now — trigger run</div>

    <h2>Data</h2>
    <div class="endpoint"><span class="method get">GET</span> <a href="/api/cycles">/api/cycles</a> — recent cycles</div>
    <div class="endpoint"><span class="method get">GET</span> <a href="/api/validations">/api/validations</a> — validation history</div>
    <div class="endpoint"><span class="method get">GET</span> <a href="/api/errors">/api/errors</a> — unresolved errors</div>
    <div class="endpoint"><span class="method get">GET</span> <a href="/api/trends">/api/trends</a> — active trends</div>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


# ═══════════════════════════════════════════════════════════════════════════════
# App factory
# ═══════════════════════════════════════════════════════════════════════════════

def create_app() -> web.Application:
    """Создаёт aiohttp приложение."""
    app = web.Application(middlewares=[cors_middleware, api_key_middleware])

    app.router.add_get("/", index_handler)
    app.router.add_get("/health", health_handler)
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_get("/api/agents", agents_handler)
    app.router.add_get("/api/cycles", cycles_handler)
    app.router.add_get("/api/validations", validations_handler)
    app.router.add_get("/api/errors", errors_handler)
    app.router.add_get("/api/trends", trends_handler)
    app.router.add_post("/api/agents/{name}/pause", agent_pause_handler)
    app.router.add_post("/api/agents/{name}/resume", agent_resume_handler)
    app.router.add_post("/api/agents/{name}/run_now", agent_run_now_handler)

    return app


async def cleanup(app: web.Application) -> None:
    """Закрытие соединений."""
    global _db_pool, _redis
    if _db_pool and not _db_pool._closed:
        await _db_pool.close()
    if _redis:
        await _redis.close()
    logger.info("dashboard_shutdown")


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = create_app()
    app.on_cleanup.append(cleanup)
    logger.info("dashboard_starting", host=DASHBOARD_HOST, port=DASHBOARD_PORT)
    web.run_app(app, host=DASHBOARD_HOST, port=DASHBOARD_PORT)
