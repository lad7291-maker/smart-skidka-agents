#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║              SUBGOAL-BASED EVALUATION (P3-8)                         ║
║                    smart-skidka.ru                                   ║
╠══════════════════════════════════════════════════════════════════════╣
║  Система оценки выполнения подцелей агентов.                         ║
║                                                                      ║
║  Каждый тип агента имеет набор subgoals — атомарных целей,           ║
║  которые проверяются индивидуально. Результат:                       ║
║    - per-subgoal score (0.0–1.0)                                     ║
║    - weighted overall score                                          ║
║    - detailed breakdown для диагностики                              ║
║                                                                      ║
║  Пример SEO: title ✓, meta ✓, h1 ✗, schema ✓ → score 0.75          ║
║                                                                      ║
║  Интеграция: SubgoalEvaluator принимает результат агента и           ║
║  возвращает SubgoalEvaluation, который можно слить с ValidationResult║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger("subgoal_evaluator")


# ═══════════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════════

class SubgoalStatus(str, Enum):
    PASSED = "passed"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class SubgoalResult:
    """Результат оценки одной подцели."""
    name: str
    status: SubgoalStatus
    score: float  # 0.0 – 1.0
    weight: float  # вес в общей оценке
    message: str = ""
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.score = max(0.0, min(1.0, self.score))
        self.weight = max(0.0, min(1.0, self.weight))


@dataclass
class SubgoalEvaluation:
    """Полный результат subgoal-based evaluation."""
    agent_type: str
    overall_score: float  # 0.0 – 1.0
    subgoals: List[SubgoalResult]
    summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed_count(self) -> int:
        return sum(1 for s in self.subgoals if s.status == SubgoalStatus.PASSED)

    @property
    def failed_count(self) -> int:
        return sum(1 for s in self.subgoals if s.status == SubgoalStatus.FAILED)

    @property
    def partial_count(self) -> int:
        return sum(1 for s in self.subgoals if s.status == SubgoalStatus.PARTIAL)

    @property
    def total_weight(self) -> float:
        return sum(s.weight for s in self.subgoals)

    @property
    def weighted_score(self) -> float:
        tw = self.total_weight
        if tw == 0:
            return 0.0
        return sum(s.score * s.weight for s in self.subgoals) / tw

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_type": self.agent_type,
            "overall_score": round(self.overall_score, 3),
            "weighted_score": round(self.weighted_score, 3),
            "passed": self.passed_count,
            "partial": self.partial_count,
            "failed": self.failed_count,
            "total": len(self.subgoals),
            "summary": self.summary,
            "subgoals": [
                {
                    "name": s.name,
                    "status": s.status.value,
                    "score": round(s.score, 3),
                    "weight": s.weight,
                    "message": s.message,
                    "details": s.details,
                }
                for s in self.subgoals
            ],
            "metadata": self.metadata,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# Subgoal checkers — reusable atomic evaluators
# ═══════════════════════════════════════════════════════════════════════════════

class Checkers:
    """Набор переиспользуемых чекеров для subgoals."""

    @staticmethod
    def field_exists(data: Dict[str, Any], field: str) -> Tuple[bool, str]:
        """Проверяет наличие поля."""
        if field in data and data[field]:
            return True, f"Поле '{field}' присутствует"
        return False, f"Поле '{field}' отсутствует или пустое"

    @staticmethod
    def string_length(
        data: Dict[str, Any], field: str, min_len: int, max_len: int
    ) -> Tuple[float, str]:
        """Оценивает длину строки: 1.0 в диапазоне, 0.5 рядом, 0.0 далеко."""
        val = data.get(field, "")
        if not isinstance(val, str):
            return 0.0, f"Поле '{field}' не является строкой"
        length = len(val)
        if min_len <= length <= max_len:
            return 1.0, f"Длина {length} в допустимом диапазоне [{min_len}-{max_len}]"
        # Линейная интерполяция штрафа
        if length < min_len:
            ratio = length / min_len if min_len > 0 else 0
            score = max(0.0, ratio * 0.5)
            return score, f"Длина {length} < мин {min_len}"
        else:  # length > max_len
            over = length - max_len
            score = max(0.0, 1.0 - over / max_len * 0.5)
            return score, f"Длина {length} > макс {max_len}"

    @staticmethod
    def contains_any(
        data: Dict[str, Any], field: str, keywords: List[str], case_sensitive: bool = False
    ) -> Tuple[bool, str]:
        """Проверяет наличие хотя бы одного ключевого слова."""
        val = data.get(field, "")
        if not isinstance(val, str):
            return False, f"Поле '{field}' не строка"
        text = val if case_sensitive else val.lower()
        found = [k for k in keywords if (k if case_sensitive else k.lower()) in text]
        if found:
            return True, f"Найдены: {found}"
        return False, f"Не найдено ни одно из: {keywords}"

    @staticmethod
    def list_size(
        data: Dict[str, Any], field: str, min_size: int, max_size: int
    ) -> Tuple[float, str]:
        """Оценивает размер списка."""
        val = data.get(field, [])
        if not isinstance(val, list):
            return 0.0, f"Поле '{field}' не список"
        size = len(val)
        if min_size <= size <= max_size:
            return 1.0, f"Размер {size} в диапазоне [{min_size}-{max_size}]"
        if size < min_size:
            ratio = size / min_size if min_size > 0 else 0
            return max(0.0, ratio * 0.5), f"Размер {size} < мин {min_size}"
        over = size - max_size
        return max(0.0, 1.0 - over / max_size * 0.3), f"Размер {size} > макс {max_size}"

    @staticmethod
    def no_duplicates(data: Dict[str, Any], field: str) -> Tuple[bool, str]:
        """Проверяет отсутствие дубликатов в списке."""
        val = data.get(field, [])
        if not isinstance(val, list):
            return False, f"Поле '{field}' не список"
        lower = [str(v).lower().strip() for v in val]
        seen = set()
        dups = []
        for item in lower:
            if item in seen:
                dups.append(item)
            seen.add(item)
        if dups:
            return False, f"Дубликаты: {set(dups)}"
        return True, "Дубликатов нет"

    @staticmethod
    def fields_differ(
        data: Dict[str, Any], field1: str, field2: str, threshold: float = 0.8
    ) -> Tuple[float, str]:
        """Проверяет что два поля достаточно отличаются."""
        v1 = str(data.get(field1, "")).lower().strip()
        v2 = str(data.get(field2, "")).lower().strip()
        if not v1 or not v2:
            return 0.0, "Одно из полей пустое"
        # Simple Jaccard-like similarity on words
        words1 = set(v1.split())
        words2 = set(v2.split())
        if not words1 or not words2:
            return 1.0, "Поля разные"
        intersection = words1 & words2
        union = words1 | words2
        similarity = len(intersection) / len(union) if union else 0
        if similarity <= threshold:
            return 1.0, f"Поля достаточно разные (sim={similarity:.2f})"
        return max(0.0, 1.0 - (similarity - threshold) / (1 - threshold)), \
               f"Поля слишком похожи (sim={similarity:.2f})"

    @staticmethod
    def has_structure(data: Dict[str, Any], field: str, required_keys: List[str]) -> Tuple[float, str]:
        """Проверяет наличие обязательных ключей в dict-поле."""
        val = data.get(field, {})
        if not isinstance(val, dict):
            return 0.0, f"Поле '{field}' не словарь"
        missing = [k for k in required_keys if k not in val]
        if not missing:
            return 1.0, f"Все ключи присутствуют: {required_keys}"
        ratio = (len(required_keys) - len(missing)) / len(required_keys)
        return ratio, f"Отсутствуют ключи: {missing}"

    @staticmethod
    def word_count_range(
        data: Dict[str, Any], field: str, min_words: int, max_words: int
    ) -> Tuple[float, str]:
        """Оценивает количество слов."""
        val = data.get(field, "")
        if not isinstance(val, str):
            return 0.0, f"Поле '{field}' не строка"
        words = len(val.split())
        if min_words <= words <= max_words:
            return 1.0, f"{words} слов в диапазоне [{min_words}-{max_words}]"
        if words < min_words:
            ratio = words / min_words if min_words > 0 else 0
            return max(0.0, ratio * 0.5), f"{words} слов < мин {min_words}"
        over = words - max_words
        return max(0.0, 1.0 - over / max_words * 0.3), f"{words} слов > макс {max_words}"


# ═══════════════════════════════════════════════════════════════════════════════
# Subgoal definitions per agent type
# ═══════════════════════════════════════════════════════════════════════════════

# SEO subgoals
SEO_SUBGOALS: List[Dict[str, Any]] = [
    {
        "name": "title_exists",
        "weight": 0.15,
        "check": lambda d: Checkers.field_exists(d, "title"),
        "binary": True,
    },
    {
        "name": "title_length",
        "weight": 0.10,
        "check": lambda d: Checkers.string_length(d, "title", 30, 60),
        "binary": False,
    },
    {
        "name": "title_brand",
        "weight": 0.05,
        "check": lambda d: Checkers.contains_any(d, "title", ["smart-skidka", "смарт-скидка", "smart skidka"]),
        "binary": True,
    },
    {
        "name": "meta_exists",
        "weight": 0.15,
        "check": lambda d: Checkers.field_exists(d, "meta_description"),
        "binary": True,
    },
    {
        "name": "meta_length",
        "weight": 0.10,
        "check": lambda d: Checkers.string_length(d, "meta_description", 120, 160),
        "binary": False,
    },
    {
        "name": "meta_cta",
        "weight": 0.05,
        "check": lambda d: Checkers.contains_any(d, "meta_description", ["узнать", "смотреть", "перейти", "выбрать", "найти", "сравнить"]),
        "binary": True,
    },
    {
        "name": "h1_exists",
        "weight": 0.10,
        "check": lambda d: Checkers.field_exists(d, "h1"),
        "binary": True,
    },
    {
        "name": "h1_length",
        "weight": 0.05,
        "check": lambda d: Checkers.string_length(d, "h1", 10, 70),
        "binary": False,
    },
    {
        "name": "h1_unique",
        "weight": 0.05,
        "check": lambda d: Checkers.fields_differ(d, "h1", "title", 0.8),
        "binary": False,
    },
    {
        "name": "keywords_valid",
        "weight": 0.10,
        "check": lambda d: Checkers.list_size(d, "keywords", 3, 15),
        "binary": False,
    },
    {
        "name": "keywords_unique",
        "weight": 0.05,
        "check": lambda d: Checkers.no_duplicates(d, "keywords"),
        "binary": True,
    },
    {
        "name": "og_tags",
        "weight": 0.05,
        "check": lambda d: Checkers.has_structure(d, "og_tags", ["og:title", "og:description", "og:image"]),
        "binary": False,
    },
    {
        "name": "structured_data",
        "weight": 0.05,
        "check": lambda d: Checkers.has_structure(d, "structured_data", ["@type"]),
        "binary": False,
    },
]

# SMM subgoals
SMM_SUBGOALS: List[Dict[str, Any]] = [
    {"name": "text_exists", "weight": 0.20, "check": lambda d: Checkers.field_exists(d, "text"), "binary": True},
    {"name": "text_length", "weight": 0.15, "check": lambda d: Checkers.string_length(d, "text", 50, 2200), "binary": False},
    {"name": "has_cta", "weight": 0.10, "check": lambda d: Checkers.contains_any(d, "text", ["перейти", "купить", "узнать", "подробнее"]), "binary": True},
    {"name": "has_hashtags", "weight": 0.10, "check": lambda d: ("#" in d.get("text", ""), "Hashtags found" if "#" in d.get("text", "") else "No hashtags"), "binary": True},
    {"name": "has_link", "weight": 0.15, "check": lambda d: Checkers.contains_any(d, "text", ["http://", "https://", "smart-skidka.ru"]), "binary": True},
    {"name": "image_attached", "weight": 0.15, "check": lambda d: Checkers.field_exists(d, "image_url"), "binary": True},
    {"name": "platform_optimal", "weight": 0.15, "check": lambda d: _check_platform_optimal(d), "binary": False},
]


def _check_platform_optimal(data: Dict[str, Any]) -> Tuple[float, str]:
    """Проверяет оптимальность под платформу."""
    platform = data.get("platform", "generic")
    text = data.get("text", "")
    if platform == "twitter" and len(text) > 280:
        return 0.0, f"Twitter: {len(text)} > 280 chars"
    if platform == "twitter":
        return 1.0, "Twitter: within limit"
    if platform == "instagram" and len(text) > 2200:
        return 0.5, f"Instagram: {len(text)} > 2200 chars"
    return 1.0, f"Platform '{platform}': OK"


# Content subgoals
CONTENT_SUBGOALS: List[Dict[str, Any]] = [
    {"name": "title_exists", "weight": 0.10, "check": lambda d: Checkers.field_exists(d, "title"), "binary": True},
    {"name": "content_exists", "weight": 0.20, "check": lambda d: Checkers.field_exists(d, "content"), "binary": True},
    {"name": "content_length", "weight": 0.15, "check": lambda d: _check_content_length(d), "binary": False},
    {"name": "has_headings", "weight": 0.10, "check": lambda d: ("<h" in d.get("content", ""), "Has headings" if "<h" in d.get("content", "") else "No headings"), "binary": True},
    {"name": "has_internal_links", "weight": 0.10, "check": lambda d: Checkers.list_size(d, "internal_links", 1, 20), "binary": False},
    {"name": "has_image", "weight": 0.10, "check": lambda d: Checkers.field_exists(d, "featured_image"), "binary": True},
    {"name": "has_keywords", "weight": 0.10, "check": lambda d: Checkers.list_size(d, "keywords", 1, 10), "binary": False},
    {"name": "content_type_valid", "weight": 0.10, "check": lambda d: (d.get("content_type") in ["article", "guide", "review", "news", "comparison", "product_description"], f"Type: {d.get('content_type', 'missing')}"), "binary": True},
    {"name": "readability", "weight": 0.05, "check": lambda d: _check_readability(d), "binary": False},
]


def _check_content_length(data: Dict[str, Any]) -> Tuple[float, str]:
    ctype = data.get("content_type", "article")
    min_lens = {"article": 800, "guide": 1500, "review": 500, "news": 300, "comparison": 600, "product_description": 200}
    min_len = min_lens.get(ctype, 500)
    return Checkers.word_count_range(data, "content", min_len, min_len * 5)


def _check_readability(data: Dict[str, Any]) -> Tuple[float, str]:
    """Упрощённая проверка читаемости."""
    content = data.get("content", "")
    if not content:
        return 0.0, "No content"
    # Strip HTML
    text = re.sub(r'<[^>]+>', '', content)
    words = text.split()
    if not words:
        return 0.0, "No text"
    sentences = re.split(r'[.!?]+', text)
    sentences = [s for s in sentences if s.strip()]
    if not sentences:
        return 0.5, "No sentences"
    avg_words = len(words) / len(sentences)
    # Optimal: 10-15 words per sentence
    if 10 <= avg_words <= 15:
        return 1.0, f"Avg {avg_words:.1f} words/sentence"
    if avg_words < 10:
        return 0.8, f"Short sentences ({avg_words:.1f})"
    if avg_words <= 20:
        return 0.6, f"Long sentences ({avg_words:.1f})"
    return 0.3, f"Very long sentences ({avg_words:.1f})"


# Performance subgoals
PERFORMANCE_SUBGOALS: List[Dict[str, Any]] = [
    {"name": "headline_exists", "weight": 0.20, "check": lambda d: Checkers.field_exists(d, "headline"), "binary": True},
    {"name": "headline_length", "weight": 0.15, "check": lambda d: Checkers.string_length(d, "headline", 20, 60), "binary": False},
    {"name": "description_exists", "weight": 0.15, "check": lambda d: Checkers.field_exists(d, "description"), "binary": True},
    {"name": "cta_strong", "weight": 0.15, "check": lambda d: Checkers.contains_any(d, "headline", ["скидка", "дешевле", "экономия", "бесплатно", "подарок"]), "binary": True},
    {"name": "targeting_defined", "weight": 0.15, "check": lambda d: Checkers.field_exists(d, "target_audience"), "binary": True},
    {"name": "budget_specified", "weight": 0.10, "check": lambda d: Checkers.field_exists(d, "budget"), "binary": True},
    {"name": "duration_valid", "weight": 0.10, "check": lambda d: _check_duration(d), "binary": False},
]


def _check_duration(data: Dict[str, Any]) -> Tuple[float, str]:
    duration = data.get("duration_days", 0)
    if isinstance(duration, str):
        try:
            duration = int(duration)
        except ValueError:
            return 0.0, f"Invalid duration: {duration}"
    if 1 <= duration <= 30:
        return 1.0, f"Duration {duration} days"
    if duration > 0:
        return 0.5, f"Duration {duration} days (unusual)"
    return 0.0, "No duration specified"


# Email subgoals
EMAIL_SUBGOALS: List[Dict[str, Any]] = [
    {"name": "subject_exists", "weight": 0.20, "check": lambda d: Checkers.field_exists(d, "subject"), "binary": True},
    {"name": "subject_length", "weight": 0.15, "check": lambda d: Checkers.string_length(d, "subject", 20, 60), "binary": False},
    {"name": "body_exists", "weight": 0.20, "check": lambda d: Checkers.field_exists(d, "body"), "binary": True},
    {"name": "body_length", "weight": 0.15, "check": lambda d: Checkers.word_count_range(d, "body", 100, 2000), "binary": False},
    {"name": "has_unsubscribe", "weight": 0.15, "check": lambda d: Checkers.contains_any(d, "body", ["отписаться", "unsubscribe", "отменить подписку"]), "binary": True},
    {"name": "low_spam_score", "weight": 0.15, "check": lambda d: _check_spam_score(d), "binary": False},
]


def _check_spam_score(data: Dict[str, Any]) -> Tuple[float, str]:
    """Оценивает спам-скор на основе ключевых слов."""
    body = data.get("body", "")
    subject = data.get("subject", "")
    text = (subject + " " + body).upper()
    high_risk = ["БЕСПЛАТНО", "КУПИ СЕЙЧАС", "ОГРАНИЧЕННОЕ ВРЕМЯ", "СРОЧНО", "ПОСЛЕДНИЙ ШАНС", "100%", "$$$"]
    medium_risk = ["СКИДКА", "БЕСПЛАТНО", "АКЦИЯ", "РАСПРОДАЖА", "ПОДАРОК", "БОНУС"]
    score = 0
    for kw in high_risk:
        if kw in text:
            score += 2
    for kw in medium_risk:
        if kw in text:
            score += 1
    if score <= 2:
        return 1.0, f"Spam score: {score}/15 (low)"
    if score <= 5:
        return 0.6, f"Spam score: {score}/15 (medium)"
    if score <= 8:
        return 0.3, f"Spam score: {score}/15 (high)"
    return 0.0, f"Spam score: {score}/15 (critical)"


# Analytics subgoals
ANALYTICS_SUBGOALS: List[Dict[str, Any]] = [
    {"name": "metrics_present", "weight": 0.25, "check": lambda d: Checkers.list_size(d, "metrics", 3, 20), "binary": False},
    {"name": "has_trend", "weight": 0.20, "check": lambda d: Checkers.field_exists(d, "trend_direction"), "binary": True},
    {"name": "has_recommendation", "weight": 0.20, "check": lambda d: Checkers.field_exists(d, "recommendations"), "binary": True},
    {"name": "data_fresh", "weight": 0.15, "check": lambda d: _check_data_freshness(d), "binary": False},
    {"name": "visualization", "weight": 0.10, "check": lambda d: Checkers.field_exists(d, "charts"), "binary": True},
    {"name": "comparison_period", "weight": 0.10, "check": lambda d: Checkers.field_exists(d, "comparison_period"), "binary": True},
]


def _check_data_freshness(data: Dict[str, Any]) -> Tuple[float, str]:
    """Проверяет свежесть данных."""
    date_str = data.get("data_date", "")
    if not date_str:
        return 0.0, "No data date"
    try:
        from datetime import datetime, timedelta
        data_date = datetime.fromisoformat(str(date_str).replace("Z", "+00:00"))
        age = (datetime.now(data_date.tzinfo) - data_date).days
        if age <= 1:
            return 1.0, f"Data is {age} days old"
        if age <= 7:
            return 0.7, f"Data is {age} days old"
        if age <= 30:
            return 0.4, f"Data is {age} days old"
        return 0.0, f"Data is {age} days old (stale)"
    except Exception:
        return 0.5, f"Cannot parse date: {date_str}"


# Trend subgoals
TREND_SUBGOALS: List[Dict[str, Any]] = [
    {"name": "trend_identified", "weight": 0.30, "check": lambda d: Checkers.field_exists(d, "trend_name"), "binary": True},
    {"name": "confidence_score", "weight": 0.20, "check": lambda d: _check_confidence(d), "binary": False},
    {"name": "sources_cited", "weight": 0.20, "check": lambda d: Checkers.list_size(d, "sources", 1, 10), "binary": False},
    {"name": "actionable", "weight": 0.15, "check": lambda d: Checkers.field_exists(d, "recommended_actions"), "binary": True},
    {"name": "category_defined", "weight": 0.15, "check": lambda d: Checkers.field_exists(d, "category"), "binary": True},
]


def _check_confidence(data: Dict[str, Any]) -> Tuple[float, str]:
    confidence = data.get("confidence", 0)
    if isinstance(confidence, str):
        try:
            confidence = float(confidence)
        except ValueError:
            return 0.0, f"Invalid confidence: {confidence}"
    if confidence >= 0.8:
        return 1.0, f"Confidence: {confidence}"
    if confidence >= 0.5:
        return 0.6, f"Confidence: {confidence} (moderate)"
    if confidence > 0:
        return 0.3, f"Confidence: {confidence} (low)"
    return 0.0, "No confidence specified"


# Registry of all subgoal definitions
SUBGOAL_REGISTRY: Dict[str, List[Dict[str, Any]]] = {
    "seo": SEO_SUBGOALS,
    "smm": SMM_SUBGOALS,
    "content": CONTENT_SUBGOALS,
    "performance": PERFORMANCE_SUBGOALS,
    "email": EMAIL_SUBGOALS,
    "analytics": ANALYTICS_SUBGOALS,
    "trend": TREND_SUBGOALS,
}


# ═══════════════════════════════════════════════════════════════════════════════
# SubgoalEvaluator
# ═══════════════════════════════════════════════════════════════════════════════

class SubgoalEvaluator:
    """Оценивает результат агента по подцелям."""

    def __init__(self, registry: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        self.registry = registry or SUBGOAL_REGISTRY

    def evaluate(self, agent_type: str, result: Dict[str, Any]) -> SubgoalEvaluation:
        """
        Оценивает результат агента по подцелям.

        Args:
            agent_type: Тип агента (seo, smm, content, ...)
            result: Результат работы агента

        Returns:
            SubgoalEvaluation с детальным разбором
        """
        agent_type = agent_type.lower()
        definitions = self.registry.get(agent_type, [])

        if not definitions:
            logger.warning("No subgoals defined for agent type", agent_type=agent_type)
            return SubgoalEvaluation(
                agent_type=agent_type,
                overall_score=0.0,
                subgoals=[],
                summary=f"No subgoals defined for '{agent_type}'",
            )

        subgoals: List[SubgoalResult] = []
        for defn in definitions:
            name = defn["name"]
            weight = defn.get("weight", 1.0)
            binary = defn.get("binary", False)
            check_fn = defn["check"]

            try:
                raw_result = check_fn(result)
            except Exception as e:
                logger.error("Subgoal check failed", subgoal=name, error=str(e))
                raw_result = (0.0, f"Check error: {e}")

            # Normalize result to (score, message)
            if isinstance(raw_result, tuple):
                if len(raw_result) == 2:
                    if isinstance(raw_result[0], bool):
                        score = 1.0 if raw_result[0] else 0.0
                        message = raw_result[1]
                    else:
                        score = float(raw_result[0])
                        message = raw_result[1]
                else:
                    score = 0.0
                    message = str(raw_result)
            else:
                score = 1.0 if raw_result else 0.0
                message = "OK" if raw_result else "Failed"

            # Determine status
            if binary:
                status = SubgoalStatus.PASSED if score >= 1.0 else SubgoalStatus.FAILED
            else:
                if score >= 0.9:
                    status = SubgoalStatus.PASSED
                elif score >= 0.5:
                    status = SubgoalStatus.PARTIAL
                else:
                    status = SubgoalStatus.FAILED

            subgoals.append(SubgoalResult(
                name=name,
                status=status,
                score=score,
                weight=weight,
                message=message,
            ))

        # Calculate overall score
        total_weight = sum(s.weight for s in subgoals)
        if total_weight > 0:
            overall_score = sum(s.score * s.weight for s in subgoals) / total_weight
        else:
            overall_score = 0.0

        # Generate summary
        passed = sum(1 for s in subgoals if s.status == SubgoalStatus.PASSED)
        partial = sum(1 for s in subgoals if s.status == SubgoalStatus.PARTIAL)
        failed = sum(1 for s in subgoals if s.status == SubgoalStatus.FAILED)
        total = len(subgoals)

        summary = (
            f"{agent_type.upper()}: {passed}/{total} passed, "
            f"{partial} partial, {failed} failed "
            f"(score: {overall_score:.2f})"
        )

        logger.info(
            "Subgoal evaluation complete",
            agent_type=agent_type,
            score=round(overall_score, 3),
            passed=passed,
            failed=failed,
        )

        return SubgoalEvaluation(
            agent_type=agent_type,
            overall_score=overall_score,
            subgoals=subgoals,
            summary=summary,
        )

    def add_subgoal(self, agent_type: str, definition: Dict[str, Any]) -> None:
        """Добавляет subgoal для типа агента в runtime."""
        agent_type = agent_type.lower()
        if agent_type not in self.registry:
            self.registry[agent_type] = []
        self.registry[agent_type].append(definition)

    def get_subgoal_names(self, agent_type: str) -> List[str]:
        """Возвращает список имён subgoals для типа агента."""
        return [d["name"] for d in self.registry.get(agent_type.lower(), [])]

    def merge_with_validation(
        self, subgoal_eval: SubgoalEvaluation, validation_result: Any
    ) -> Dict[str, Any]:
        """
        Сливает SubgoalEvaluation с ValidationResult в единый отчёт.

        Returns:
            Словарь с полями из обоих результатов
        """
        merged = subgoal_eval.to_dict()
        # Try to extract ValidationResult fields
        if hasattr(validation_result, "to_dict"):
            merged["validation"] = validation_result.to_dict()
        elif isinstance(validation_result, dict):
            merged["validation"] = validation_result
        else:
            merged["validation"] = {"status": str(validation_result)}

        # Combined score: average of subgoal and validation scores
        v_score = merged["validation"].get("score", 0.0)
        merged["combined_score"] = round((merged["weighted_score"] + v_score) / 2, 3)

        return merged


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton evaluator
# ═══════════════════════════════════════════════════════════════════════════════

_default_evaluator: Optional[SubgoalEvaluator] = None


def get_evaluator() -> SubgoalEvaluator:
    """Возвращает singleton SubgoalEvaluator."""
    global _default_evaluator
    if _default_evaluator is None:
        _default_evaluator = SubgoalEvaluator()
    return _default_evaluator


def evaluate_subgoals(agent_type: str, result: Dict[str, Any]) -> SubgoalEvaluation:
    """Удобная функция для оценки подцелей."""
    return get_evaluator().evaluate(agent_type, result)
