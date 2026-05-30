#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║              TEMPERATURE CALIBRATION — Автокалибровка                ║
║                         smart-skidka.ru                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  Автоматическая калибровка temperature LLM на основе истории        ║
║  успешности (validation_score).                                      ║
║                                                                      ║
║  P3-4: Автоматическая калибровка temperature                         ║
║                                                                      ║
║  Алгоритм: ε-greedy bandit с EMA (exponential moving average)       ║
║    - Дискретные "arms": [0.5, 0.6, 0.7, 0.8, 0.9]                  ║
║    - 15% exploration (ε), 85% exploitation                           ║
║    - EMA α=0.3 для быстрой адаптации к изменениям                   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger("temperature_calibration")

# ═══════════════════════════════════════════════════════════════════════════════
# Конфигурация
# ═══════════════════════════════════════════════════════════════════════════════

# Дискретные значения temperature (arms бандита)
DEFAULT_TEMPERATURE_ARMS = [0.5, 0.6, 0.7, 0.8, 0.9]

# EMA alpha — вес нового наблюдения (0.3 = 30% новое, 70% история)
DEFAULT_EMA_ALPHA = float(os.getenv("TEMP_CALIBRATION_EMA_ALPHA", "0.3"))

# Epsilon — вероятность exploration
DEFAULT_EPSILON = float(os.getenv("TEMP_CALIBRATION_EPSILON", "0.15"))

# Минимум запусков на arm перед exploitation
DEFAULT_MIN_RUNS_PER_ARM = int(os.getenv("TEMP_CALIBRATION_MIN_RUNS", "5"))

# Директория для хранения калибровок
DEFAULT_CALIBRATION_DIR = Path(os.getenv("TEMP_CALIBRATION_DIR", "./configs/temperatures"))


# ═══════════════════════════════════════════════════════════════════════════════
# Data-классы
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class TemperatureArm:
    """Одно значение temperature (arm бандита)."""
    temperature: float
    ema_score: float = 0.0
    run_count: int = 0
    last_used: Optional[str] = None

    def record_score(self, score: float, alpha: float) -> None:
        """Обновляет EMA score."""
        if self.run_count == 0:
            self.ema_score = score
        else:
            self.ema_score = alpha * score + (1 - alpha) * self.ema_score
        self.run_count += 1
        self.last_used = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentCalibration:
    """Калибровка temperature для конкретного агента."""
    agent_name: str
    enabled: bool = True
    arms: List[TemperatureArm] = field(default_factory=list)
    epsilon: float = DEFAULT_EPSILON
    ema_alpha: float = DEFAULT_EMA_ALPHA
    min_runs_per_arm: int = DEFAULT_MIN_RUNS_PER_ARM
    default_temperature: float = 0.7
    updated_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def __post_init__(self):
        if not self.arms:
            self.arms = [TemperatureArm(t) for t in DEFAULT_TEMPERATURE_ARMS]

    def select_temperature(self) -> float:
        """
        Выбирает temperature по ε-greedy стратегии.

        1. Если калибровка отключена — возвращает default_temperature
        2. Если есть arm с run_count < min_runs — forced exploration
        3. С вероятностью ε — random exploration
        4. Иначе — exploitation (arm с максимальным ema_score)
        """
        if not self.enabled:
            return self.default_temperature

        # Forced exploration: недоисследованные arms
        underexplored = [a for a in self.arms if a.run_count < self.min_runs_per_arm]
        if underexplored:
            chosen = random.choice(underexplored)
            logger.debug(
                "temperature_forced_exploration",
                agent=self.agent_name,
                temperature=chosen.temperature,
                runs=chosen.run_count,
            )
            return chosen.temperature

        # ε-greedy
        if random.random() < self.epsilon:
            chosen = random.choice(self.arms)
            logger.debug(
                "temperature_exploration",
                agent=self.agent_name,
                temperature=chosen.temperature,
                epsilon=self.epsilon,
            )
            return chosen.temperature

        # Exploitation: лучший arm по EMA
        best = max(self.arms, key=lambda a: a.ema_score)
        logger.debug(
            "temperature_exploitation",
            agent=self.agent_name,
            temperature=best.temperature,
            ema_score=round(best.ema_score, 3),
        )
        return best.temperature

    def record_result(self, temperature: float, score: float) -> None:
        """Записывает результат запуска для данного temperature."""
        for arm in self.arms:
            if abs(arm.temperature - temperature) < 0.001:
                arm.record_score(score, self.ema_alpha)
                self.updated_at = datetime.now().isoformat()
                logger.info(
                    "temperature_result_recorded",
                    agent=self.agent_name,
                    temperature=temperature,
                    score=score,
                    ema=round(arm.ema_score, 3),
                    runs=arm.run_count,
                )
                return
        logger.warning("temperature_arm_not_found", agent=self.agent_name, temperature=temperature)

    def get_stats(self) -> Dict[str, Any]:
        """Возвращает статистику калибровки."""
        return {
            "agent_name": self.agent_name,
            "enabled": self.enabled,
            "epsilon": self.epsilon,
            "ema_alpha": self.ema_alpha,
            "min_runs_per_arm": self.min_runs_per_arm,
            "arms": [
                {
                    "temperature": a.temperature,
                    "ema_score": round(a.ema_score, 3),
                    "run_count": a.run_count,
                    "last_used": a.last_used,
                }
                for a in self.arms
            ],
            "best_arm": self._get_best_arm(),
            "updated_at": self.updated_at,
        }

    def _get_best_arm(self) -> Optional[Dict[str, Any]]:
        """Возвращает лучший arm."""
        if not self.arms or all(a.run_count == 0 for a in self.arms):
            return None
        best = max(self.arms, key=lambda a: a.ema_score)
        return {
            "temperature": best.temperature,
            "ema_score": round(best.ema_score, 3),
            "run_count": best.run_count,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "enabled": self.enabled,
            "epsilon": self.epsilon,
            "ema_alpha": self.ema_alpha,
            "min_runs_per_arm": self.min_runs_per_arm,
            "default_temperature": self.default_temperature,
            "arms": [a.to_dict() for a in self.arms],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentCalibration":
        """Создаёт из словаря."""
        arms = [TemperatureArm(**a) for a in data.get("arms", [])]
        return cls(
            agent_name=data["agent_name"],
            enabled=data.get("enabled", True),
            arms=arms,
            epsilon=data.get("epsilon", DEFAULT_EPSILON),
            ema_alpha=data.get("ema_alpha", DEFAULT_EMA_ALPHA),
            min_runs_per_arm=data.get("min_runs_per_arm", DEFAULT_MIN_RUNS_PER_ARM),
            default_temperature=data.get("default_temperature", 0.7),
            updated_at=data.get("updated_at", datetime.now().isoformat()),
        )


# ═══════════════════════════════════════════════════════════════════════════════
# TemperatureCalibrator — центральный класс
# ═══════════════════════════════════════════════════════════════════════════════

class TemperatureCalibrator:
    """
    Центральный калибратор temperature.

    Управляет калибровками всех агентов, сохраняет/загружает из JSON.
    """

    def __init__(self, calibration_dir: Optional[Path] = None) -> None:
        self.calibration_dir = calibration_dir or DEFAULT_CALIBRATION_DIR
        self.calibration_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, AgentCalibration] = {}
        self.logger = structlog.get_logger("temperature_calibrator")

    def _get_calibration_file(self, agent_name: str) -> Path:
        return self.calibration_dir / f"{agent_name}.temperature.json"

    def load_calibration(self, agent_name: str) -> AgentCalibration:
        """Загружает калибровку агента."""
        if agent_name in self._cache:
            return self._cache[agent_name]

        cal_file = self._get_calibration_file(agent_name)
        if cal_file.exists():
            try:
                data = json.loads(cal_file.read_text(encoding="utf-8"))
                cal = AgentCalibration.from_dict(data)
                self._cache[agent_name] = cal
                return cal
            except Exception as e:
                self.logger.warning("calibration_load_failed", agent=agent_name, error=str(e))

        # Создаём новую
        cal = AgentCalibration(agent_name=agent_name)
        self._cache[agent_name] = cal
        return cal

    def save_calibration(self, agent_name: str) -> None:
        """Сохраняет калибровку агента."""
        if agent_name not in self._cache:
            return
        cal = self._cache[agent_name]
        cal_file = self._get_calibration_file(agent_name)
        cal_file.write_text(
            json.dumps(cal.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def is_enabled(self, agent_name: str) -> bool:
        """Проверяет, включена ли калибровка для агента."""
        cal = self.load_calibration(agent_name)
        return cal.enabled

    def select_temperature(self, agent_name: str) -> float:
        """
        Выбирает temperature для агента.

        Returns:
            Выбранное значение temperature.
        """
        cal = self.load_calibration(agent_name)
        if not cal.enabled:
            return cal.default_temperature
        return cal.select_temperature()

    def record_result(self, agent_name: str, temperature: float, score: float) -> None:
        """Записывает результат запуска."""
        cal = self.load_calibration(agent_name)
        if not cal.enabled:
            return
        cal.record_result(temperature, score)
        self.save_calibration(agent_name)

    def get_stats(self, agent_name: Optional[str] = None) -> Dict[str, Any]:
        """Возвращает статистику калибровки."""
        if agent_name:
            cal = self.load_calibration(agent_name)
            return cal.get_stats()

        # Все агенты
        result = {}
        for f in self.calibration_dir.glob("*.temperature.json"):
            name = f.stem.replace(".temperature", "")
            result[name] = self.load_calibration(name).get_stats()
        return result

    def enable(self, agent_name: str) -> None:
        """Включает калибровку для агента."""
        cal = self.load_calibration(agent_name)
        cal.enabled = True
        self.save_calibration(agent_name)

    def disable(self, agent_name: str) -> None:
        """Выключает калибровку для агента."""
        cal = self.load_calibration(agent_name)
        cal.enabled = False
        self.save_calibration(agent_name)

    def reset(self, agent_name: str) -> None:
        """Сбрасывает калибровку агента."""
        cal = AgentCalibration(agent_name=agent_name)
        self._cache[agent_name] = cal
        self.save_calibration(agent_name)


# ═══════════════════════════════════════════════════════════════════════════════
# Integration helpers
# ═══════════════════════════════════════════════════════════════════════════════

def get_calibrator() -> TemperatureCalibrator:
    """Возвращает singleton calibrator."""
    return TemperatureCalibrator()
