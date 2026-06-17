#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    A/B TESTING — Тестирование промптов               ║
║                         smart-skidka.ru                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  A/B тестирование system_prompt для агентов.                         ║
║  P3-3: Сравнивать разные system_prompt и выбирать лучший по score.   ║
║                                                                      ║
║  Архитектура:                                                        ║
║    - PromptVariant — dataclass для варианта промпта                  ║
║    - PromptVariantRegistry — хранение вариантов (DB + JSON fallback) ║
║    - ABTestRunner — запуск экспериментов, сбор статистики            ║
║    - ABTestEvaluator — оценка результатов, выбор победителя          ║
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

logger = structlog.get_logger("ab_testing")

# ═══════════════════════════════════════════════════════════════════════════════
# Конфигурация
# ═══════════════════════════════════════════════════════════════════════════════

AB_TEST_MIN_RUNS = int(os.getenv("AB_TEST_MIN_RUNS", "10"))
AB_TEST_CONFIDENCE_THRESHOLD = float(os.getenv("AB_TEST_CONFIDENCE_THRESHOLD", "0.05"))
AB_TEST_DEFAULT_VARIANTS_DIR = Path(os.getenv("AB_TEST_VARIANTS_DIR", "./configs/variants"))


# ═══════════════════════════════════════════════════════════════════════════════
# Data-классы
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class PromptVariant:
    """Вариант system_prompt для A/B тестирования."""
    agent_name: str
    variant_name: str
    system_prompt: str
    is_active: bool = False
    experiment_count: int = 0
    total_score: float = 0.0
    avg_score: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def record_score(self, score: float) -> None:
        """Записывает score одного запуска."""
        self.experiment_count += 1
        self.total_score += score
        self.avg_score = self.total_score / self.experiment_count

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ABTestResult:
    """Результат сравнения двух вариантов."""
    agent_name: str
    variant_a: str
    variant_b: str
    winner: Optional[str]
    confidence: float
    reason: str
    stats_a: Dict[str, Any]
    stats_b: Dict[str, Any]


# ═══════════════════════════════════════════════════════════════════════════════
# PromptVariantRegistry — хранение вариантов
# ═══════════════════════════════════════════════════════════════════════════════

class PromptVariantRegistry:
    """
    Реестр вариантов промптов.

    Хранит варианты в JSON-файлах (fallback) и синхронизирует с БД.
    """

    def __init__(self, variants_dir: Optional[Path] = None) -> None:
        self.variants_dir = variants_dir or AB_TEST_DEFAULT_VARIANTS_DIR
        self.variants_dir.mkdir(parents=True, exist_ok=True)
        self._cache: Dict[str, List[PromptVariant]] = {}
        self.logger = structlog.get_logger("variant_registry")

    def _get_variant_file(self, agent_name: str) -> Path:
        """Путь к файлу вариантов агента."""
        return self.variants_dir / f"{agent_name}.variants.json"

    def load_variants(self, agent_name: str) -> List[PromptVariant]:
        """Загружает варианты для агента из файла."""
        if agent_name in self._cache:
            return self._cache[agent_name]

        variant_file = self._get_variant_file(agent_name)
        if not variant_file.exists():
            return []

        try:
            data = json.loads(variant_file.read_text(encoding="utf-8"))
            variants = [PromptVariant(**v) for v in data.get("variants", [])]
            self._cache[agent_name] = variants
            return variants
        except Exception as e:
            self.logger.warning("variant_load_failed", agent=agent_name, error=str(e))
            return []

    def save_variants(self, agent_name: str, variants: List[PromptVariant]) -> None:
        """Сохраняет варианты для агента."""
        variant_file = self._get_variant_file(agent_name)
        data = {
            "agent_name": agent_name,
            "updated_at": datetime.now().isoformat(),
            "variants": [v.to_dict() for v in variants],
        }
        variant_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        self._cache[agent_name] = variants

    def get_variant(self, agent_name: str, variant_name: str) -> Optional[PromptVariant]:
        """Возвращает конкретный вариант."""
        variants = self.load_variants(agent_name)
        for v in variants:
            if v.variant_name == variant_name:
                return v
        return None

    def get_active_variant(self, agent_name: str) -> Optional[PromptVariant]:
        """Возвращает активный (победивший) вариант."""
        variants = self.load_variants(agent_name)
        for v in variants:
            if v.is_active:
                return v
        return None

    def add_variant(
        self,
        agent_name: str,
        variant_name: str,
        system_prompt: str,
        is_active: bool = False,
    ) -> PromptVariant:
        """Добавляет новый вариант промпта."""
        variants = self.load_variants(agent_name)

        # Проверяем уникальность имени
        for v in variants:
            if v.variant_name == variant_name:
                raise ValueError(f"Variant '{variant_name}' already exists for {agent_name}")

        variant = PromptVariant(
            agent_name=agent_name,
            variant_name=variant_name,
            system_prompt=system_prompt,
            is_active=is_active,
        )
        variants.append(variant)
        self.save_variants(agent_name, variants)
        self.logger.info("variant_added", agent=agent_name, variant=variant_name)
        return variant

    def select_variant_for_run(self, agent_name: str) -> Optional[PromptVariant]:
        """
        Выбирает вариант для запуска.

        Стратегия:
        - Если есть активный (победитель) — используем его (80% времени)
        - Иначе — round-robin между всеми вариантами
        """
        variants = self.load_variants(agent_name)
        if not variants:
            return None

        active = self.get_active_variant(agent_name)
        if active:
            # 80% шанс использовать победителя, 20% — исследовать другие
            if random.random() < 0.8:
                return active
            others = [v for v in variants if v.variant_name != active.variant_name]
            if others:
                return random.choice(others)
            return active

        # Round-robin: выбираем вариант с наименьшим experiment_count
        return min(variants, key=lambda v: v.experiment_count)

    def record_run_result(self, agent_name: str, variant_name: str, score: float) -> None:
        """Записывает результат запуска варианта."""
        variants = self.load_variants(agent_name)
        for v in variants:
            if v.variant_name == variant_name:
                v.record_score(score)
                self.save_variants(agent_name, variants)
                self.logger.info(
                    "variant_score_recorded",
                    agent=agent_name,
                    variant=variant_name,
                    score=score,
                    avg=v.avg_score,
                    runs=v.experiment_count,
                )
                return

    def list_all_variants(self) -> Dict[str, List[PromptVariant]]:
        """Возвращает все варианты всех агентов."""
        result = {}
        for f in self.variants_dir.glob("*.variants.json"):
            agent_name = f.stem.replace(".variants", "")
            result[agent_name] = self.load_variants(agent_name)
        return result


# ═══════════════════════════════════════════════════════════════════════════════
# ABTestEvaluator — оценка и выбор победителя
# ═══════════════════════════════════════════════════════════════════════════════

class ABTestEvaluator:
    """
    Оценивает результаты A/B тестов и выбирает победителя.
    """

    def __init__(self, registry: PromptVariantRegistry) -> None:
        self.registry = registry
        self.logger = structlog.get_logger("ab_evaluator")

    def evaluate(self, agent_name: str) -> Optional[ABTestResult]:
        """
        Сравнивает все варианты агента и выбирает победителя.

        Returns:
            ABTestResult с результатом сравнения или None если недостаточно данных.
        """
        variants = self.registry.load_variants(agent_name)
        if len(variants) < 2:
            return None

        # Фильтруем варианты с достаточным количеством запусков
        qualified = [v for v in variants if v.experiment_count >= AB_TEST_MIN_RUNS]
        if len(qualified) < 2:
            self.logger.info(
                "not_enough_data",
                agent=agent_name,
                qualified=len(qualified),
                min_required=AB_TEST_MIN_RUNS,
            )
            return None

        # Сортируем по avg_score
        qualified.sort(key=lambda v: v.avg_score, reverse=True)
        best = qualified[0]
        second = qualified[1]

        # Простая эвристика уверенности: разница в avg_score
        score_diff = best.avg_score - second.avg_score
        confidence = min(score_diff * 10, 1.0)  # масштабируем

        winner = best.variant_name if confidence >= AB_TEST_CONFIDENCE_THRESHOLD else None
        reason = (
            f"Best variant '{best.variant_name}' avg_score={best.avg_score:.3f} "
            f"vs '{second.variant_name}' avg_score={second.avg_score:.3f} "
            f"(diff={score_diff:.3f}, confidence={confidence:.3f})"
        )

        result = ABTestResult(
            agent_name=agent_name,
            variant_a=best.variant_name,
            variant_b=second.variant_name,
            winner=winner,
            confidence=confidence,
            reason=reason,
            stats_a={
                "avg_score": best.avg_score,
                "runs": best.experiment_count,
            },
            stats_b={
                "avg_score": second.avg_score,
                "runs": second.experiment_count,
            },
        )

        if winner:
            self._promote_winner(agent_name, winner)

        return result

    def _promote_winner(self, agent_name: str, winner_name: str) -> None:
        """Делает вариант активным (победителем)."""
        variants = self.registry.load_variants(agent_name)
        for v in variants:
            v.is_active = (v.variant_name == winner_name)
        self.registry.save_variants(agent_name, variants)
        self.logger.info("winner_promoted", agent=agent_name, winner=winner_name)

    def evaluate_all(self) -> List[ABTestResult]:
        """Оценивает всех агентов с вариантами."""
        all_variants = self.registry.list_all_variants()
        results = []
        for agent_name in all_variants:
            result = self.evaluate(agent_name)
            if result:
                results.append(result)
        return results


# ═══════════════════════════════════════════════════════════════════════════════
# Integration with AgentConfig
# ═══════════════════════════════════════════════════════════════════════════════

class ABTestEnabledConfig:
    """
    Обертка для AgentConfig с поддержкой A/B тестирования.

    Использование в orchestrator:
        config = AgentConfig("seo-agent", "./configs")
        ab_config = ABTestEnabledConfig(config)
        system_prompt = ab_config.get_system_prompt()  # может вернуть вариант
    """

    _registry: Optional[PromptVariantRegistry] = None

    @classmethod
    def get_registry(cls) -> PromptVariantRegistry:
        if cls._registry is None:
            cls._registry = PromptVariantRegistry()
        return cls._registry

    def __init__(self, agent_config) -> None:
        self.agent_config = agent_config
        self.registry = self.get_registry()
        self.selected_variant: Optional[str] = None

    def get_system_prompt(self) -> str:
        """
        Возвращает system_prompt — либо из конфига, либо вариант из A/B теста.

        Если у агента включён ab_test в конфиге — выбирает вариант из registry.
        Иначе — возвращает стандартный system_prompt.
        """
        config = self.agent_config._config
        if not config.get("ab_test", False):
            return self.agent_config.get_system_prompt()

        agent_name = self.agent_config.agent_name
        variant = self.registry.select_variant_for_run(agent_name)

        if variant:
            self.selected_variant = variant.variant_name
            logger.debug(
                "ab_variant_selected",
                agent=agent_name,
                variant=variant.variant_name,
                runs=variant.experiment_count,
            )
            return variant.system_prompt

        # Нет вариантов — fallback на стандартный
        return self.agent_config.get_system_prompt()

    def record_validation_score(self, score: float) -> None:
        """Записывает validation score для выбранного варианта."""
        if self.selected_variant:
            self.registry.record_run_result(
                self.agent_config.agent_name,
                self.selected_variant,
                score,
            )


# ═══════════════════════════════════════════════════════════════════════════════
# CLI / Utilities
# ═══════════════════════════════════════════════════════════════════════════════

def create_variant(agent_name: str, variant_name: str, system_prompt: str) -> PromptVariant:
    """CLI: создаёт новый вариант промпта."""
    registry = PromptVariantRegistry()
    return registry.add_variant(agent_name, variant_name, system_prompt)


def evaluate_agent(agent_name: str) -> Optional[ABTestResult]:
    """CLI: оценивает A/B тест для агента."""
    registry = PromptVariantRegistry()
    evaluator = ABTestEvaluator(registry)
    return evaluator.evaluate(agent_name)


def list_variants(agent_name: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """CLI: список всех вариантов."""
    registry = PromptVariantRegistry()
    if agent_name:
        variants = registry.load_variants(agent_name)
        return {agent_name: [v.to_dict() for v in variants]}
    all_v = registry.list_all_variants()
    return {k: [v.to_dict() for v in vs] for k, vs in all_v.items()}
