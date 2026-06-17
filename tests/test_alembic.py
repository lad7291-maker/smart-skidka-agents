#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для alembic миграций (P3-5).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, "/opt/smart-skidka-agents")


class TestAlembicSetup(unittest.TestCase):
    """Тесты конфигурации alembic."""

    def test_alembic_ini_exists(self):
        """alembic.ini существует."""
        self.assertTrue(Path("alembic.ini").exists())

    def test_alembic_directory_exists(self):
        """Директория alembic существует."""
        self.assertTrue(Path("alembic").exists())
        self.assertTrue(Path("alembic/versions").exists())
        self.assertTrue(Path("alembic/env.py").exists())

    def test_initial_migration_exists(self):
        """Начальная миграция существует."""
        migration = Path("alembic/versions/001_initial_schema.py")
        self.assertTrue(migration.exists())

    def test_migration_syntax(self):
        """Миграция импортируется без ошибок."""
        import importlib.util
        import sys

        # alembic.op needs to be importable
        sys.path.insert(0, "/opt/smart-skidka-agents/.venv/lib/python3.12/site-packages")
        spec = importlib.util.spec_from_file_location("migration", "alembic/versions/001_initial_schema.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertTrue(hasattr(mod, "upgrade"))
        self.assertTrue(hasattr(mod, "downgrade"))
        self.assertEqual(mod.revision, "001")

    def test_alembic_ini_has_database_url(self):
        """alembic.ini содержит URL базы данных."""
        content = Path("alembic.ini").read_text()
        self.assertIn("sqlalchemy.url", content)
        self.assertIn("postgresql://", content)

    def test_migration_creates_core_tables(self):
        """Миграция содержит создание core таблиц."""
        content = Path("alembic/versions/001_initial_schema.py").read_text()
        tables = [
            "orchestrator_cycles",
            "agent_results",
            "metrics",
            "agent_errors",
            "agent_memory",
            "generated_content",
            "agent_tasks",
        ]
        for table in tables:
            self.assertIn(f"op.create_table(\n        '{table}'", content)

    def test_migration_creates_trend_tables(self):
        """Миграция содержит создание trend таблиц."""
        content = Path("alembic/versions/001_initial_schema.py").read_text()
        tables = [
            "trend_detections",
            "trend_data_sources",
            "trend_recommendations",
            "agent_trend_context",
        ]
        for table in tables:
            self.assertIn(f"op.create_table(\n        '{table}'", content)

    def test_migration_creates_indexes(self):
        """Миграция содержит создание индексов."""
        content = Path("alembic/versions/001_initial_schema.py").read_text()
        self.assertIn("op.create_index", content)
        self.assertIn("idx_agent_results_agent_name", content)

    def test_migration_has_downgrade(self):
        """Миграция содержит downgrade."""
        content = Path("alembic/versions/001_initial_schema.py").read_text()
        self.assertIn("def downgrade()", content)
        self.assertIn("op.drop_table", content)
        self.assertIn("op.drop_index", content)

    def test_alembic_history_shows_revision(self):
        """alembic history показывает revision 001."""
        import subprocess

        result = subprocess.run(
            ["alembic", "history"],
            capture_output=True,
            text=True,
            cwd="/opt/smart-skidka-agents",
        )
        self.assertIn("001", result.stdout)
        self.assertIn("Initial schema", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
