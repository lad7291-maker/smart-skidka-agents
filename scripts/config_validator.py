#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║              CONFIG VALIDATOR — P2-3                                 ║
║                    smart-skidka.ru                                   ║
╠══════════════════════════════════════════════════════════════════════╣
║  JSON Schema валидация конфигураций агентов.                         ║
║                                                                      ║
║  Использование:                                                      ║
║    from config_validator import validate_agent_config, ConfigError ║
║    validate_agent_config({"agent_name": "seo-agent", ...})         ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger("config_validator")

# P2-3: Lazy import jsonschema для избежания зависимости при отсутствии
try:
    import jsonschema
    from jsonschema import ValidationError as SchemaValidationError
    _JSONSCHEMA_AVAILABLE = True
except ImportError:
    _JSONSCHEMA_AVAILABLE = False
    SchemaValidationError = Exception  # type: ignore


# ═══════════════════════════════════════════════════════════════════════════════
# Exceptions
# ═══════════════════════════════════════════════════════════════════════════════

class ConfigError(Exception):
    """Ошибка валидации конфигурации агента."""


# ═══════════════════════════════════════════════════════════════════════════════
# Schema loading
# ═══════════════════════════════════════════════════════════════════════════════

_SCHEMA_PATH = Path(os.getenv("AGENT_CONFIG_SCHEMA", "./configs/agent-config.schema.json"))
_schema: Optional[Dict[str, Any]] = None


def _load_schema() -> Dict[str, Any]:
    """Загружает JSON Schema из файла."""
    global _schema
    if _schema is not None:
        return _schema

    path = _SCHEMA_PATH
    if not path.exists():
        # Fallback: используем inline schema
        logger.warning("schema_file_not_found", path=str(path), fallback="inline")
        _schema = _get_inline_schema()
        return _schema

    try:
        _schema = json.loads(path.read_text(encoding="utf-8"))
        logger.info("schema_loaded", path=str(path))
        return _schema
    except (json.JSONDecodeError, OSError) as e:
        logger.error("schema_load_failed", path=str(path), error=str(e))
        _schema = _get_inline_schema()
        return _schema


def _get_inline_schema() -> Dict[str, Any]:
    """Встроенная схема (fallback если файл не найден)."""
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "AgentConfig",
        "type": "object",
        "required": ["agent_name", "version", "system_prompt"],
        "properties": {
            "agent_name": {
                "type": "string",
                "pattern": "^[a-z0-9_-]+$",
            },
            "version": {
                "type": "string",
                "pattern": "^\\d+\\.\\d+\\.\\d+$",
            },
            "description": {"type": "string"},
            "enabled": {"type": "boolean", "default": True},
            "system_prompt": {"type": "string", "minLength": 1},
            "schedule": {
                "type": "object",
                "properties": {
                    "interval": {"type": "integer", "minimum": 1},
                    "enabled": {"type": "boolean", "default": True},
                    "run_once": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
            "llm_settings": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "temperature": {"type": "number", "minimum": 0, "maximum": 2},
                    "max_tokens": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
            "validation_rules": {
                "type": "object",
                "properties": {
                    "required_fields": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "min_score": {"type": "number", "minimum": 0, "maximum": 1},
                    "max_execution_time": {"type": "integer", "minimum": 1},
                },
                "additionalProperties": False,
            },
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["name"],
                    "properties": {
                        "name": {"type": "string"},
                        "input_map": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                        },
                        "condition": {"type": "string"},
                    },
                    "additionalProperties": False,
                },
            },
        },
        "additionalProperties": False,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Validation functions
# ═══════════════════════════════════════════════════════════════════════════════

def validate_agent_config(config: Dict[str, Any]) -> None:
    """
    Валидирует конфигурацию агента по JSON Schema.

    Args:
        config: Словарь с конфигурацией агента

    Raises:
        ConfigError: Если конфигурация невалидна
    """
    if not _JSONSCHEMA_AVAILABLE:
        logger.warning("jsonschema_not_available", skip_validation=True)
        # P2-3: Без jsonschema делаем минимальную ручную проверку
        _minimal_validation(config)
        return

    schema = _load_schema()
    try:
        jsonschema.validate(instance=config, schema=schema)
    except SchemaValidationError as e:
        raise ConfigError(f"Config validation failed: {e.message}") from e

    # Дополнительные семантические проверки
    _semantic_validation(config)


def _minimal_validation(config: Dict[str, Any]) -> None:
    """Минимальная валидация без jsonschema (fallback)."""
    required = ["agent_name", "version", "system_prompt"]
    for field in required:
        if field not in config:
            raise ConfigError(f"Missing required field: {field}")

    if not isinstance(config.get("agent_name"), str):
        raise ConfigError("agent_name must be a string")
    if not isinstance(config.get("version"), str):
        raise ConfigError("version must be a string")
    if not isinstance(config.get("system_prompt"), str):
        raise ConfigError("system_prompt must be a string")

    llm = config.get("llm_settings", {})
    temp = llm.get("temperature")
    if temp is not None and not (0 <= temp <= 2):
        raise ConfigError(f"temperature must be between 0 and 2, got {temp}")

    max_tokens = llm.get("max_tokens")
    if max_tokens is not None and max_tokens < 1:
        raise ConfigError(f"max_tokens must be >= 1, got {max_tokens}")


def _semantic_validation(config: Dict[str, Any]) -> None:
    """Семантические проверки, не покрываемые JSON Schema."""
    agent_name = config.get("agent_name", "")

    # Проверка: agent_name должен совпадать с именем файла (если известно)
    # Это проверяется на уровне AgentConfig

    # Проверка: temperature в разумных пределах
    llm = config.get("llm_settings", {})
    temp = llm.get("temperature")
    if temp is not None and temp > 1.5:
        logger.warning(
            "high_temperature",
            agent=agent_name,
            temperature=temp,
            message="temperature > 1.5 may produce unpredictable results",
        )

    # Проверка: system_prompt не пустой
    prompt = config.get("system_prompt", "")
    if len(prompt.strip()) < 10:
        raise ConfigError("system_prompt is too short (min 10 chars)")

    # Проверка: validation_rules.min_score в разумных пределах
    rules = config.get("validation_rules", {})
    min_score = rules.get("min_score")
    if min_score is not None and min_score > 0.95:
        logger.warning(
            "very_high_min_score",
            agent=agent_name,
            min_score=min_score,
            message="min_score > 0.95 may cause frequent validation failures",
        )

    # Проверка: actions имеют уникальные имена
    actions = config.get("actions", [])
    names = [a.get("name") for a in actions if isinstance(a, dict)]
    if len(names) != len(set(names)):
        raise ConfigError("Duplicate action names found")


# ═══════════════════════════════════════════════════════════════════════════════
# Integration with AgentConfig
# ═══════════════════════════════════════════════════════════════════════════════

def validate_config_file(path: Path) -> List[str]:
    """
    Валидирует JSON-файл конфигурации.

    Args:
        path: Путь к JSON-файлу

    Returns:
        Список ошибок (пустой если валидно)
    """
    errors: List[str] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        return [f"Invalid JSON: {e}"]
    except OSError as e:
        return [f"Cannot read file: {e}"]

    try:
        validate_agent_config(config)
    except ConfigError as e:
        errors.append(str(e))

    return errors


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> int:
    """CLI: validate all configs in a directory."""
    import argparse

    parser = argparse.ArgumentParser(description="Validate agent configs")
    parser.add_argument("--dir", default="./configs", help="Config directory")
    parser.add_argument("--schema", default="./configs/agent-config.schema.json", help="Schema file")
    args = parser.parse_args()

    global _SCHEMA_PATH
    _SCHEMA_PATH = Path(args.schema)

    config_dir = Path(args.dir)
    if not config_dir.exists():
        print(f"Directory not found: {config_dir}")
        return 1

    all_valid = True
    for config_file in config_dir.glob("*.json"):
        # Skip secrets and schema files
        if config_file.name in ("secrets.enc.json", "agent-config.schema.json"):
            continue

        errors = validate_config_file(config_file)
        if errors:
            all_valid = False
            print(f"❌ {config_file.name}: {errors[0]}")
        else:
            print(f"✅ {config_file.name}")

    return 0 if all_valid else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
