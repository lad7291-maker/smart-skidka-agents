# -*- coding: utf-8 -*-
"""
Сервисный слой оркестратора (P1-1).

Разделение Orchestrator на специализированные сервисы:
- CycleManager: управление жизненным циклом агентов
- TaskDispatcher: диспетчеризация trend-рекомендаций и analytics-задач
- ReportGenerator: генерация отчётов, health, метрики
- ActionExecutor: выполнение actions (legacy + plugin)
"""

from .cycle_manager import CycleManager
from .task_dispatcher import TaskDispatcher
from .report_generator import ReportGenerator
from .action_executor import ActionExecutor

__all__ = [
    "CycleManager",
    "TaskDispatcher",
    "ReportGenerator",
    "ActionExecutor",
]
