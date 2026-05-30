#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for Orchestrator with mocks (no DB/Redis/LLM required).

Run:
    cd /opt/smart-skidka-agents && PYTHONPATH=scripts:$PYTHONPATH python3 -m unittest tests.test_orchestrator -v
"""

import sys
import unittest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

sys.path.insert(0, '/opt/smart-skidka-agents')
sys.path.insert(0, '/opt/smart-skidka-agents/scripts')

from scripts.orchestrator import (
    Orchestrator,
    ValidationResult,
    ValidationStatus,
    AgentConfig,
    AgentRunner,
    LLMClient,
)


class MockMemoryStore:
    """Mock MemoryStore for testing without PostgreSQL/Redis."""

    def __init__(self):
        self.results = []
        self.pages = []
        self.content_registry = []
        self.tasks = []
        self._db_pool = MagicMock()
        self._redis = MagicMock()

    async def init_schema(self):
        pass

    async def save_result(self, agent_name, result, cycle_id):
        self.results.append({
            "agent_name": agent_name,
            "result": result,
            "cycle_id": cycle_id,
        })

    async def get_context(self, agent_name):
        return {"fresh_start": True}

    async def get_last_results(self, agent_name, limit=10):
        return []

    async def get_trend_recommendations(self, agent_name, limit=5):
        return []

    async def mark_trend_recommendations_completed(self, agent_name, actions):
        pass

    async def get_analytics_tasks(self, agent_name, limit=5):
        return []

    async def mark_analytics_tasks_completed(self, agent_name, titles):
        pass

    async def save_metrics(self, agent_name, metrics):
        pass

    async def update_validation_status(self, agent_name, cycle_id, validation):
        pass

    async def save_task(self, task):
        self.tasks.append(task)

    async def get_pending_tasks(self, agent_name):
        return []

    async def complete_task(self, task_id):
        return True

    async def close(self):
        pass

    async def _get_db_pool(self):
        return self._db_pool

    async def _get_redis(self):
        return self._redis

    # CRIT-4: Page tracking
    async def track_page(self, path, agent_name, page_type="", title="",
                         html_valid=None, http_status=None):
        self.pages.append({
            "path": path,
            "agent_name": agent_name,
            "page_type": page_type,
            "title": title,
            "html_valid": html_valid,
            "http_status": http_status,
        })

    async def get_agent_pages(self, agent_name=None, status="active", limit=100):
        pages = [p for p in self.pages if p.get("status", "active") == status]
        if agent_name:
            pages = [p for p in pages if p["agent_name"] == agent_name]
        return pages[:limit]

    # IMP-6: Content registry
    async def register_content(self, content_type, title, slug, path,
                               agent_name, keywords=None, related_slugs=None):
        self.content_registry.append({
            "content_type": content_type,
            "title": title,
            "slug": slug,
            "path": path,
            "agent_name": agent_name,
        })

    async def find_similar_content(self, title, threshold=0.7):
        return []

    async def get_related_content(self, slug, limit=5):
        return []


class MockLLMClient:
    """Mock LLMClient for testing."""

    def __init__(self, *args, **kwargs):
        self._cb_state = "closed"

    async def close(self):
        pass

    async def generate(self, *args, **kwargs):
        return {"content": "mock response", "success": True}


class MockReporter:
    """Mock TelegramReporter."""

    async def send_summary(self, data):
        pass

    async def send_alert(self, agent_name, error):
        pass

    async def send_daily_report(self, report):
        pass

    async def close(self):
        pass


class TestOrchestratorBasics(unittest.IsolatedAsyncioTestCase):
    """Тесты базовой функциональности Orchestrator."""

    async def asyncSetUp(self):
        """Создаём оркестратор с моками перед каждым тестом."""
        self.orch = Orchestrator(config_path="./configs")
        # Подменяем компоненты моками
        self.orch.memory = MockMemoryStore()
        self.orch.llm_client = MockLLMClient()
        self.orch.reporter = MockReporter()
        self.orch.agents = []
        self.orch.agent_runners = {}

    async def test_health_status_not_running(self):
        """Health status = unhealthy когда оркестратор не запущен."""
        health = self.orch.get_health_status()
        self.assertEqual(health["status"], "unhealthy")
        self.assertFalse(health["running"])
        self.assertEqual(health["cycle_count"], 0)

    async def test_health_status_running(self):
        """Health status = healthy когда оркестратор работает и мало ошибок."""
        self.orch.running = True
        self.orch.start_time = datetime.now() - timedelta(minutes=5)
        health = self.orch.get_health_status()
        self.assertEqual(health["status"], "healthy")
        self.assertTrue(health["running"])
        self.assertGreater(health["uptime_seconds"], 0)

    async def test_health_status_degraded(self):
        """Health status = degraded при >10 ошибок."""
        self.orch.running = True
        self.orch.start_time = datetime.now()
        self.orch.total_errors = 15
        health = self.orch.get_health_status()
        self.assertEqual(health["status"], "degraded")

    async def test_pause_resume_agent(self):
        """Пауза и возобновление агента."""
        # Создаём фейковый агент
        mock_config = MagicMock()
        mock_config.agent_name = "test_agent"
        self.orch.agents = [mock_config]

        # Пауза
        ok = self.orch.pause_agent("test_agent")
        self.assertTrue(ok)
        self.assertIn("test_agent", self.orch.paused_agents)

        # Повторная пауза — всё ещё True
        ok = self.orch.pause_agent("test_agent")
        self.assertTrue(ok)

        # Возобновление
        ok = self.orch.resume_agent("test_agent")
        self.assertTrue(ok)
        self.assertNotIn("test_agent", self.orch.paused_agents)

        # Возобновление не-паузы — False
        ok = self.orch.resume_agent("test_agent")
        self.assertFalse(ok)

    async def test_pause_unknown_agent(self):
        """Пауза неизвестного агента возвращает False."""
        ok = self.orch.pause_agent("nonexistent")
        self.assertFalse(ok)

    async def test_metrics_without_db(self):
        """Метрики возвращают нули когда нет БД."""
        self.orch.memory = None
        metrics = await self.orch.get_metrics()
        self.assertEqual(metrics["pages_total"], 0)
        self.assertEqual(metrics["pages_today"], 0)
        self.assertEqual(metrics["pages_this_week"], 0)
        self.assertEqual(metrics["pages_this_month"], 0)
        self.assertEqual(metrics["cycles_total"], 0)
        self.assertEqual(metrics["errors_total"], 0)

    async def test_metrics_with_mock_db(self):
        """Метрики собираются из мока БД."""
        metrics = await self.orch.get_metrics()
        self.assertIn("pages_total", metrics)
        self.assertIn("pages_today", metrics)
        self.assertIn("avg_validation_score", metrics)
        self.assertIn("published_content_count", metrics)

    async def test_stop(self):
        """Остановка оркестратора."""
        self.orch.running = True
        self.orch.stop()
        self.assertFalse(self.orch.running)


class TestOrchestratorCycle(unittest.IsolatedAsyncioTestCase):
    """Тесты цикла оркестратора с моками."""

    async def asyncSetUp(self):
        self.orch = Orchestrator(config_path="./configs")
        self.orch.memory = MockMemoryStore()
        self.orch.llm_client = MockLLMClient()
        self.orch.reporter = MockReporter()

        # Создаём фейковый агент и раннер
        self.mock_config = MagicMock()
        self.mock_config.agent_name = "content_agent"
        self.mock_config.is_enabled.return_value = True
        self.orch.agents = [self.mock_config]

        # Мок раннера, который возвращает успешный результат
        self.mock_runner = MagicMock()
        self.mock_runner.run = AsyncMock(return_value={
            "success": True,
            "data": {"title": "Test", "description": "Test desc"},
            "task_type": "content",
        })
        self.mock_runner.retry = AsyncMock(return_value={
            "success": True,
            "data": {"title": "Test", "description": "Test desc"},
        })
        self.orch.agent_runners = {"content_agent": self.mock_runner}

    async def test_run_cycle_empty_agents(self):
        """Цикл с пустым списком агентов завершается успешно."""
        self.orch.agents = []
        result = await self.orch.run_cycle()
        self.assertIn("cycle_id", result)
        self.assertEqual(len(result["results"]), 0)
        self.assertEqual(result["errors"], [])

    async def test_run_cycle_with_agent(self):
        """Цикл с одним агентом выполняется и сохраняет результат."""
        result = await self.orch.run_cycle()
        self.assertIn("cycle_id", result)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["agent_name"], "content_agent")
        self.assertTrue(result["results"][0]["success"])
        # Проверяем что результат сохранён в memory
        self.assertEqual(len(self.orch.memory.results), 1)

    async def test_run_cycle_counts_cycles(self):
        """Счётчик циклов увеличивается."""
        initial = self.orch.cycle_count
        await self.orch.run_cycle()
        self.assertEqual(self.orch.cycle_count, initial + 1)
        await self.orch.run_cycle()
        self.assertEqual(self.orch.cycle_count, initial + 2)

    async def test_run_cycle_agent_failure(self):
        """Цикл продолжается даже если агент упал."""
        self.mock_runner.run = AsyncMock(return_value={
            "success": False,
            "error": "LLM timeout",
            "data": {},
        })
        self.mock_runner.retry = AsyncMock(return_value={
            "success": False,
            "error": "LLM timeout",
            "data": {},
        })

        result = await self.orch.run_cycle()
        self.assertEqual(len(result["results"]), 1)
        self.assertFalse(result["results"][0]["success"])
        self.assertEqual(self.orch.total_errors, 1)

    async def test_run_cycle_agent_exception(self):
        """Цикл продолжается даже при исключении в агенте."""
        self.mock_runner.run = AsyncMock(side_effect=RuntimeError("Boom!"))

        result = await self.orch.run_cycle()
        self.assertEqual(len(result["results"]), 1)
        self.assertFalse(result["results"][0]["success"])
        self.assertIn("Boom!", result["results"][0]["error"])


class TestOrchestratorValidation(unittest.IsolatedAsyncioTestCase):
    """Тесты валидации результатов."""

    async def asyncSetUp(self):
        self.orch = Orchestrator(config_path="./configs")
        self.orch.memory = MockMemoryStore()
        self.orch.llm_client = MockLLMClient()

    async def test_validate_and_store(self):
        """Валидация результата возвращает ValidationResult."""
        result = {
            "data": {
                "title": "Test Title",
                "description": "Test Description",
                "keywords": ["test", "seo"],
            }
        }
        validation = await self.orch.validate_and_store("seo_agent", result)
        # validate_by_type returns validator.ValidationResult, not orchestrator.ValidationResult
        from scripts.validator import ValidationResult as ValidatorResult
        self.assertIsInstance(validation, (ValidationResult, ValidatorResult))
        self.assertIn(validation.status.value, [
            "passed", "warning", "failed", "skipped",
        ])

    async def test_validate_unknown_agent_type(self):
        """Валидация неизвестного типа агента не падает."""
        result = {"data": {"foo": "bar"}}
        validation = await self.orch.validate_and_store("unknown_agent", result)
        from scripts.validator import ValidationResult as ValidatorResult
        self.assertIsInstance(validation, (ValidationResult, ValidatorResult))


class TestOrchestratorContentMetrics(unittest.IsolatedAsyncioTestCase):
    """Тесты метрик контента (COS-2)."""

    async def asyncSetUp(self):
        self.orch = Orchestrator(config_path="./configs")
        self.orch.memory = MockMemoryStore()
        self.orch.llm_client = MockLLMClient()

    async def test_content_metrics_empty(self):
        """Метрики контента пусты при отсутствии данных."""
        # Mock the DB pool to return actual counts
        mock_conn = MagicMock()
        mock_conn.fetchrow = AsyncMock(return_value=[0])  # COUNT(*) = 0
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_cm)
        self.orch.memory._db_pool = mock_pool

        metrics = await self.orch._get_content_metrics()
        self.assertEqual(metrics["pages_total"], 0)
        self.assertEqual(metrics["pages_today"], 0)
        self.assertEqual(metrics["pages_this_week"], 0)
        self.assertEqual(metrics["pages_this_month"], 0)
        self.assertEqual(metrics["avg_validation_score"], 0.0)
        self.assertEqual(metrics["published_content_count"], 0)

    async def test_content_metrics_structure(self):
        """Структура метрик контента корректна."""
        metrics = await self.orch._get_content_metrics()
        required_keys = [
            "pages_total", "pages_today", "pages_this_week",
            "pages_this_month", "avg_validation_score", "published_content_count",
        ]
        for key in required_keys:
            self.assertIn(key, metrics)


class TestOrchestratorDailyReport(unittest.IsolatedAsyncioTestCase):
    """Тесты ежедневного отчёта."""

    async def asyncSetUp(self):
        self.orch = Orchestrator(config_path="./configs")
        self.orch.memory = MockMemoryStore()
        self.orch.llm_client = MockLLMClient()
        self.orch.reporter = MockReporter()

    async def test_generate_daily_report_no_db(self):
        """Отчёт без БД возвращает базовую структуру."""
        self.orch.memory = None
        report = await self.orch.generate_daily_report()
        self.assertIn("date", report)
        self.assertIn("total_agents", report)
        self.assertIn("successful_runs", report)
        self.assertIn("failed_runs", report)
        self.assertEqual(report["successful_runs"], 0)

    async def test_generate_daily_report_with_mock_db(self):
        """Отчёт с моком БД возвращает структуру."""
        # Mock DB to return empty rows (avoid ZeroDivisionError)
        mock_conn = MagicMock()
        mock_conn.fetch = AsyncMock(return_value=[])
        mock_cm = MagicMock()
        mock_cm.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_cm.__aexit__ = AsyncMock(return_value=False)
        mock_pool = MagicMock()
        mock_pool.acquire = MagicMock(return_value=mock_cm)
        self.orch.memory._db_pool = mock_pool

        report = await self.orch.generate_daily_report()
        self.assertIn("date", report)
        self.assertIn("agent_details", report)


class TestOrchestratorValidationHistory(unittest.IsolatedAsyncioTestCase):
    """Тесты истории валидации."""

    async def asyncSetUp(self):
        self.orch = Orchestrator(config_path="./configs")
        self.orch.memory = MockMemoryStore()

    async def test_validation_history_no_db(self):
        """История без БД возвращает пустой результат."""
        self.orch.memory = None
        history = await self.orch.get_validation_history()
        self.assertEqual(history["total"], 0)
        self.assertEqual(history["results"], [])

    async def test_validation_history_structure(self):
        """Структура истории валидации корректна."""
        history = await self.orch.get_validation_history()
        self.assertIn("total", history)
        self.assertIn("results", history)
        self.assertIn("summary", history)


class TestOrchestratorFeedbackLoop(unittest.IsolatedAsyncioTestCase):
    """COS-4: Тесты feedback loop."""

    async def asyncSetUp(self):
        self.orch = Orchestrator(config_path="./configs")
        self.orch.memory = MockMemoryStore()

    async def test_feedback_no_db(self):
        """Feedback без БД возвращает None."""
        self.orch.memory = None
        feedback = await self.orch._get_feedback_for_agent("seo", limit=5)
        self.assertIsNone(feedback)

    async def test_feedback_empty_results(self):
        """Feedback с пустыми результатами возвращает структуру с пустыми списками."""
        feedback = await self.orch._get_feedback_for_agent("seo", limit=5)
        # Mock возвращает пустой список rows → метод возвращает структуру с пустыми runs
        self.assertIsNotNone(feedback)
        self.assertEqual(feedback["runs"], [])
        self.assertEqual(feedback["patterns"], [])
        self.assertEqual(feedback["action_history"], [])
        self.assertEqual(feedback["avg_score"], 0.0)


class TestOrchestratorGitVersioning(unittest.IsolatedAsyncioTestCase):
    """COS-1: Тесты git versioning."""

    async def asyncSetUp(self):
        self.orch = Orchestrator(config_path="./configs")

    async def test_git_commit_file_not_repo(self):
        """git_commit_file возвращает True (skip) если не git-репозиторий."""
        from scripts.actions.file_utils import git_commit_file
        result = git_commit_file("/tmp/nonexistent.txt", message="test")
        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
