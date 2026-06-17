#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║              CRITIC AGENT (P3-10)                                    ║
║                    smart-skidka.ru                                   ║
╠══════════════════════════════════════════════════════════════════════╣
║  Вторичный агент для аудита логов первичных агентов.               ║
║                                                                      ║
║  Возможности:                                                        ║
║    - Проверка соответствия плану (plan adherence)                    ║
║    - Обнаружение галлюцинаций аргументов (argument hallucination)    ║
║    - Оценка качества эскалации (escalation quality)                  ║
║    - Агрегированный score + детальный отчёт                         ║
║                                                                      ║
║  Интеграция: CriticAgent.audit_cycle(cycle_results) → CriticReport  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger("critic_agent")


# ═══════════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════════

class CriticSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class CriticFinding:
    """Одна находка аудита."""
    check_name: str
    severity: CriticSeverity
    message: str
    agent_name: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "check_name": self.check_name,
            "severity": self.severity.value,
            "message": self.message,
            "agent_name": self.agent_name,
            "details": self.details,
        }


@dataclass
class CriticReport:
    """Итоговый отчёт аудита цикла."""
    cycle_id: str
    overall_score: float  # 0.0 – 1.0
    findings: List[CriticFinding]
    summary: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "overall_score": round(self.overall_score, 3),
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
            "timestamp": self.timestamp,
        }

    def findings_by_severity(self, severity: CriticSeverity) -> List[CriticFinding]:
        return [f for f in self.findings if f.severity == severity]

    def findings_for_agent(self, agent_name: str) -> List[CriticFinding]:
        return [f for f in self.findings if f.agent_name == agent_name]


# ═══════════════════════════════════════════════════════════════════════════════
# Plan Adherence Checker
# ═══════════════════════════════════════════════════════════════════════════════

class PlanAdherenceChecker:
    """
    Проверяет, что результат агента соответствует заявленному плану/задаче.

    Для каждого типа агента определены обязательные поля в выходе.
    Если поля отсутствуют или пусты — это отклонение от плана.
    """

    # Ожидаемые ключевые поля по типу агента
    EXPECTED_FIELDS: Dict[str, List[str]] = {
        "seo": ["title", "meta_description", "keywords", "h1"],
        "smm": ["content", "hashtags", "platform"],
        "content": ["title", "body", "headings"],
        "performance": ["headline", "description", "cta"],
        "email": ["subject", "body", "cta"],
        "analytics": ["metrics", "insights", "recommendations"],
        "trend": ["trends", "sources", "confidence"],
    }

    # Минимальная длина значимого поля (символов)
    MIN_FIELD_LENGTH: int = 3

    def check(self, agent_name: str, result: Dict[str, Any]) -> List[CriticFinding]:
        findings: List[CriticFinding] = []
        agent_type = self._extract_type(agent_name)
        data = result.get("data", result) if isinstance(result, dict) else {}
        if not isinstance(data, dict):
            data = {}

        expected = self.EXPECTED_FIELDS.get(agent_type, [])
        if not expected:
            return findings

        missing = []
        empty = []
        for field_name in expected:
            value = data.get(field_name)
            if value is None:
                missing.append(field_name)
            elif isinstance(value, str) and len(value.strip()) < self.MIN_FIELD_LENGTH:
                empty.append(field_name)
            elif isinstance(value, list) and len(value) == 0:
                empty.append(field_name)
            elif isinstance(value, dict) and len(value) == 0:
                empty.append(field_name)

        if missing:
            findings.append(
                CriticFinding(
                    check_name="plan_adherence",
                    severity=CriticSeverity.ERROR,
                    message=f"Отсутствуют обязательные поля: {', '.join(missing)}",
                    agent_name=agent_name,
                    details={"missing_fields": missing, "agent_type": agent_type},
                )
            )

        if empty:
            findings.append(
                CriticFinding(
                    check_name="plan_adherence",
                    severity=CriticSeverity.WARNING,
                    message=f"Пустые или слишком короткие поля: {', '.join(empty)}",
                    agent_name=agent_name,
                    details={"empty_fields": empty, "agent_type": agent_type},
                )
            )

        if not missing and not empty:
            findings.append(
                CriticFinding(
                    check_name="plan_adherence",
                    severity=CriticSeverity.INFO,
                    message="Все обязательные поля присутствуют и заполнены",
                    agent_name=agent_name,
                    details={"agent_type": agent_type},
                )
            )

        return findings

    def _extract_type(self, agent_name: str) -> str:
        return agent_name.split("-")[0] if "-" in agent_name else agent_name


# ═══════════════════════════════════════════════════════════════════════════════
# Argument Hallucination Detector
# ═══════════════════════════════════════════════════════════════════════════════

class HallucinationDetector:
    """
    Обнаруживает галлюцинации в аргументах/данных агента.

    Эвристики:
    1. Повторяющиеся паттерны — признак шаблонного ответа
    2. Нереалистичные числа (слишком большие/маленькие)
    3. Ссылки на несуществующие источники
    4. Противоречивые данные внутри результата
    """

    # Паттерны подозрительных ссылок
    SUSPICIOUS_PATTERNS: List[Tuple[str, str]] = [
        (r"https?://example\.", "placeholder_url"),
        (r"\[.*?\]\(.*?\)", "markdown_link_unverified"),
        (r"lorem ipsum", "lorem_ipsum"),
        (r"TODO|FIXME|XXX", "placeholder_marker"),
    ]

    # Максимально допустимое числовое значение (для маркетинговых метрик)
    MAX_REALISTIC_NUMBER: float = 1_000_000_000.0

    def check(self, agent_name: str, result: Dict[str, Any]) -> List[CriticFinding]:
        findings: List[CriticFinding] = []
        data = result.get("data", result) if isinstance(result, dict) else {}
        if not isinstance(data, dict):
            data = {}

        # 1. Проверка на placeholder-контент
        raw_text = json.dumps(data, ensure_ascii=False).lower()
        for pattern, pattern_name in self.SUSPICIOUS_PATTERNS:
            if re.search(pattern, raw_text, re.IGNORECASE):
                findings.append(
                    CriticFinding(
                        check_name="hallucination",
                        severity=CriticSeverity.WARNING,
                        message=f"Обнаружен placeholder-контент: {pattern_name}",
                        agent_name=agent_name,
                        details={"pattern": pattern_name},
                    )
                )

        # 2. Проверка числовых значений
        numeric_issues = self._check_numeric_values(data)
        if numeric_issues:
            findings.append(
                CriticFinding(
                    check_name="hallucination",
                    severity=CriticSeverity.WARNING,
                    message=f"Подозрительные числовые значения: {len(numeric_issues)} шт.",
                    agent_name=agent_name,
                    details={"issues": numeric_issues},
                )
            )

        # 3. Проверка на противоречия
        contradictions = self._check_contradictions(data)
        for contradiction in contradictions:
            findings.append(
                CriticFinding(
                    check_name="hallucination",
                    severity=CriticSeverity.ERROR,
                    message=f"Противоречие в данных: {contradiction}",
                    agent_name=agent_name,
                    details={"contradiction": contradiction},
                )
            )

        if not findings:
            findings.append(
                CriticFinding(
                    check_name="hallucination",
                    severity=CriticSeverity.INFO,
                    message="Галлюцинаций не обнаружено",
                    agent_name=agent_name,
                )
            )

        return findings

    def _check_numeric_values(self, data: Dict[str, Any]) -> List[Dict[str, Any]]:
        issues = []
        for key, value in self._flatten(data).items():
            if isinstance(value, (int, float)) and value > self.MAX_REALISTIC_NUMBER:
                issues.append({"field": key, "value": value})
        return issues

    def _check_contradictions(self, data: Dict[str, Any]) -> List[str]:
        contradictions = []
        # Пример: если есть keywords_count и список keywords — проверяем совпадение
        keywords = data.get("keywords", [])
        keywords_count = data.get("keywords_count")
        if isinstance(keywords, list) and keywords_count is not None:
            if len(keywords) != keywords_count:
                contradictions.append(
                    f"keywords_count ({keywords_count}) != len(keywords) ({len(keywords)})"
                )
        return contradictions

    def _flatten(self, obj: Any, prefix: str = "") -> Dict[str, Any]:
        items: Dict[str, Any] = {}
        if isinstance(obj, dict):
            for k, v in obj.items():
                new_key = f"{prefix}.{k}" if prefix else k
                if isinstance(v, (dict, list)):
                    items.update(self._flatten(v, new_key))
                else:
                    items[new_key] = v
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                new_key = f"{prefix}[{i}]"
                if isinstance(v, (dict, list)):
                    items.update(self._flatten(v, new_key))
                else:
                    items[new_key] = v
        else:
            items[prefix] = obj
        return items


# ═══════════════════════════════════════════════════════════════════════════════
# Escalation Quality Assessor
# ═══════════════════════════════════════════════════════════════════════════════

class EscalationQualityAssessor:
    """
    Оценивает качество эскалации — насколько хорошо агент обработал ошибки
    и запросил помощь/передал управление.

    Эвристики:
    1. При ошибке агент должен содержать error_context
    2. При критической ошибке — должен быть флаг escalation_needed
    3. Повторяющиеся ошибки без изменения стратегии — плохая эскалация
    """

    def check(
        self,
        agent_name: str,
        result: Dict[str, Any],
        previous_results: Optional[List[Dict[str, Any]]] = None,
    ) -> List[CriticFinding]:
        findings: List[CriticFinding] = []
        success = result.get("success", True)
        data = result.get("data", {}) if isinstance(result, dict) else {}
        if not isinstance(data, dict):
            data = {}

        if success:
            findings.append(
                CriticFinding(
                    check_name="escalation_quality",
                    severity=CriticSeverity.INFO,
                    message="Агент выполнен успешно, эскалация не требуется",
                    agent_name=agent_name,
                )
            )
            return findings

        # При ошибке проверяем наличие контекста
        error = result.get("error", "")
        retry_attempts = result.get("retry_attempts", 0)

        if not error:
            findings.append(
                CriticFinding(
                    check_name="escalation_quality",
                    severity=CriticSeverity.ERROR,
                    message="Ошибка без описания — невозможна диагностика",
                    agent_name=agent_name,
                    details={"retry_attempts": retry_attempts},
                )
            )
        else:
            if retry_attempts == 0:
                findings.append(
                    CriticFinding(
                        check_name="escalation_quality",
                        severity=CriticSeverity.WARNING,
                        message="Ошибка без попытки retry",
                        agent_name=agent_name,
                        details={"error": error[:200]},
                    )
                )
            elif retry_attempts >= 3:
                findings.append(
                    CriticFinding(
                        check_name="escalation_quality",
                        severity=CriticSeverity.ERROR,
                        message=f"Исчерпаны все попытки retry ({retry_attempts})",
                        agent_name=agent_name,
                        details={"error": error[:200], "retry_exhausted": True},
                    )
                )
            else:
                findings.append(
                    CriticFinding(
                        check_name="escalation_quality",
                        severity=CriticSeverity.INFO,
                        message=f"Retry сработал после {retry_attempts} попыток",
                        agent_name=agent_name,
                        details={"retry_attempts": retry_attempts},
                    )
                )

        # Проверка повторяющихся ошибок
        if previous_results:
            repeat_findings = self._check_repeated_errors(
                agent_name, error, previous_results
            )
            findings.extend(repeat_findings)

        return findings

    def _check_repeated_errors(
        self,
        agent_name: str,
        current_error: str,
        previous_results: List[Dict[str, Any]],
    ) -> List[CriticFinding]:
        findings = []
        if not current_error:
            return findings

        current_error_norm = current_error.lower().strip()[:100]
        similar_count = 0
        for prev in previous_results[-5:]:
            prev_error = prev.get("error", "")
            if prev_error:
                prev_norm = prev_error.lower().strip()[:100]
                # Простое сходство по подстроке
                if (current_error_norm in prev_norm) or (prev_norm in current_error_norm):
                    similar_count += 1

        if similar_count >= 2:
            findings.append(
                CriticFinding(
                    check_name="escalation_quality",
                    severity=CriticSeverity.ERROR,
                    message=f"Повторяющаяся ошибка {similar_count} раз — стратегия не меняется",
                    agent_name=agent_name,
                    details={"similar_occurrences": similar_count},
                )
            )

        return findings


# ═══════════════════════════════════════════════════════════════════════════════
# Critic Agent — thread-safe singleton
# ═══════════════════════════════════════════════════════════════════════════════

class CriticAgent:
    """
    Агент-критик для аудита результатов первичных агентов.

    P2-5: Thread-safe singleton через asyncio.Lock.
    """

    _instance: Optional[CriticAgent] = None
    _lock = asyncio.Lock()

    def __new__(cls) -> CriticAgent:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # P2-5: Инициализируем только один раз
        if not hasattr(self, "_initialized"):
            self.plan_checker = PlanAdherenceChecker()
            self.hallucination_detector = HallucinationDetector()
            self.escalation_assessor = EscalationQualityAssessor()
            self.logger = structlog.get_logger("critic_agent")
            self._initialized = True

    def audit_cycle(
        self,
        cycle_id: str,
        cycle_results: List[Dict[str, Any]],
        previous_cycles: Optional[List[List[Dict[str, Any]]]] = None,
    ) -> CriticReport:
        """
        Аудит одного цикла оркестратора.

        Args:
            cycle_id: ID цикла
            cycle_results: Результаты всех агентов в цикле
            previous_cycles: История предыдущих циклов для проверки повторов

        Returns:
            CriticReport с оценками и находками
        """
        self.logger.info("Начало аудита цикла", cycle_id=cycle_id)
        findings: List[CriticFinding] = []

        for result in cycle_results:
            agent_name = result.get("agent_name", "unknown")
            agent_findings = self.audit_agent(agent_name, result, previous_cycles)
            findings.extend(agent_findings)

        overall_score = self._calculate_overall_score(findings, cycle_results)
        summary = self._build_summary(findings, cycle_results)

        report = CriticReport(
            cycle_id=cycle_id,
            overall_score=overall_score,
            findings=findings,
            summary=summary,
        )

        self.logger.info(
            "Аудит завершён",
            cycle_id=cycle_id,
            score=overall_score,
            findings_count=len(findings),
        )
        return report

    def audit_agent(
        self,
        agent_name: str,
        result: Dict[str, Any],
        previous_cycles: Optional[List[List[Dict[str, Any]]]] = None,
    ) -> List[CriticFinding]:
        """Аудит одного агента."""
        findings: List[CriticFinding] = []

        # Plan adherence
        findings.extend(self.plan_checker.check(agent_name, result))

        # Hallucination detection
        findings.extend(self.hallucination_detector.check(agent_name, result))

        # Escalation quality
        prev_results = self._extract_agent_history(agent_name, previous_cycles)
        findings.extend(self.escalation_assessor.check(agent_name, result, prev_results))

        return findings

    def _calculate_overall_score(
        self, findings: List[CriticFinding], cycle_results: List[Dict[str, Any]]
    ) -> float:
        """
        Вычисляет общий score аудита.

        Логика:
        - Базовый score: 1.0
        - ERROR finding: -0.15
        - WARNING finding: -0.05
        - CRITICAL finding: -0.30
        - INFO finding: +0.02 (макс +0.10)
        """
        score = 1.0
        info_bonus = 0.0

        for finding in findings:
            if finding.severity == CriticSeverity.CRITICAL:
                score -= 0.30
            elif finding.severity == CriticSeverity.ERROR:
                score -= 0.15
            elif finding.severity == CriticSeverity.WARNING:
                score -= 0.05
            elif finding.severity == CriticSeverity.INFO:
                info_bonus = min(info_bonus + 0.02, 0.10)

        score += info_bonus
        return max(0.0, min(1.0, round(score, 3)))

    def _build_summary(
        self, findings: List[CriticFinding], cycle_results: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Строит сводку по аудиту."""
        severity_counts = {
            "critical": len(self._filter_by_severity(findings, CriticSeverity.CRITICAL)),
            "error": len(self._filter_by_severity(findings, CriticSeverity.ERROR)),
            "warning": len(self._filter_by_severity(findings, CriticSeverity.WARNING)),
            "info": len(self._filter_by_severity(findings, CriticSeverity.INFO)),
        }

        agent_names = {r.get("agent_name", "unknown") for r in cycle_results}
        agent_scores = {}
        for agent_name in agent_names:
            agent_findings = [f for f in findings if f.agent_name == agent_name]
            agent_scores[agent_name] = self._calculate_agent_score(agent_findings)

        return {
            "agents_audited": len(cycle_results),
            "severity_counts": severity_counts,
            "agent_scores": agent_scores,
            "checks_performed": ["plan_adherence", "hallucination", "escalation_quality"],
        }

    def _calculate_agent_score(self, findings: List[CriticFinding]) -> float:
        score = 1.0
        info_bonus = 0.0
        for finding in findings:
            if finding.severity == CriticSeverity.CRITICAL:
                score -= 0.30
            elif finding.severity == CriticSeverity.ERROR:
                score -= 0.15
            elif finding.severity == CriticSeverity.WARNING:
                score -= 0.05
            elif finding.severity == CriticSeverity.INFO:
                info_bonus = min(info_bonus + 0.02, 0.10)
        score += info_bonus
        return max(0.0, min(1.0, round(score, 3)))

    def _filter_by_severity(
        self, findings: List[CriticFinding], severity: CriticSeverity
    ) -> List[CriticFinding]:
        return [f for f in findings if f.severity == severity]

    def _extract_agent_history(
        self,
        agent_name: str,
        previous_cycles: Optional[List[List[Dict[str, Any]]]],
    ) -> List[Dict[str, Any]]:
        if not previous_cycles:
            return []
        history = []
        for cycle in previous_cycles:
            for result in cycle:
                if result.get("agent_name") == agent_name:
                    history.append(result)
        return history


# ═══════════════════════════════════════════════════════════════════════════════
# Convenience functions
# ═══════════════════════════════════════════════════════════════════════════════

_critic_singleton: Optional[CriticAgent] = None


async def get_critic_async() -> CriticAgent:
    """Возвращает thread-safe singleton CriticAgent."""
    async with CriticAgent._lock:
        if CriticAgent._instance is None:
            CriticAgent._instance = CriticAgent()
        return CriticAgent._instance


def get_critic() -> CriticAgent:
    """Возвращает синглтон CriticAgent (sync wrapper)."""
    if CriticAgent._instance is None:
        CriticAgent._instance = CriticAgent()
    return CriticAgent._instance


def reset_critic() -> None:
    """Сбрасывает синглтон (для тестов)."""
    CriticAgent._instance = None


def audit_cycle(
    cycle_id: str,
    cycle_results: List[Dict[str, Any]],
    previous_cycles: Optional[List[List[Dict[str, Any]]]] = None,
) -> CriticReport:
    """Удобная функция для аудита цикла."""
    return get_critic().audit_cycle(cycle_id, cycle_results, previous_cycles)
