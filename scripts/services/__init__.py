# -*- coding: utf-8 -*-
"""
Сервисный слой оркестратора (P1-1).

Разделение Orchestrator на специализированные сервисы:
- CycleManager: управление жизненным циклом агентов
- TaskDispatcher: диспетчеризация trend-рекомендаций и analytics-задач
- ReportGenerator: генерация отчётов, health, метрики
- ActionExecutor: выполнение actions (legacy + plugin)
"""

from .action_executor import ActionExecutor
from .cycle_manager import CycleManager
from .report_generator import ReportGenerator
from .task_dispatcher import TaskDispatcher

__all__ = [
    "CycleManager",
    "TaskDispatcher",
    "ReportGenerator",
    "ActionExecutor",
]
