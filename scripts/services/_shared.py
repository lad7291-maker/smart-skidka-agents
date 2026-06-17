# -*- coding: utf-8 -*-
"""
Shared constants для сервисного слоя.

P1-1: Вынесены из orchestrator.py для избежания циклических импортов.
"""

from typing import List

AGENT_NAMES: List[str] = [
    "seo_agent",
    "smm_agent",
    "performance_agent",
    "email_agent",
    "analytics_agent",
    "content_agent",
    "trend_agent",
]


def _get_agent_type(agent_name: str) -> str:
    """Возвращает тип агента из имени (префикс до '-')."""
    return agent_name.split("-")[0] if "-" in agent_name else agent_name
