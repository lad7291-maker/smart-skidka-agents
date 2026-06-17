#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║              TEMPERATURE CALIBRATION — P1-19                         ║
║                    smart-skidka.ru                                   ║
╠══════════════════════════════════════════════════════════════════════╣
║  Multi-arm bandit temperature calibration для LLM.                  ║
║  Epsilon-greedy: explore (случайный arm) vs exploit (лучший arm).   ║
║                                                                      ║
║  Архитектура:                                                        ║
║  • TemperatureArm — один arm с temperature, EMA score, run_count   ║
║  • AgentCalibration — набор arms для одного агента                 ║
║  • TemperatureCalibrator — управление калибровками всех агентов   ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import os
import random
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger("temperature_calibration")

# ═══════════════════════════════════════════════════════════════════════════════
# Конфигурация
# ═══════════════════════════════════════════════════════════════════════════════

DEFAULT_TEMPERATURE_ARMS: List[float] = [0.3, 0.5, 0.7, 0.8, 0.9]
DEFAULT_EPSILON: float = float(os.getenv("TEMP_CALIBRATION_EPSILON", "0.2"))
DEFAULT_EMA_ALPHA: float = float(os.getenv("TEMP_CALIBRATION_EMA_ALPHA", "0.3"))
DEFAULT_MIN_RUNS_PER_ARM: int = int(os.getenv("TEMP_CALIBRATION_MIN_RUNS", "2"))
DEFAULT_CALIBRATION_DIR: Path = Path(os.getenv("TEMP_CALIBRATION_DIR", "./configs/temperatures"))


# ═══════════════════════════════════════════════════════════════════════════════
# Data-классы
# ═══════════════════════════════════════════════════════════════════════════════


@dataclass
class TemperatureArm:
    """Один arm multi-arm bandit."""

    temperature: float
    ema_score: float = 0.0
    run_count: int = 0
    last_used: Optional[str] = None

    def record_score(self, score: float, alpha: float = DEFAULT_EMA_ALPHA) -> None:
        """Обновляет EMA score."""
        if self.run_count == 0:
            self.ema_score = score
        else:
            self.ema_score = alpha * score + (1 - alpha) * self.ema_score
        self.run_count += 1
        self.last_used = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "temperature": self.temperature,
            "ema_score": self.ema_score,
            "run_count": self.run_count,
            "last_used": self.last_used,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TemperatureArm:
        return cls(
            temperature=data["temperature"],
            ema_score=data.get("ema_score", 0.0),
            run_count=data.get("run_count", 0),
            last_used=data.get("last_used"),
        )


@dataclass
class AgentCalibration:
    """Калибровка temperature для одного агента (multi-arm bandit)."""

    agent_name: str
    arms: List[TemperatureArm] = field(default_factory=list)
    enabled: bool = True
    default_temperature: float = 0.7
    epsilon: float = DEFAULT_EPSILON
    min_runs_per_arm: int = DEFAULT_MIN_RUNS_PER_ARM

    def __post_init__(self):
        if not self.arms:
            self.arms = [TemperatureArm(t) for t in DEFAULT_TEMPERATURE_ARMS]

    def _get_best_arm(self) -> Optional[TemperatureArm]:
        """Возвращает arm с наивысшим EMA score (минимум 1 запуск)."""
        tried = [a for a in self.arms if a.run_count > 0]
        if not tried:
            return None
        return max(tried, key=lambda a: a.ema_score)

    def _needs_forced_exploration(self) -> bool:
        """True если есть arms с run_count < min_runs_per_arm."""
        return any(a.run_count < self.min_runs_per_arm for a in self.arms)

    def select_temperature(self) -> float:
        """
        Epsilon-greedy выбор temperature.

        - Сначала forced exploration (все arms min_runs_per_arm раз)
        - Потом epsilon-greedy: explore с вероятностью epsilon
        """
        if not self.enabled:
            return self.default_temperature

        # Forced exploration: выбираем arm с наименьшим run_count
        if self._needs_forced_exploration():
            return min(self.arms, key=lambda a: a.run_count).temperature

        # Epsilon-greedy
        if random.random() < self.epsilon:
            # Explore: случайный arm
            return random.choice(self.arms).temperature
        else:
            # Exploit: лучший arm
            best = self._get_best_arm()
            return best.temperature if best else self.default_temperature

    def record_result(self, temperature: float, score: float) -> None:
        """Записывает результат для arm с данной temperature."""
        for arm in self.arms:
            if abs(arm.temperature - temperature) < 0.001:
                arm.record_score(score)
                return
        logger.warning("arm_not_found", temperature=temperature, agent=self.agent_name)

    def get_stats(self) -> Dict[str, Any]:
        best = self._get_best_arm()
        return {
            "agent_name": self.agent_name,
            "enabled": self.enabled,
            "arms": [a.to_dict() for a in self.arms],
            "best_arm": best.to_dict() if best else None,
            "epsilon": self.epsilon,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "enabled": self.enabled,
            "default_temperature": self.default_temperature,
            "epsilon": self.epsilon,
            "min_runs_per_arm": self.min_runs_per_arm,
            "arms": [a.to_dict() for a in self.arms],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentCalibration:
        cal = cls(
            agent_name=data["agent_name"],
            enabled=data.get("enabled", True),
            default_temperature=data.get("default_temperature", 0.7),
            epsilon=data.get("epsilon", DEFAULT_EPSILON),
            min_runs_per_arm=data.get("min_runs_per_arm", DEFAULT_MIN_RUNS_PER_ARM),
        )
        cal.arms = [TemperatureArm.from_dict(a) for a in data.get("arms", [])]
        return cal


# ═══════════════════════════════════════════════════════════════════════════════
# TemperatureCalibrator
# ═══════════════════════════════════════════════════════════════════════════════


class TemperatureCalibrator:
    """
    Управляет калибровками temperature для всех агентов.
    """

    def __init__(self, calibration_dir: Optional[Path] = None) -> None:
        self.calibration_dir = calibration_dir or DEFAULT_CALIBRATION_DIR
        self.calibration_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, AgentCalibration] = {}
        self.logger = structlog.get_logger("temperature_calibrator")

    def _get_file(self, agent_name: str) -> Path:
        return self.calibration_dir / f"{agent_name}.json"

    def load_calibration(self, agent_name: str) -> AgentCalibration:
        """Загружает или создаёт калибровку для агента."""
        if agent_name in self._cache:
            return self._cache[agent_name]

        file_path = self._get_file(agent_name)
        if file_path.exists():
            try:
                data = json.loads(file_path.read_text(encoding="utf-8"))
                cal = AgentCalibration.from_dict(data)
                self._cache[agent_name] = cal
                return cal
            except Exception as e:
                self.logger.warning("load_failed", agent=agent_name, error=str(e))

        cal = AgentCalibration(agent_name=agent_name)
        self._cache[agent_name] = cal
        return cal

    def save_calibration(self, agent_name: str) -> None:
        """Сохраняет калибровку агента."""
        cal = self._cache.get(agent_name)
        if cal is None:
            return
        file_path = self._get_file(agent_name)
        try:
            file_path.write_text(
                json.dumps(cal.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            self.logger.warning("save_failed", agent=agent_name, error=str(e))

    def is_enabled(self, agent_name: str) -> bool:
        return self.load_calibration(agent_name).enabled

    def enable(self, agent_name: str) -> None:
        cal = self.load_calibration(agent_name)
        cal.enabled = True
        self.save_calibration(agent_name)

    def disable(self, agent_name: str) -> None:
        cal = self.load_calibration(agent_name)
        cal.enabled = False
        self.save_calibration(agent_name)

    def select_temperature(self, agent_name: str) -> float:
        """Выбирает temperature для агента."""
        cal = self.load_calibration(agent_name)
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
            return self.load_calibration(agent_name).get_stats()
        # Все агенты
        stats = {}
        for f in self.calibration_dir.glob("*.json"):
            name = f.stem
            stats[name] = self.load_calibration(name).get_stats()
        return stats

    def reset(self, agent_name: str) -> None:
        """Сбрасывает калибровку агента."""
        cal = AgentCalibration(agent_name=agent_name)
        self._cache[agent_name] = cal
        self.save_calibration(agent_name)

    # P1-19: Compatibility with single-agent API used in orchestrator
    def get_temperature(self, base_temperature: float = 0.7) -> float:
        """Compatibility: returns temperature for the first cached agent or default."""
        # This is called from AgentRunner which doesn't pass agent_name
        # Return base_temperature — the actual selection happens via select_temperature
        return base_temperature


# ═══════════════════════════════════════════════════════════════════════════════
# CLI / Utilities
# ═══════════════════════════════════════════════════════════════════════════════


def get_calibrator(calibration_dir: Optional[Path] = None) -> TemperatureCalibrator:
    return TemperatureCalibrator(calibration_dir)


def record_run(
    agent_name: str,
    temperature: float,
    score: float,
    calibration_dir: Optional[Path] = None,
) -> None:
    calibrator = TemperatureCalibrator(calibration_dir)
    calibrator.record_result(agent_name, temperature, score)


def get_stats(agent_name: Optional[str] = None, calibration_dir: Optional[Path] = None) -> Dict[str, Any]:
    calibrator = TemperatureCalibrator(calibration_dir)
    return calibrator.get_stats(agent_name)
