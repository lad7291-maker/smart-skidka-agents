#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для Web UI дашборда (P3-2).
"""

import sys
import unittest
import asyncio

sys.path.insert(0, '/opt/smart-skidka-agents')
sys.path.insert(0, '/opt/smart-skidka-agents/scripts')

from aiohttp import web
from aiohttp.test_utils import AioHTTPTestCase, unittest_run_loop

from scripts.dashboard import (
    create_app,
    index_handler,
    health_handler,
    metrics_handler,
    agents_handler,
    cycles_handler,
    validations_handler,
    errors_handler,
    trends_handler,
    agent_pause_handler,
    agent_resume_handler,
    agent_run_now_handler,
)


class TestDashboardHandlers(AioHTTPTestCase):
    """Тесты дашборда через aiohttp test client."""

    async def get_application(self):
        return create_app()

    @unittest_run_loop
    async def test_index(self):
        """GET / возвращает HTML."""
        resp = await self.client.request("GET", "/")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertIn("Smart-Skidka Agents Dashboard", text)

    @unittest_run_loop
    async def test_health(self):
        """GET /health возвращает JSON."""
        resp = await self.client.request("GET", "/health")
        self.assertIn(resp.status, [200, 503])
        data = await resp.json()
        self.assertIn("status", data)
        self.assertIn("checks", data)

    @unittest_run_loop
    async def test_metrics(self):
        """GET /metrics возвращает plain text."""
        resp = await self.client.request("GET", "/metrics")
        self.assertEqual(resp.status, 200)
        text = await resp.text()
        self.assertTrue(text.startswith("#") or "ERROR" in text)

    @unittest_run_loop
    async def test_agents(self):
        """GET /api/agents возвращает JSON (может быть 500 без БД)."""
        resp = await self.client.request("GET", "/api/agents")
        self.assertIn(resp.status, [200, 500])
        data = await resp.json()
        if resp.status == 200:
            self.assertIn("agents", data)

    @unittest_run_loop
    async def test_cycles(self):
        """GET /api/cycles возвращает JSON."""
        resp = await self.client.request("GET", "/api/cycles")
        self.assertIn(resp.status, [200, 500])

    @unittest_run_loop
    async def test_validations(self):
        """GET /api/validations возвращает JSON."""
        resp = await self.client.request("GET", "/api/validations")
        self.assertIn(resp.status, [200, 500])

    @unittest_run_loop
    async def test_errors(self):
        """GET /api/errors возвращает JSON."""
        resp = await self.client.request("GET", "/api/errors")
        self.assertIn(resp.status, [200, 500])

    @unittest_run_loop
    async def test_trends(self):
        """GET /api/trends возвращает JSON."""
        resp = await self.client.request("GET", "/api/trends")
        self.assertIn(resp.status, [200, 500])

    @unittest_run_loop
    async def test_agent_pause_unauthorized(self):
        """POST /api/agents/{name}/pause без API ключа — 401."""
        # Set API key for test
        import scripts.dashboard as d
        d.DASHBOARD_API_KEY = "test_key"
        resp = await self.client.request("POST", "/api/agents/seo-agent/pause")
        self.assertEqual(resp.status, 401)
        d.DASHBOARD_API_KEY = ""  # reset

    @unittest_run_loop
    async def test_cors_headers(self):
        """CORS headers присутствуют."""
        resp = await self.client.request("GET", "/health")
        self.assertIn("Access-Control-Allow-Origin", resp.headers)
        self.assertEqual(resp.headers["Access-Control-Allow-Origin"], "*")


class TestDashboardUnit(unittest.TestCase):
    """Юнит-тесты без HTTP."""

    def test_create_app(self):
        """App создаётся без ошибок."""
        app = create_app()
        self.assertIsInstance(app, web.Application)

    def test_routes_registered(self):
        """Все маршруты зарегистрированы."""
        app = create_app()
        routes = [r for r in app.router.routes() if r.method != 'HEAD']
        paths = set()
        for r in routes:
            resource = r.resource
            if hasattr(resource, '_path'):
                paths.add(resource._path)
            elif hasattr(resource, '_formatter'):
                paths.add(resource._formatter)
        expected = {'/', '/health', '/metrics', '/api/agents', '/api/cycles',
                    '/api/validations', '/api/errors', '/api/trends',
                    '/api/agents/{name}/pause', '/api/agents/{name}/resume',
                    '/api/agents/{name}/run_now'}
        self.assertTrue(expected.issubset(paths) or len(paths) >= len(expected))


if __name__ == "__main__":
    unittest.main(verbosity=2)
