#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для JSON Schema валидации конфигов (P2-3).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, '/opt/smart-skidka-agents')
sys.path.insert(0, '/opt/smart-skidka-agents/scripts')

from scripts.config_validator import (
    validate_agent_config,
    validate_config_file,
    ConfigError,
    _minimal_validation,
    _semantic_validation,
)


class TestValidateAgentConfig(unittest.TestCase):
    """Тесты валидации конфигурации агента."""

    def _valid_config(self, **overrides):
        base = {
            "agent_name": "test-agent",
            "version": "1.0.0",
            "description": "Test agent",
            "enabled": True,
            "system_prompt": "You are a test agent.",
            "schedule": {"interval": 3600, "enabled": True, "run_once": False},
            "llm_settings": {"model": "deepseek-chat", "temperature": 0.7, "max_tokens": 2048},
            "validation_rules": {
                "required_fields": ["title"],
                "min_score": 0.7,
                "max_execution_time": 30000,
            },
            "actions": [{"name": "test_action", "input_map": {"key": "value"}, "condition": "has_key"}],
        }
        base.update(overrides)
        return base

    def test_valid_config_passes(self):
        """Валидный конфиг проходит проверку."""
        validate_agent_config(self._valid_config())

    def test_missing_agent_name(self):
        """Отсутствие agent_name — ошибка."""
        config = self._valid_config()
        del config["agent_name"]
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("agent_name", str(ctx.exception))

    def test_missing_version(self):
        """Отсутствие version — ошибка."""
        config = self._valid_config()
        del config["version"]
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("version", str(ctx.exception))

    def test_missing_system_prompt(self):
        """Отсутствие system_prompt — ошибка."""
        config = self._valid_config()
        del config["system_prompt"]
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("system_prompt", str(ctx.exception))

    def test_invalid_version_format(self):
        """Невалидный semver — ошибка."""
        config = self._valid_config(version="not-semver")
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("not-semver", str(ctx.exception))

    def test_invalid_agent_name_pattern(self):
        """agent_name с пробелами — ошибка."""
        config = self._valid_config(agent_name="bad name")
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("bad name", str(ctx.exception))

    def test_empty_system_prompt(self):
        """Пустой system_prompt — ошибка."""
        config = self._valid_config(system_prompt="")
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("non-empty", str(ctx.exception).lower())

    def test_temperature_too_high(self):
        """temperature > 2 — ошибка."""
        config = self._valid_config(llm_settings={"temperature": 2.5})
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("2.5", str(ctx.exception))

    def test_temperature_negative(self):
        """temperature < 0 — ошибка."""
        config = self._valid_config(llm_settings={"temperature": -0.1})
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("-0.1", str(ctx.exception))

    def test_max_tokens_zero(self):
        """max_tokens = 0 — ошибка."""
        config = self._valid_config(llm_settings={"max_tokens": 0})
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("0", str(ctx.exception))

    def test_min_score_above_one(self):
        """min_score > 1 — ошибка."""
        config = self._valid_config(validation_rules={"min_score": 1.5})
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("1.5", str(ctx.exception))

    def test_duplicate_action_names(self):
        """Дублирующиеся имена action — ошибка."""
        config = self._valid_config(actions=[
            {"name": "action1"},
            {"name": "action1"},
        ])
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("Duplicate", str(ctx.exception))

    def test_short_system_prompt(self):
        """Слишком короткий system_prompt — ошибка."""
        config = self._valid_config(system_prompt="Hi")
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("system_prompt", str(ctx.exception))

    def test_unknown_top_level_property(self):
        """Неизвестное свойство верхнего уровня — ошибка."""
        config = self._valid_config()
        config["unknown_field"] = "value"
        with self.assertRaises(ConfigError) as ctx:
            validate_agent_config(config)
        self.assertIn("unknown", str(ctx.exception).lower())

    def test_valid_real_configs(self):
        """Реальные конфиги проходят валидацию."""
        for name in ["seo-agent", "smm-agent", "content-agent"]:
            errors = validate_config_file(Path(f"configs/{name}.json"))
            self.assertEqual(errors, [], f"{name} should be valid")


class TestMinimalValidation(unittest.TestCase):
    """Тесты fallback-валидации без jsonschema."""

    def test_missing_required(self):
        """Отсутствие обязательного поля."""
        with self.assertRaises(ConfigError):
            _minimal_validation({"version": "1.0.0"})

    def test_wrong_type(self):
        """Неверный тип."""
        with self.assertRaises(ConfigError):
            _minimal_validation({
                "agent_name": 123,
                "version": "1.0.0",
                "system_prompt": "test",
            })


class TestConfigFileValidation(unittest.TestCase):
    """Тесты валидации файлов."""

    def test_valid_file(self):
        """Валидный файл."""
        errors = validate_config_file(Path("configs/seo-agent.json"))
        self.assertEqual(errors, [])

    def test_nonexistent_file(self):
        """Несуществующий файл."""
        errors = validate_config_file(Path("configs/nonexistent.json"))
        self.assertTrue(len(errors) > 0)

    def test_invalid_json(self):
        """Невалидный JSON."""
        import tempfile
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{not json")
            path = Path(f.name)
        errors = validate_config_file(path)
        self.assertTrue(len(errors) > 0)
        path.unlink()


if __name__ == "__main__":
    unittest.main()
