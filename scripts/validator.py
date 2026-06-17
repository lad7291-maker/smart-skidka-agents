#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                         VALIDATOR MODULE                             ║
║                         smart-skidka.ru                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  Модуль детальной валидации результатов работы агентов.             ║
║  Каждый тип агента имеет специфические проверки качества,          ║
║  соответствия требованиям и бизнес-логике.                          ║
╚══════════════════════════════════════════════════════════════════════╝

Валидаторы:
    - validate_seo_result       : Проверка SEO-мета-тегов, структуры
    - validate_smm_result       : Проверка постов для соцсетей
    - validate_performance_result : Проверка рекламных объявлений
    - validate_email_result     : Проверка email-рассылок (спам-скор)
    - validate_analytics_result : Проверка аналитических отчётов
    - validate_content_result   : Проверка сгенерированного контента

Утилиты:
    - calculate_spam_score      : Расчёт спам-скора email
    - check_uniqueness          : Проверка уникальности текста

Example:
    >>> from validator import validate_seo_result, calculate_spam_score
    >>> result = validate_seo_result({"title": "...", "meta_description": "..."})
    >>> if result.is_valid:
    ...     print("SEO валидно")
    >>> spam = calculate_spam_score(email_body)
    >>> if spam > 5:
    ...     print("Высокий риск спама!")
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

import structlog
from dotenv import load_dotenv

# ═══════════════════════════════════════════════════════════════════════════════
# Загрузка переменных окружения
# ═══════════════════════════════════════════════════════════════════════════════
import os
_env_loaded = load_dotenv()
if not _env_loaded and not os.getenv("LLM_API_KEY"):
    import warnings
    warnings.warn(
        ".env файл не найден и переменные окружения не заданы. "
        "Система может работать некорректно.",
        RuntimeWarning,
        stacklevel=2,
    )

# ═══════════════════════════════════════════════════════════════════════════════
# Настройка логирования
# ═══════════════════════════════════════════════════════════════════════════════
logger = structlog.get_logger("validator")


# ═══════════════════════════════════════════════════════════════════════════════
# Перечисления и константы
# ═══════════════════════════════════════════════════════════════════════════════
class ValidationStatus(str, Enum):
    """Статусы валидации результата."""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


# SEO-константы
SEO_TITLE_MIN_LENGTH: int = 30
SEO_TITLE_MAX_LENGTH: int = 60
SEO_META_MIN_LENGTH: int = 120
SEO_META_MAX_LENGTH: int = 160
SEO_H1_MIN_LENGTH: int = 10
SEO_H1_MAX_LENGTH: int = 70
SEO_KEYWORDS_MIN_COUNT: int = 3
SEO_KEYWORDS_MAX_COUNT: int = 15

# SMM-константы
SMM_TWITTER_MAX_LENGTH: int = 280
SMM_INSTAGRAM_MAX_LENGTH: int = 2200
SMM_HASHTAGS_MAX_COUNT: int = 30
SMM_HASHTAGS_OPTIMAL_COUNT: int = 10

# Email-константы
EMAIL_SUBJECT_OPTIMAL_MIN: int = 20
EMAIL_SUBJECT_OPTIMAL_MAX: int = 60
EMAIL_BODY_MIN_LENGTH: int = 100
EMAIL_SPAM_KEYWORDS_HIGH: List[str] = [
    "БЕСПЛАТНО", "КУПИ СЕЙЧАС", "ОГРАНИЧЕННОЕ ВРЕМЯ",
    "ПРЯМО СЕЙЧАС", "ТОЛЬКО СЕГОДНЯ", "СУПЕР ПРЕДЛОЖЕНИЕ",
    "100% БЕСПЛАТНО", "ЗАРАБОТАЙ", "$$$", "!!!",
    "НЕ УДАЛЯЙТЕ", "СРОЧНО", "ПОСЛЕДНИЙ ШАНС",
    "БЕЗ ОБЯЗАТЕЛЬСТВ", "КОНФИДЕНЦИАЛЬНО", "ВЫ ВЫИГРАЛИ",
    "ЛОТЕРЕЯ", "МИЛЛИОН", "ГАРАНТИРОВАНО", "НИЧЕГО НЕ ПОКУПАЙ",
]
EMAIL_SPAM_KEYWORDS_MEDIUM: List[str] = [
    "скидка", "бесплатно", "акция", "распродажа",
    "выгода", "экономия", "подарок", "бонус",
    "дешево", "лучшая цена", "только сейчас",
]

# Content-константы
CONTENT_MIN_LENGTH: Dict[str, int] = {
    "article": 800,
    "guide": 1500,
    "review": 500,
    "news": 300,
    "comparison": 600,
    "product_description": 200,
}
CONTENT_READABILITY_MIN: float = 50.0  # Flesch Reading Ease (упрощённый)


# ═══════════════════════════════════════════════════════════════════════════════
# Data-классы
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class ValidationResult:
    """
    Результат валидации агента.

    Attributes:
        status: Статус валидации (passed/failed/warning/skipped)
        score: Оценка качества от 0.0 до 1.0
        errors: Список критических ошибок
        warnings: Список предупреждений
        metadata: Дополнительные метаданные
    """
    status: ValidationStatus
    score: float = 0.0
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_valid(self) -> bool:
        """Проверяет, пройдена ли валидация (passed или warning)."""
        return self.status in (ValidationStatus.PASSED, ValidationStatus.WARNING)

    def to_dict(self) -> Dict[str, Any]:
        """Сериализует результат в словарь."""
        return {
            "status": self.status.value,
            "score": self.score,
            "errors": self.errors,
            "warnings": self.warnings,
            "metadata": self.metadata,
            "is_valid": self.is_valid,
        }


@dataclass
class SpamAnalysisResult:
    """Результат анализа на спам."""
    total_score: int
    high_risk_keywords: List[str]
    medium_risk_keywords: List[str]
    recommendations: List[str]
    risk_level: str  # "low", "medium", "high", "critical"


@dataclass
class UniquenessResult:
    """Результат проверки уникальности текста."""
    uniqueness_score: float  # 0.0 - 1.0
    similar_phrases: List[Dict[str, Any]]
    checked_against: int  # количество проверенных записей
    method: str  # метод проверки


# ═══════════════════════════════════════════════════════════════════════════════
# Вспомогательные функции
# ═══════════════════════════════════════════════════════════════════════════════
def _normalize_text(text: str) -> str:
    """
    Нормализует текст для проверок.

    Убирает лишние пробелы, приводит к нижнему регистру.

    Args:
        text: Исходный текст

    Returns:
        Нормализованный текст
    """
    if not text:
        return ""
    # Убираем лишние пробелы и переносы
    text = " ".join(text.split())
    return text.strip()


def _count_words(text: str) -> int:
    """Подсчитывает количество слов в тексте."""
    return len(text.split())


def _estimate_readability(text: str) -> float:
    """
    Оценивает читаемость текста (упрощённый Flesch Reading Ease).

    Возвращает оценку от 0 до 100, где:
        90-100: Очень легко
        60-80:  Стандартный
        30-50:  Сложный
        0-30:   Очень сложный

    Args:
        text: Текст для оценки

    Returns:
        Оценка читаемости
    """
    text = _normalize_text(text)
    if not text:
        return 0.0

    words = text.split()
    sentences = re.split(r'[.!?]+', text)
    sentences = [s for s in sentences if s.strip()]

    if not sentences or not words:
        return 50.0

    avg_words_per_sentence = len(words) / len(sentences)

    # Упрощённая формула для русского языка
    # Оптимально: 10-15 слов на предложение
    if avg_words_per_sentence <= 10:
        score = 90 - (avg_words_per_sentence - 5) * 3
    elif avg_words_per_sentence <= 20:
        score = 75 - (avg_words_per_sentence - 10) * 2.5
    else:
        score = 50 - (avg_words_per_sentence - 20) * 2

    return max(0.0, min(100.0, score))


def _check_keyword_density(text: str, keywords: List[str]) -> Dict[str, float]:
    """
    Проверяет плотность ключевых слов в тексте.

    Args:
        text: Текст для проверки
        keywords: Список ключевых слов

    Returns:
        Словарь {ключевое_слово: плотность_в_процентах}
    """
    text_lower = text.lower()
    words_count = _count_words(text)

    if words_count == 0:
        return {kw: 0.0 for kw in keywords}

    densities = {}
    for kw in keywords:
        kw_lower = kw.lower()
        # Подсчёт вхождений
        count = text_lower.count(kw_lower)
        density = (count / words_count) * 100
        densities[kw] = round(density, 2)

    return densities


# ═══════════════════════════════════════════════════════════════════════════════
# SEO Валидация
# ═══════════════════════════════════════════════════════════════════════════════
def validate_seo_result(result: Dict[str, Any]) -> ValidationResult:
    """
    Валидирует результат SEO-агента.

    Проверяет:
    - Наличие обязательных полей (title, meta_description, keywords, h1)
    - Длину title (30-60 символов)
    - Длину meta_description (120-160 символов)
    - Длину H1 (10-70 символов)
    - Количество ключевых слов (3-15)
    - Уникальность title и meta_description
    - Наличие слова "smart-skidka" или "скидка" в title
    - Корректность формата keywords
    - Отсутствие дублирующихся ключевых слов

    Args:
        result: Результат работы SEO-агента, содержащий:
            - title: Заголовок страницы
            - meta_description: Мета-описание
            - keywords: Список ключевых слов
            - h1: Заголовок H1
            - canonical_url: Канонический URL (опционально)
            - og_tags: Open Graph теги (опционально)
            - structured_data: Структурированные данные (опционально)

    Returns:
        ValidationResult с детальным результатом проверки
    """
    errors: List[str] = []
    warnings: List[str] = []
    score: float = 1.0
    metadata: Dict[str, Any] = {}

    logger.info("Начало валидации SEO-результата")

    # ─── Проверка обязательных полей ──────────────────────────────────────────
    required_fields = ["title", "meta_description", "keywords", "h1"]
    missing_fields = [f for f in required_fields if f not in result or not result[f]]

    if missing_fields:
        errors.append(f"Отсутствуют обязательные поля: {', '.join(missing_fields)}")
        score -= 0.25 * len(missing_fields)

    # ─── Валидация TITLE ──────────────────────────────────────────────────────
    title = result.get("title", "")
    if title:
        title_len = len(title)
        metadata["title_length"] = title_len

        if title_len < SEO_TITLE_MIN_LENGTH:
            warnings.append(
                f"Title слишком короткий ({title_len} симв., "
                f"рекомендуется {SEO_TITLE_MIN_LENGTH}-{SEO_TITLE_MAX_LENGTH})"
            )
            score -= 0.15
        elif title_len > SEO_TITLE_MAX_LENGTH:
            warnings.append(
                f"Title слишком длинный ({title_len} симв., "
                f"поисковики обрежут до {SEO_TITLE_MAX_LENGTH})"
            )
            score -= 0.1
        else:
            metadata["title_optimal"] = True

        # Проверка на бренд
        brand = os.getenv("BRAND_NAME", "smart-skidka")
        brand_keywords = [brand, brand.replace("-", " "), brand.replace(".", "")]
        # Fallback на дефолтные варианты если бренд = smart-skidka
        if brand == "smart-skidka":
            brand_keywords = ["smart-skidka", "смарт-скидка", "smart skidka"]
        has_brand = any(bk.lower() in title.lower() for bk in brand_keywords)
        if not has_brand:
            warnings.append(f"В title отсутствует упоминание бренда {brand}")
            score -= 0.05

        # Проверка на спам в title (повторение ключевых слов)
        words = title.lower().split()
        word_counts = {}
        for w in words:
            word_counts[w] = word_counts.get(w, 0) + 1
        duplicates = {w: c for w, c in word_counts.items() if c > 2}
        if duplicates:
            warnings.append(f"Повторение слов в title: {duplicates}")
            score -= 0.1

    # ─── Валидация META DESCRIPTION ───────────────────────────────────────────
    meta = result.get("meta_description", "")
    if meta:
        meta_len = len(meta)
        metadata["meta_length"] = meta_len

        if meta_len < SEO_META_MIN_LENGTH:
            warnings.append(
                f"Meta description слишком короткий ({meta_len} симв., "
                f"рекомендуется {SEO_META_MIN_LENGTH}-{SEO_META_MAX_LENGTH})"
            )
            score -= 0.15
        elif meta_len > SEO_META_MAX_LENGTH:
            warnings.append(
                f"Meta description слишком длинный ({meta_len} симв., "
                f"поисковики обрежут до {SEO_META_MAX_LENGTH})"
            )
            score -= 0.1
        else:
            metadata["meta_optimal"] = True

        # Проверка CTA в meta description
        cta_words = ["узнать", "смотреть", "перейти", "выбрать", "найти", "сравнить"]
        has_cta = any(cta in meta.lower() for cta in cta_words)
        if not has_cta:
            warnings.append("В meta description отсутствует призыв к действию (CTA)")
            score -= 0.05

    # ─── Валидация H1 ─────────────────────────────────────────────────────────
    h1 = result.get("h1", "")
    if h1:
        h1_len = len(h1)
        metadata["h1_length"] = h1_len

        if h1_len < SEO_H1_MIN_LENGTH:
            warnings.append(f"H1 слишком короткий ({h1_len} симв., мин. {SEO_H1_MIN_LENGTH})")
            score -= 0.1
        elif h1_len > SEO_H1_MAX_LENGTH:
            warnings.append(f"H1 слишком длинный ({h1_len} симв., макс. {SEO_H1_MAX_LENGTH})")
            score -= 0.05

        # H1 должен отличаться от title
        if title and h1.lower().strip() == title.lower().strip():
            warnings.append("H1 и Title идентичны — рекомендуется разнообразить")
            score -= 0.1

    # ─── Валидация KEYWORDS ───────────────────────────────────────────────────
    keywords = result.get("keywords", [])
    if isinstance(keywords, list):
        keywords_count = len(keywords)
        metadata["keywords_count"] = keywords_count

        if keywords_count < SEO_KEYWORDS_MIN_COUNT:
            warnings.append(
                f"Мало ключевых слов ({keywords_count}, "
                f"рекомендуется {SEO_KEYWORDS_MIN_COUNT}-{SEO_KEYWORDS_MAX_COUNT})"
            )
            score -= 0.1
        elif keywords_count > SEO_KEYWORDS_MAX_COUNT:
            warnings.append(
                f"Много ключевых слов ({keywords_count}, "
                f"рекомендуется не более {SEO_KEYWORDS_MAX_COUNT})"
            )
            score -= 0.05

        # Проверка на дубликаты
        lower_keywords = [k.lower().strip() for k in keywords]
        duplicates = [k for k in lower_keywords if lower_keywords.count(k) > 1]
        if duplicates:
            errors.append(f"Дублирующиеся ключевые слова: {set(duplicates)}")
            score -= 0.15

        # Проверка длины каждого ключевого слова
        for kw in keywords:
            if len(kw) < 2:
                warnings.append(f"Ключевое слово слишком короткое: '{kw}'")
                score -= 0.02

    elif keywords:  # Не список
        errors.append("Keywords должен быть списком строк")
        score -= 0.2

    # ─── Валидация Open Graph тегов (опционально) ────────────────────────────
    og_tags = result.get("og_tags", {})
    if og_tags:
        og_required = ["og:title", "og:description", "og:image"]
        missing_og = [t for t in og_required if t not in og_tags]
        if missing_og:
            warnings.append(f"Отсутствуют важные OG-теги: {missing_og}")
            score -= 0.05
    else:
        warnings.append("Отсутствуют Open Graph теги — рекомендуется добавить")
        score -= 0.05

    # ─── Валидация structured_data (опционально) ─────────────────────────────
    structured = result.get("structured_data", {})
    if structured:
        if "@type" not in structured:
            warnings.append("В structured_data отсутствует поле @type")
            score -= 0.03
    else:
        warnings.append("Отсутствуют структурированные данные (Schema.org)")
        score -= 0.03

    # ─── Итоговая оценка ──────────────────────────────────────────────────────
    final_score = max(0.0, min(1.0, score))

    if errors:
        status = ValidationStatus.FAILED
    elif warnings:
        status = ValidationStatus.WARNING
    else:
        status = ValidationStatus.PASSED

    # SEO требует высокого порога
    if final_score < 0.5:
        status = ValidationStatus.FAILED

    logger.info(
        "Валидация SEO завершена",
        status=status.value,
        score=round(final_score, 3),
        errors_count=len(errors),
        warnings_count=len(warnings),
    )

    return ValidationResult(
        status=status,
        score=final_score,
        errors=errors,
        warnings=warnings,
        metadata=metadata,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# SMM Валидация
# ═══════════════════════════════════════════════════════════════════════════════
def validate_smm_result(result: Dict[str, Any]) -> ValidationResult:
    """
    Валидирует результат SMM-агента (пост для соцсетей).

    Проверяет:
    - Наличие текста поста
    - Длину текста для конкретной платформы
    - Количество хештегов (1-30)
    - Наличие CTA (call-to-action)
    - Наличие ссылки на smart-skidka.ru
    - Эмодзи (не более 20% текста)
    - Форматирование

    Args:
        result: Результат работы SMM-агента:
            - text: Текст поста
            - platform: Платформа (twitter, instagram, vk, telegram)
            - hashtags: Список хештегов
            - cta: Призыв к действию
            - link: Ссылка
            - image_prompt: Описание изображения

    Returns:
        ValidationResult с результатом проверки
    """
    errors: List[str] = []
    warnings: List[str] = []
    score: float = 1.0
    metadata: Dict[str, Any] = {}

    logger.info("Начало валидации SMM-результата")

    platform = result.get("platform", "general").lower()
    metadata["platform"] = platform

    # ─── Проверка текста ──────────────────────────────────────────────────────
    text = result.get("text", "")
    if not text:
        errors.append("Отсутствует текст поста")
        score -= 0.4
    else:
        text_len = len(text)
        metadata["text_length"] = text_len

        # Проверка длины по платформе
        platform_limits = {
            "twitter": SMM_TWITTER_MAX_LENGTH,
            "instagram": SMM_INSTAGRAM_MAX_LENGTH,
            "vk": 10000,
            "telegram": 4096,
            "facebook": 63206,
        }
        limit = platform_limits.get(platform, 2000)

        if text_len > limit:
            errors.append(
                f"Текст превышает лимит {platform} ({text_len} > {limit})"
            )
            score -= 0.3

        # Проверка на минимальную длину
        if text_len < 50:
            warnings.append(f"Текст слишком короткий ({text_len} симв.)")
            score -= 0.1

        # Проверка эмодзи (не более 20% символов)
        emoji_pattern = re.compile(
            "["
            "\U0001F600-\U0001F64F"  # смайлики
            "\U0001F300-\U0001F5FF"  # символы
            "\U0001F680-\U0001F6FF"  # транспорт
            "\U0001F1E0-\U0001F1FF"  # флаги
            "\U00002702-\U000027B0"
            "\U000024C2-\U0001F251"
            "]+",
            flags=re.UNICODE,
        )
        emoji_chars = len("".join(emoji_pattern.findall(text)))
        if text_len > 0:
            emoji_ratio = emoji_chars / text_len
            metadata["emoji_ratio"] = round(emoji_ratio, 3)
            if emoji_ratio > 0.2:
                warnings.append(f"Слишком много эмодзи ({emoji_ratio:.1%})")
                score -= 0.1
            elif emoji_ratio == 0:
                warnings.append("Нет эмодзи — рекомендуется добавить для вовлечённости")
                score -= 0.03

    # ─── Проверка хештегов ────────────────────────────────────────────────────
    hashtags = result.get("hashtags", [])
    if isinstance(hashtags, list):
        hashtags_count = len(hashtags)
        metadata["hashtags_count"] = hashtags_count

        if hashtags_count == 0:
            warnings.append("Нет хештегов — рекомендуется добавить 5-15")
            score -= 0.1
        elif hashtags_count > SMM_HASHTAGS_MAX_COUNT:
            errors.append(
                f"Слишком много хештегов ({hashtags_count}, макс. {SMM_HASHTAGS_MAX_COUNT})"
            )
            score -= 0.2
        elif hashtags_count > SMM_HASHTAGS_OPTIMAL_COUNT:
            warnings.append(
                f"Много хештегов ({hashtags_count}, оптимально {SMM_HASHTAGS_OPTIMAL_COUNT})"
            )
            score -= 0.05

        # Проверка формата хештегов
        for tag in hashtags:
            if not tag.startswith("#"):
                warnings.append(f"Хештег '{tag}' не начинается с #")
                score -= 0.02
            if " " in tag.strip("#"):
                warnings.append(f"Хештег '{tag}' содержит пробелы")
                score -= 0.02

        # Проверка на дубликаты
        lower_tags = [t.lower().strip() for t in hashtags]
        if len(lower_tags) != len(set(lower_tags)):
            warnings.append("Есть дублирующиеся хештеги")
            score -= 0.05

    # ─── Проверка CTA ─────────────────────────────────────────────────────────
    cta = result.get("cta", "")
    if not cta:
        warnings.append("Отсутствует призыв к действию (CTA)")
        score -= 0.1
    else:
        metadata["has_cta"] = True

    # ─── Проверка ссылки ──────────────────────────────────────────────────────
    link = result.get("link", "")
    brand_domain = os.getenv("BRAND_NAME", "smart-skidka.ru")
    brand_short = brand_domain.replace(".ru", "").replace(".com", "").replace(".net", "")
    if not link:
        warnings.append(f"Отсутствует ссылка на {brand_domain}")
        score -= 0.1
    elif brand_domain not in link and brand_short not in link:
        warnings.append(f"Ссылка не ведёт на {brand_domain}")
        score -= 0.1
    else:
        metadata["has_brand_link"] = True

    # ─── Проверка описания изображения ────────────────────────────────────────
    if "image_prompt" not in result and "image_description" not in result:
        warnings.append("Отсутствует описание изображения для поста")
        score -= 0.05

    # ─── Итоговая оценка ──────────────────────────────────────────────────────
    final_score = max(0.0, min(1.0, score))

    if errors:
        status = ValidationStatus.FAILED
    elif warnings:
        status = ValidationStatus.WARNING
    else:
        status = ValidationStatus.PASSED

    logger.info(
        "Валидация SMM завершена",
        status=status.value,
        score=round(final_score, 3),
    )

    return ValidationResult(
        status=status,
        score=final_score,
        errors=errors,
        warnings=warnings,
        metadata=metadata,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Performance (Реклама) Валидация
# ═══════════════════════════════════════════════════════════════════════════════
def validate_performance_result(result: Dict[str, Any]) -> ValidationResult:
    """
    Валидирует результат performance-агента (рекламные объявления).

    Проверяет:
    - Наличие заголовков (5-15 для Google Ads)
    - Длину каждого заголовка (макс. 30 символов)
    - Наличие описаний (2-4)
    - Длину описаний (макс. 90 символов)
    - Ключевые слова
    - Бюджетные ограничения
    - URL посадочной страницы
    - Привязка к smart-skidka.ru

    Args:
        result: Результат работы performance-агента:
            - headlines: Список заголовков
            - descriptions: Список описаний
            - keywords: Ключевые слова для таргетинга
            - final_url: URL посадочной страницы
            - daily_budget: Дневной бюджет
            - targeting: Настройки таргетинга

    Returns:
        ValidationResult с результатом проверки
    """
    errors: List[str] = []
    warnings: List[str] = []
    score: float = 1.0
    metadata: Dict[str, Any] = {}

    logger.info("Начало валидации Performance-результата")

    # ─── Валидация заголовков ─────────────────────────────────────────────────
    headlines = result.get("headlines", [])
    if isinstance(headlines, list):
        headlines_count = len(headlines)
        metadata["headlines_count"] = headlines_count

        if headlines_count < 3:
            errors.append(
                f"Слишком мало заголовков ({headlines_count}, "
                f"рекомендуется 5-15 для Google Ads)"
            )
            score -= 0.2
        elif headlines_count < 5:
            warnings.append(
                f"Мало заголовков ({headlines_count}, рекомендуется 5-15)"
            )
            score -= 0.1

        # Проверка длины каждого заголовка
        long_headlines = []
        for i, h in enumerate(headlines):
            if len(h) > 30:
                long_headlines.append((i + 1, len(h)))
        if long_headlines:
            warnings.append(
                f"Заголовки превышают 30 символов: {long_headlines}"
            )
            score -= 0.05 * len(long_headlines)

        # Проверка уникальности заголовков
        unique_headlines = set(h.lower().strip() for h in headlines)
        if len(unique_headlines) < len(headlines):
            warnings.append("Есть дублирующиеся заголовки")
            score -= 0.1

    else:
        errors.append("Headlines должен быть списком строк")
        score -= 0.3

    # ─── Валидация описаний ───────────────────────────────────────────────────
    descriptions = result.get("descriptions", [])
    if isinstance(descriptions, list):
        desc_count = len(descriptions)
        metadata["descriptions_count"] = desc_count

        if desc_count < 2:
            warnings.append(
                f"Мало описаний ({desc_count}, рекомендуется 2-4)"
            )
            score -= 0.1

        # Проверка длины описаний
        long_descs = []
        for i, d in enumerate(descriptions):
            if len(d) > 90:
                long_descs.append((i + 1, len(d)))
        if long_descs:
            warnings.append(
                f"Описания превышают 90 символов: {long_descs}"
            )
            score -= 0.05 * len(long_descs)

    else:
        warnings.append("Descriptions должен быть списком строк")
        score -= 0.15

    # ─── Валидация ключевых слов ──────────────────────────────────────────────
    keywords = result.get("keywords", [])
    if isinstance(keywords, list):
        if len(keywords) < 5:
            warnings.append(f"Мало ключевых слов ({len(keywords)}, рекомендуется 10-20)")
            score -= 0.1
    elif not keywords:
        warnings.append("Отсутствуют ключевые слова для таргетинга")
        score -= 0.15

    # ─── Валидация URL ────────────────────────────────────────────────────────
    final_url = result.get("final_url", "")
    brand_domain = os.getenv("BRAND_NAME", "smart-skidka.ru")
    brand_short = brand_domain.replace(".ru", "").replace(".com", "").replace(".net", "")
    if not final_url:
        errors.append("Отсутствует URL посадочной страницы")
        score -= 0.2
    elif brand_domain not in final_url and brand_short not in final_url:
        warnings.append(f"URL не ведёт на {brand_domain}")
        score -= 0.1
    else:
        metadata["has_valid_url"] = True

        # Проверка UTM-меток
        if "utm_" not in final_url:
            warnings.append("В URL отсутствуют UTM-метки для отслеживания")
            score -= 0.05

    # ─── Валидация бюджета ────────────────────────────────────────────────────
    budget = result.get("daily_budget", 0)
    if budget:
        metadata["daily_budget"] = budget
        if budget <= 0:
            errors.append("Дневной бюджет должен быть положительным")
            score -= 0.2
        elif budget > 500000:
            warnings.append(f"Дневной бюджет очень высокий ({budget} руб.)")
            score -= 0.05
    else:
        warnings.append("Не указан дневной бюджет")
        score -= 0.1

    # ─── Валидация таргетинга ─────────────────────────────────────────────────
    targeting = result.get("targeting", {})
    if targeting:
        if "geo" not in targeting:
            warnings.append("Не указана геотаргетинг")
            score -= 0.05
        if "language" not in targeting:
            warnings.append("Не указан язык таргетинга")
            score -= 0.03
    else:
        warnings.append("Отсутствуют настройки таргетинга")
        score -= 0.1

    # ─── Итоговая оценка ──────────────────────────────────────────────────────
    final_score = max(0.0, min(1.0, score))

    if errors:
        status = ValidationStatus.FAILED
    elif warnings:
        status = ValidationStatus.WARNING
    else:
        status = ValidationStatus.PASSED

    logger.info(
        "Валидация Performance завершена",
        status=status.value,
        score=round(final_score, 3),
    )

    return ValidationResult(
        status=status,
        score=final_score,
        errors=errors,
        warnings=warnings,
        metadata=metadata,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Email Валидация
# ═══════════════════════════════════════════════════════════════════════════════
def calculate_spam_score(email_content: str) -> int:
    """
    Рассчитывает спам-скор email-сообщения.

    Анализирует текст на наличие спам-триггеров, подозрительных
    паттернов и нарушений лучших практик.

    Оценка:
        0-2   : Низкий риск (безопасно)
        3-5   : Средний риск (внимание)
        6-8   : Высокий риск (вероятно попадет в спам)
        9+    : Критический риск (гарантированно в спам)

    Args:
        email_content: Текст email (subject + body)

    Returns:
        Целочисленный спам-скор от 0 до 10+
    """
    if not email_content:
        return 10  # Пустое письмо = максимальный спам-скор

    score: int = 0
    text_upper = email_content.upper()
    text_lower = email_content.lower()

    # ─── Проверка HIGH риск ключевых слов ─────────────────────────────────────
    found_high = [kw for kw in EMAIL_SPAM_KEYWORDS_HIGH if kw.upper() in text_upper]
    score += len(found_high) * 2  # Каждое HIGH слово = +2

    # ─── Проверка MEDIUM риск ключевых слов ───────────────────────────────────
    found_medium = [kw for kw in EMAIL_SPAM_KEYWORDS_MEDIUM if kw in text_lower]
    score += len(found_medium)  # Каждое MEDIUM слово = +1

    # ─── Проверка на ПРОПИСНЫЕ БУКВЫ ─────────────────────────────────────────
    letters = [c for c in email_content if c.isalpha()]
    uppercase_letters = [c for c in letters if c.isupper()]
    if letters:
        uppercase_ratio = len(uppercase_letters) / len(letters)
        if uppercase_ratio > 0.7:
            score += 3
        elif uppercase_ratio > 0.5:
            score += 1

    # ─── Проверка на множественные знаки препинания ───────────────────────────
    excessive_punctuation = len(re.findall(r'[!]{2,}', email_content))
    excessive_punctuation += len(re.findall(r'[?]{2,}', email_content))
    score += min(excessive_punctuation, 3)

    # ─── Проверка на $$ и цифры ───────────────────────────────────────────────
    money_symbols = len(re.findall(r'\$+', email_content))
    score += min(money_symbols, 2)

    # ─── Проверка на отсутствие отписки ───────────────────────────────────────
    if "unsubscribe" not in text_lower and "отписаться" not in text_lower:
        score += 2

    # ─── Проверка соотношения текста и HTML ───────────────────────────────────
    html_tags = len(re.findall(r'<[^>]+>', email_content))
    if html_tags > 0:
        text_length = len(re.sub(r'<[^>]+>', '', email_content))
        if text_length < html_tags * 5:  # Слишком много HTML относительно текста
            score += 1

    # ─── Проверка длины subject ───────────────────────────────────────────────
    lines = email_content.split("\n")
    subject = lines[0] if lines else ""
    if len(subject) > 80:
        score += 1
    if "!!!" in subject or "???" in subject:
        score += 1

    # ─── Проверка на ссылки ───────────────────────────────────────────────────
    urls = re.findall(r'https?://\S+', email_content)
    if len(urls) > 5:  # Слишком много ссылок
        score += 1

    # Проверка на подозрительные домены в ссылках
    suspicious_domains = ["bit.ly", "tinyurl", "t.co", "short.link"]
    for url in urls:
        for domain in suspicious_domains:
            if domain in url.lower():
                score += 2
                break

    logger.info(
        "Расчёт спам-скора завершён",
        score=score,
        high_risk=found_high,
        medium_risk=found_medium,
    )

    return min(score, 15)  # Максимум 15


def validate_email_result(result: Dict[str, Any]) -> ValidationResult:
    """
    Валидирует результат email-агента.

    Проверяет:
    - Наличие subject, body, preheader
    - Длину subject (оптимально 40-60 символов)
    - Спам-скор (должен быть < 5)
    - Наличие ссылки для отписки (unsubscribe)
    - Наличие preheader
    - Персонализация ({name}, {email})
    - CTA в письме
    - Alt-текст для изображений

    Args:
        result: Результат работы email-агента:
            - subject: Тема письма
            - preheader: Preheader текст
            - body: HTML тело письма
            - text_version: Текстовая версия
            - from_name: Имя отправителя
            - reply_to: Обратный адрес

    Returns:
        ValidationResult с результатом проверки
    """
    errors: List[str] = []
    warnings: List[str] = []
    score: float = 1.0
    metadata: Dict[str, Any] = {}

    logger.info("Начало валидации Email-результата")

    # ─── Проверка обязательных полей ──────────────────────────────────────────
    if "subject" not in result or not result["subject"]:
        errors.append("Отсутствует тема письма (subject)")
        score -= 0.3

    if "body" not in result or not result["body"]:
        errors.append("Отсутствует тело письма (body)")
        score -= 0.3

    # ─── Валидация Subject ────────────────────────────────────────────────────
    subject = result.get("subject", "")
    if subject:
        subj_len = len(subject)
        metadata["subject_length"] = subj_len

        if subj_len < 10:
            warnings.append(f"Тема слишком короткая ({subj_len} симв.)")
            score -= 0.1
        elif subj_len > 80:
            warnings.append(f"Тема слишком длинная ({subj_len} симв.)")
            score -= 0.1
        elif subj_len < EMAIL_SUBJECT_OPTIMAL_MIN or subj_len > EMAIL_SUBJECT_OPTIMAL_MAX:
            warnings.append(
                f"Длина темы неоптимальна ({subj_len}, "
                f"оптимально {EMAIL_SUBJECT_OPTIMAL_MIN}-{EMAIL_SUBJECT_OPTIMAL_MAX})"
            )
            score -= 0.03
        else:
            metadata["subject_optimal"] = True

        # Проверка на спам-триггеры в теме
        for kw in EMAIL_SPAM_KEYWORDS_HIGH:
            if kw.upper() in subject.upper():
                warnings.append(f"Спам-триггер в теме: '{kw}'")
                score -= 0.15

    # ─── Проверка Preheader ───────────────────────────────────────────────────
    preheader = result.get("preheader", "")
    if not preheader:
        warnings.append("Отсутствует preheader — снижает открываемость")
        score -= 0.1
    elif len(preheader) > 100:
        warnings.append(f"Preheader слишком длинный ({len(preheader)} симв.)")
        score -= 0.05
    else:
        metadata["has_preheader"] = True

    # ─── Проверка тела письма ─────────────────────────────────────────────────
    body = result.get("body", "")
    if body:
        # Проверка длины
        body_text = re.sub(r'<[^>]+>', '', body)
        metadata["body_text_length"] = len(body_text)

        if len(body_text) < EMAIL_BODY_MIN_LENGTH:
            warnings.append(
                f"Тело письма слишком короткое ({len(body_text)} симв.)"
            )
            score -= 0.1

        # Расчёт спам-скора
        full_content = f"{subject}\n{preheader}\n{body_text}"
        spam_score = calculate_spam_score(full_content)
        metadata["spam_score"] = spam_score

        if spam_score >= 8:
            errors.append(f"КРИТИЧЕСКИЙ спам-скор: {spam_score}/15 (вероятно в спам)")
            score -= 0.4
        elif spam_score >= 5:
            warnings.append(f"Высокий спам-скор: {spam_score}/15")
            score -= 0.2
        elif spam_score >= 3:
            warnings.append(f"Средний спам-скор: {spam_score}/15")
            score -= 0.05
        else:
            metadata["spam_safe"] = True

        # Проверка ссылки для отписки
        has_unsubscribe = (
            "unsubscribe" in body.lower() or
            "отписаться" in body.lower() or
            "{unsubscribe_url}" in body.lower()
        )
        if not has_unsubscribe:
            errors.append("Отсутствует ссылка для отписки (unsubscribe)")
            score -= 0.2
        else:
            metadata["has_unsubscribe"] = True

        # Проверка персонализации
        personalization_vars = ["{name}", "{first_name}", "{email}", "{{ name }}"]
        has_personalization = any(pv in body for pv in personalization_vars)
        if not has_personalization:
            warnings.append("Нет персонализации — рекомендуется добавить {{ name }}")
            score -= 0.05
        else:
            metadata["has_personalization"] = True

        # Проверка CTA
        cta_patterns = ["перейти", "подробнее", "узнать", "смотреть", "купить",
                        "заказать", "скачать", "получить", "подписаться", "button"]
        has_cta = any(cta in body.lower() for cta in cta_patterns)
        if not has_cta:
            warnings.append("Отсутствует явный призыв к действию (CTA)")
            score -= 0.1
        else:
            metadata["has_cta"] = True

        # Проверка alt-текста для изображений
        img_tags = re.findall(r'<img[^>]*>', body, re.IGNORECASE)
        imgs_without_alt = []
        for img in img_tags:
            if 'alt=' not in img.lower():
                imgs_without_alt.append(img[:50])
        if imgs_without_alt:
            warnings.append(f"{len(imgs_without_alt)} изображений без alt-текста")
            score -= 0.03 * len(imgs_without_alt)

    # ─── Проверка текстовой версии ────────────────────────────────────────────
    text_version = result.get("text_version", "")
    if not text_version:
        warnings.append("Отсутствует текстовая версия письма (plain text)")
        score -= 0.1

    # ─── Проверка отправителя ─────────────────────────────────────────────────
    from_name = result.get("from_name", "")
    brand = os.getenv("BRAND_NAME", "smart-skidka")
    brand_short = brand.replace(".ru", "").replace(".com", "").replace(".net", "")
    if not from_name:
        warnings.append("Не указано имя отправителя (from_name)")
        score -= 0.1
    elif brand_short not in from_name.lower():
        warnings.append(f"Имя отправителя не содержит {brand_short}")
        score -= 0.05
    else:
        metadata["has_brand_from_name"] = True

    # ─── Итоговая оценка ──────────────────────────────────────────────────────
    final_score = max(0.0, min(1.0, score))

    if errors:
        status = ValidationStatus.FAILED
    elif warnings:
        status = ValidationStatus.WARNING
    else:
        status = ValidationStatus.PASSED

    # Email с высоким спам-скором автоматически failed
    if metadata.get("spam_score", 0) >= 8:
        status = ValidationStatus.FAILED

    logger.info(
        "Валидация Email завершена",
        status=status.value,
        score=round(final_score, 3),
        spam_score=metadata.get("spam_score", "N/A"),
    )

    return ValidationResult(
        status=status,
        score=final_score,
        errors=errors,
        warnings=warnings,
        metadata=metadata,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Analytics Валидация
# ═══════════════════════════════════════════════════════════════════════════════
def validate_analytics_result(result: Dict[str, Any]) -> ValidationResult:
    """
    Валидирует результат аналитического агента.

    Проверяет:
    - Наличие метрик (visits, conversions, revenue и т.д.)
    - Корректность дат отчёта
    - Временной диапазон
    - Корректность числовых значений (не отрицательные)
    - Наличие рекомендаций
    - Источник данных
    - Консистентность метрик

    Args:
        result: Результат работы аналитического агента:
            - report_date: Дата отчёта
            - date_range: Диапазон дат (start, end)
            - metrics: Словарь метрик
            - data_source: Источник данных
            - recommendations: Список рекомендаций
            - segments: Сегментация

    Returns:
        ValidationResult с результатом проверки
    """
    errors: List[str] = []
    warnings: List[str] = []
    score: float = 1.0
    metadata: Dict[str, Any] = {}

    logger.info("Начало валидации Analytics-результата")

    # ─── Проверка даты отчёта ─────────────────────────────────────────────────
    report_date = result.get("report_date", "")
    if not report_date:
        warnings.append("Отсутствует дата отчёта")
        score -= 0.1

    # ─── Проверка диапазона дат ───────────────────────────────────────────────
    date_range = result.get("date_range", {})
    if isinstance(date_range, dict):
        start_date = date_range.get("start", "")
        end_date = date_range.get("end", "")
        if not start_date or not end_date:
            warnings.append("Неполный диапазон дат")
            score -= 0.1
    else:
        warnings.append("date_range должен быть словарём с start и end")
        score -= 0.1

    # ─── Проверка метрик ──────────────────────────────────────────────────────
    metrics = result.get("metrics", {})
    if not metrics:
        errors.append("Отсутствуют метрики")
        score -= 0.4
    elif not isinstance(metrics, dict):
        errors.append("Metrics должен быть словарём")
        score -= 0.3
    else:
        metadata["metrics_count"] = len(metrics)

        # Проверяем ключевые метрики
        key_metrics = ["visits", "pageviews", "users", "bounce_rate"]
        found_key = [m for m in key_metrics if m in metrics]
        metadata["key_metrics_found"] = found_key

        if len(found_key) < 2:
            warnings.append(
                f"Мало ключевых метрик ({len(found_key)}/{len(key_metrics)})"
            )
            score -= 0.1

        # Проверка на отрицательные значения
        negative_metrics = []
        for key, value in metrics.items():
            if isinstance(value, (int, float)) and value < 0:
                negative_metrics.append(key)
        if negative_metrics:
            errors.append(f"Отрицательные значения метрик: {negative_metrics}")
            score -= 0.15 * len(negative_metrics)

        # Проверка конверсии (должна быть 0-100%)
        conversion = metrics.get("conversion_rate")
        if conversion is not None:
            if conversion < 0 or conversion > 100:
                errors.append(f"Некорректное значение conversion_rate: {conversion}")
                score -= 0.15
            metadata["conversion_rate"] = conversion

        # Проверка bounce_rate (0-100%)
        bounce = metrics.get("bounce_rate")
        if bounce is not None:
            if bounce < 0 or bounce > 100:
                errors.append(f"Некорректное значение bounce_rate: {bounce}")
                score -= 0.1

    # ─── Проверка источника данных ────────────────────────────────────────────
    data_source = result.get("data_source", "")
    if not data_source:
        warnings.append("Не указан источник данных")
        score -= 0.1
    else:
        metadata["data_source"] = data_source

    # ─── Проверка рекомендаций ────────────────────────────────────────────────
    recommendations = result.get("recommendations", [])
    if isinstance(recommendations, list):
        if len(recommendations) == 0:
            warnings.append("Отсутствуют рекомендации на основе аналитики")
            score -= 0.15
        else:
            metadata["recommendations_count"] = len(recommendations)
    else:
        warnings.append("Recommendations должен быть списком")
        score -= 0.1

    # ─── Проверка сегментации ─────────────────────────────────────────────────
    segments = result.get("segments", {})
    if not segments:
        warnings.append("Нет сегментации данных — рекомендуется добавить")
        score -= 0.05

    # ─── Итоговая оценка ──────────────────────────────────────────────────────
    final_score = max(0.0, min(1.0, score))

    if errors:
        status = ValidationStatus.FAILED
    elif warnings:
        status = ValidationStatus.WARNING
    else:
        status = ValidationStatus.PASSED

    logger.info(
        "Валидация Analytics завершена",
        status=status.value,
        score=round(final_score, 3),
    )

    return ValidationResult(
        status=status,
        score=final_score,
        errors=errors,
        warnings=warnings,
        metadata=metadata,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Content Валидация
# ═══════════════════════════════════════════════════════════════════════════════
def check_uniqueness(text: str, reference_texts: Optional[List[str]] = None) -> float:
    """
    Проверяет уникальность текста путём сравнения с базой.

    Использует алгоритм сравнения n-грамм для оценки схожести.
    Возвращает оценку от 0.0 (полностью скопирован) до 1.0 (полностью уникален).

    Args:
        text: Текст для проверки уникальности
        reference_texts: Список текстов для сравнения (если None, проверяет
                        внутреннюю базу шинглов)

    Returns:
        Оценка уникальности от 0.0 до 1.0
    """
    if not text:
        return 0.0

    text = _normalize_text(text)
    if not text:
        return 0.0

    # Создаём шинглы (3-граммы слов)
    words = text.lower().split()
    if len(words) < 3:
        return 1.0  # Слишком короткий текст считаем уникальным

    shingles: Set[str] = set()
    for i in range(len(words) - 2):
        shingle = " ".join(words[i:i + 3])
        shingles.add(hashlib.md5(shingle.encode(), usedforsecurity=False).hexdigest())

    total_shingles = len(shingles)
    if total_shingles == 0:
        return 1.0

    metadata: Dict[str, Any] = {
        "text_length": len(text),
        "words_count": len(words),
        "shingles_count": total_shingles,
    }

    # P1-12: Без референсных текстов проверка невозможна
    if not reference_texts:
        logger.warning(
            "Проверка уникальности без референсных текстов",
            shingles=total_shingles,
        )
        raise ValueError(
            "reference_texts is required for uniqueness check. "
            "Pass a list of reference texts or use an external plagiarism API."
        )

    # Сравнение с референсными текстами
    max_similarity = 0.0
    similar_phrases: List[Dict[str, Any]] = []

    for ref_text in reference_texts:
        ref_text = _normalize_text(ref_text)
        ref_words = ref_text.lower().split()

        if len(ref_words) < 3:
            continue

        ref_shingles: Set[str] = set()
        for i in range(len(ref_words) - 2):
            shingle = " ".join(ref_words[i:i + 3])
            ref_shingles.add(hashlib.md5(shingle.encode(), usedforsecurity=False).hexdigest())

        if not ref_shingles:
            continue

        # Расчёт схожести через коэффициент Жаккара
        intersection = shingles & ref_shingles
        union = shingles | ref_shingles

        if union:
            similarity = len(intersection) / len(union)
            max_similarity = max(max_similarity, similarity)

            if similarity > 0.3:  # Записываем похожие фразы
                similar_phrases.append({
                    "similarity": round(similarity, 3),
                    "matched_shingles": len(intersection),
                })

    # Уникальность = 1 - максимальная схожесть
    uniqueness = 1.0 - max_similarity

    logger.info(
        "Проверка уникальности завершена",
        uniqueness=round(uniqueness, 3),
        checked_against=len(reference_texts),
    )

    return round(uniqueness, 3)


def validate_content_result(result: Dict[str, Any]) -> ValidationResult:
    """
    Валидирует результат контент-агента.

    Проверяет:
    - Наличие заголовка и основного текста
    - Длину контента по типу (статья, гайд, обзор, новость)
    - Читаемость текста
    - Уникальность (через check_uniqueness)
    - Структуру (заголовки h2, h3)
    - Теги
    - Изображение
    - Внутренние ссылки
    - Ключевые слова и их плотность

    Args:
        result: Результат работы контент-агента:
            - title: Заголовок контента
            - content: Основной текст (HTML или Markdown)
            - content_type: Тип контента (article, guide, review, news, comparison)
            - tags: Теги
            - featured_image: Изображение
            - keywords: Ключевые слова для SEO
            - internal_links: Внутренние ссылки

    Returns:
        ValidationResult с результатом проверки
    """
    errors: List[str] = []
    warnings: List[str] = []
    score: float = 1.0
    metadata: Dict[str, Any] = {}

    logger.info("Начало валидации Content-результата")

    # ─── Проверка обязательных полей ──────────────────────────────────────────
    title = result.get("title", "")
    content = result.get("content", "")
    content_type = result.get("content_type", "article")

    if not title:
        errors.append("Отсутствует заголовок")
        score -= 0.25

    if not content:
        errors.append("Отсутствует основной текст")
        score -= 0.25

    metadata["content_type"] = content_type

    # ─── Проверка длины контента ──────────────────────────────────────────────
    if content:
        # Убираем HTML-теги для подсчёта
        content_text = re.sub(r'<[^>]+>', '', content)
        content_len = len(content_text)
        metadata["content_length"] = content_len

        min_length = CONTENT_MIN_LENGTH.get(content_type, 500)

        if content_len < min_length:
            warnings.append(
                f"Контент слишком короткий ({content_len} симв., "
                f"мин. для {content_type}: {min_length})"
            )
            score -= 0.15
        elif content_len > min_length * 5:
            warnings.append(
                f"Контент очень длинный ({content_len} симв.)"
            )
            score -= 0.03

        # Проверка количества слов
        word_count = _count_words(content_text)
        metadata["word_count"] = word_count

        if word_count < 100:
            warnings.append(f"Мало слов в контенте ({word_count})")
            score -= 0.1

    # ─── Проверка читаемости ──────────────────────────────────────────────────
    if content:
        readability = _estimate_readability(content_text)
        metadata["readability_score"] = round(readability, 2)

        if readability < 30:
            warnings.append(
                f"Низкая читаемость ({readability:.1f}). "
                f"Текст слишком сложный, разбейте предложения."
            )
            score -= 0.1
        elif readability > 90:
            warnings.append(
                f"Очень высокая читаемость ({readability:.1f}). "
                f"Возможно, текст слишком простой."
            )
            score -= 0.02

    # ─── Проверка структуры ───────────────────────────────────────────────────
    if content:
        # Проверка заголовков h2/h3
        h2_count = len(re.findall(r'<h2[^>]*>', content, re.IGNORECASE))
        h2_count += len(re.findall(r'^## ', content, re.MULTILINE))  # Markdown
        h3_count = len(re.findall(r'<h3[^>]*>', content, re.IGNORECASE))
        h3_count += len(re.findall(r'^### ', content, re.MULTILINE))  # Markdown

        metadata["h2_count"] = h2_count
        metadata["h3_count"] = h3_count

        if h2_count == 0:
            warnings.append("Нет заголовков H2 — контент плохо структурирован")
            score -= 0.1
        elif h2_count < 2:
            warnings.append("Мало заголовков H2 — рекомендуется 3-5")
            score -= 0.05

        # Проверка абзацев
        paragraphs = [p for p in content_text.split('\n') if p.strip()]
        avg_paragraph_len = sum(len(p) for p in paragraphs) / len(paragraphs) if paragraphs else 0

        if avg_paragraph_len > 500:
            warnings.append(
                f"Абзацы слишком длинные (средн. {avg_paragraph_len:.0f} симв.)"
            )
            score -= 0.05

    # ─── Проверка тегов ───────────────────────────────────────────────────────
    tags = result.get("tags", [])
    if isinstance(tags, list):
        if len(tags) < 2:
            warnings.append(f"Мало тегов ({len(tags)}, рекомендуется 3-8)")
            score -= 0.05
        elif len(tags) > 15:
            warnings.append(f"Много тегов ({len(tags)}, рекомендуется не более 15)")
            score -= 0.03
    else:
        warnings.append("Tags должен быть списком")
        score -= 0.05

    # ─── Проверка изображения ─────────────────────────────────────────────────
    featured_image = result.get("featured_image", "")
    if not featured_image:
        warnings.append("Отсутствует изображение для контента")
        score -= 0.1
    else:
        metadata["has_image"] = True

    # ─── Проверка ключевых слов и плотности ───────────────────────────────────
    keywords = result.get("keywords", [])
    if isinstance(keywords, list) and keywords and content:
        densities = _check_keyword_density(content_text, keywords)
        metadata["keyword_densities"] = densities

        # Проверяем, что ключевые слова присутствуют
        for kw, density in densities.items():
            if density == 0:
                warnings.append(f"Ключевое слово '{kw}' не найдено в тексте")
                score -= 0.05
            elif density > 5:
                warnings.append(
                    f"Высокая плотность ключевого слова '{kw}' ({density:.1f}%)"
                )
                score -= 0.1

    # ─── Проверка внутренних ссылок ───────────────────────────────────────────
    internal_links = result.get("internal_links", [])
    if isinstance(internal_links, list):
        if len(internal_links) == 0:
            warnings.append("Нет внутренних ссылок — рекомендуется добавить 2-5")
            score -= 0.05
        else:
            metadata["internal_links_count"] = len(internal_links)
    else:
        warnings.append("internal_links должен быть списком")
        score -= 0.03

    # ─── Проверка уникальности ────────────────────────────────────────────────
    if content:
        uniqueness = check_uniqueness(content_text)
        metadata["uniqueness_score"] = uniqueness

        if uniqueness < 0.7:
            warnings.append(f"Низкая уникальность текста ({uniqueness:.1%})")
            score -= 0.15
        elif uniqueness < 0.85:
            warnings.append(f"Средняя уникальность ({uniqueness:.1%})")
            score -= 0.05

    # ─── Проверка на пустые секции ────────────────────────────────────────────
    empty_sections = re.findall(r'<h[23][^>]*>.*?</h[23]>\s*(?=<h[23]|</|$)',
                                content, re.IGNORECASE | re.DOTALL)
    if empty_sections:
        warnings.append(f"{len(empty_sections)} пустых секций после заголовков")
        score -= 0.05 * len(empty_sections)

    # ─── Итоговая оценка ──────────────────────────────────────────────────────
    final_score = max(0.0, min(1.0, score))

    if errors:
        status = ValidationStatus.FAILED
    elif warnings:
        status = ValidationStatus.WARNING
    else:
        status = ValidationStatus.PASSED

    # Контент с критически низкой уникальностью = failed
    if metadata.get("uniqueness_score", 1.0) < 0.5:
        status = ValidationStatus.FAILED

    logger.info(
        "Валидация Content завершена",
        status=status.value,
        score=round(final_score, 3),
        words=metadata.get("word_count", 0),
    )

    return ValidationResult(
        status=status,
        score=final_score,
        errors=errors,
        warnings=warnings,
        metadata=metadata,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Trend Research валидатор
# ═══════════════════════════════════════════════════════════════════════════════
AGENT_NAMES: List[str] = [
    "seo_agent",
    "smm_agent",
    "performance_agent",
    "email_agent",
    "analytics_agent",
    "content_agent",
    "trend_agent",
]


def _check_trend_freshness(result: Dict[str, Any]) -> bool:
    """Проверка что тренд не устарел (>48 часов)."""
    detected = result.get("detected_at")
    if not detected:
        return True
    try:
        dt = datetime.fromisoformat(str(detected).replace("Z", "+00:00"))
        return (datetime.now(dt.tzinfo) - dt).total_seconds() < 48 * 3600
    except Exception:
        return True


def validate_trend_result(result: Dict[str, Any]) -> ValidationResult:
    """
    Валидирует результат Trend Research Agent.

    Проверяет корректность типа тренда, confidence, наличие заголовка,
    описания, метрик, источников данных, рекомендаций и свежесть тренда.
    """
    checks: Dict[str, bool] = {
        "has_trend_type": result.get("trend_type") in ["product", "category", "event", "viral", "seasonal"],
        "confidence_valid": 0.0 <= result.get("confidence", 0) <= 1.0,
        "confidence_threshold": result.get("confidence", 0) >= 0.6,
        "has_title": bool(result.get("title")),
        "has_description": bool(result.get("description")),
        "min_data_sources": len(result.get("data_sources", [])) >= 2,
        "has_metrics": bool(result.get("metrics")),
        "has_recommendations": len(result.get("recommended_actions", [])) > 0,
        "actions_have_agents": all(
            a.get("agent") in AGENT_NAMES
            for a in result.get("recommended_actions", [])
        ),
        "status_valid": result.get("status") in ["rising", "peak", "declining"],
        "not_expired": _check_trend_freshness(result),
    }

    score = result.get("confidence", 0) * (sum(checks.values()) / len(checks))
    passed = all(checks.values())
    errors: List[str] = []
    warnings: List[str] = []

    if not checks["has_trend_type"]:
        errors.append(f"Некорректный тип тренда: {result.get('trend_type')}")
    if not checks["confidence_threshold"]:
        errors.append(f"Недостаточная уверенность: {result.get('confidence', 0):.2f} (мин. 0.6)")
    if not checks["has_title"]:
        errors.append("Отсутствует заголовок тренда")
    if not checks["has_description"]:
        errors.append("Отсутствует описание тренда")
    if not checks["min_data_sources"]:
        warnings.append(f"Мало источников данных ({len(result.get('data_sources', []))}, мин. 2)")
    if not checks["actions_have_agents"]:
        actions = result.get("recommended_actions", [])
        unknown = [a.get("agent") for a in actions if a.get("agent") not in AGENT_NAMES]
        errors.append(f"Неизвестные агенты в рекомендациях: {unknown}")
    if not checks["not_expired"]:
        warnings.append("Тренд устарел (>48 часов)")

    status = ValidationStatus.PASSED if passed else ValidationStatus.FAILED

    return ValidationResult(
        status=status,
        score=round(score, 3),
        errors=errors,
        warnings=warnings,
        metadata={"checks": checks},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Универсальный валидатор по типу агента
# ═══════════════════════════════════════════════════════════════════════════════
def validate_by_type(result: Dict[str, Any], agent_type: str) -> ValidationResult:
    """
    Универсальная функция валидации по типу агента.

    Args:
        result: Результат работы агента
        agent_type: Тип агента (seo, smm, performance, email, analytics, content, trend)

    Returns:
        ValidationResult с результатом проверки
    """
    validators = {
        "seo": validate_seo_result,
        "smm": validate_smm_result,
        "performance": validate_performance_result,
        "email": validate_email_result,
        "analytics": validate_analytics_result,
        "content": validate_content_result,
        "trend": validate_trend_result,
    }

    validator_func = validators.get(agent_type.lower())
    if not validator_func:
        logger.warning(f"Неизвестный тип агента: {agent_type}")
        return ValidationResult(
            status=ValidationStatus.SKIPPED,
            score=0.0,
            warnings=[f"Неизвестный тип агента: {agent_type}"],
        )

    return validator_func(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Точка входа для тестирования
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    # Пример тестирования валидаторов
    print("=" * 60)
    print("ТЕСТИРОВАНИЕ ВАЛИДАТОРОВ")
    print("=" * 60)

    # Тест SEO
    seo_result = {
        "title": "Лучшие скидки на электронику — smart-skidka.ru 2024",
        "meta_description": "Найдите лучшие скидки на электронику в интернет-магазинах. "
        "Сравнивайте цены и экономьте до 50% на покупках вместе с smart-skidka.ru.",
        "keywords": ["скидки", "электроника", "дешевые гаджеты", "распродажа", "сравнение цен"],
        "h1": "Скидки на электронику: лучшие предложения",
    }
    seo_validation = validate_seo_result(seo_result)
    print(f"\nSEO: {seo_validation.status.value} (score: {seo_validation.score:.2f})")
    for e in seo_validation.errors:
        print(f"  Ошибка: {e}")
    for w in seo_validation.warnings:
        print(f"  Предупреждение: {w}")

    # Тест Email + Spam Score
    email_body = (
        "Узнайте о наших лучших скидках! Перейдите на smart-skidka.ru "
        "и сравните цены на тысячи товаров.\n\n"
        "<a href='{unsubscribe_url}'>Отписаться от рассылки</a>"
    )
    spam = calculate_spam_score("Лучшие скидки этого месяца!" + "\n" + email_body)
    print(f"\nSpam Score: {spam}/15")

    # Тест Content
    content_result = {
        "title": "Как выбрать смартфон со скидкой",
        "content": (
            "<h2>Введение</h2><p>Выбор смартфона — важная задача.</p>"
            "<h2>Критерии выбора</h2><p>Обратите внимание на процессор, камеру и батарею.</p>"
            "<h2>Где искать скидки</h2><p>На smart-skidka.ru собраны лучшие предложения.</p>"
        ),
        "content_type": "article",
        "tags": ["смартфоны", "скидки", "гаджеты"],
        "keywords": ["смартфон", "скидка", "купить"],
        "featured_image": "https://smart-skidka.ru/images/smartphone-guide.jpg",
        "internal_links": ["https://smart-skidka.ru/category/phones"],
    }
    content_validation = validate_content_result(content_result)
    print(f"\nContent: {content_validation.status.value} (score: {content_validation.score:.2f})")
    print(f"  Words: {content_validation.metadata.get('word_count', 0)}")
    print(f"  Readability: {content_validation.metadata.get('readability_score', 0)}")
    print(f"  Uniqueness: {content_validation.metadata.get('uniqueness_score', 0)}")
