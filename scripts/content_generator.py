#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                     CONTENT GENERATOR                                ║
║                         smart-skidka.ru                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  Вспомогательный модуль для генерации маркетингового контента.      ║
║  Создаёт SEO-страницы, описания товаров, сравнения, гайды.         ║
║  Поддерживает batch-генерацию и валидацию результатов.              ║
╚══════════════════════════════════════════════════════════════════════╝

Функции:
    - generate_seo_page          : Генерация SEO-страницы для категории
    - generate_product_description : Генерация описания товара
    - generate_comparison          : Сравнение двух товаров
    - generate_guide               : Создание гайда/инструкции
    - batch_generate               : Batch-генерация контента

Классы:
    - ContentGenerator : Основной генератор с LLM
    - ContentTemplate  : Шаблоны для разных типов контента

Example:
    >>> generator = ContentGenerator()
    >>> page = await generator.generate_seo_page(
    ...     category="Смартфоны",
    ...     keywords=["смартфоны со скидкой", "купить смартфон"]
    ... )
    >>> descriptions = await generator.batch_generate(
    ...     count=10, content_type="product_description"
    ... )
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

import aiohttp
import structlog
from dotenv import load_dotenv

# ═══════════════════════════════════════════════════════════════════════════════
# Загрузка переменных окружения
# ═══════════════════════════════════════════════════════════════════════════════
_env_loaded = load_dotenv()
if not _env_loaded and not os.getenv("LLM_API_KEY"):
    import warnings

    warnings.warn(
        ".env файл не найден и переменные окружения не заданы. " "Система может работать некорректно.",
        RuntimeWarning,
        stacklevel=2,
    )

# ═══════════════════════════════════════════════════════════════════════════════
# Настройка логирования
# ═══════════════════════════════════════════════════════════════════════════════
logger = structlog.get_logger("content_generator")


# ═══════════════════════════════════════════════════════════════════════════════
# Data-классы
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class SEOPage:
    """SEO-страница для категории."""

    title: str
    meta_description: str
    h1: str
    content: str
    keywords: List[str]
    canonical_url: str = ""
    og_tags: Dict[str, str] = field(default_factory=dict)
    structured_data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ProductDescription:
    """Описание товара."""

    title: str
    description: str
    features: List[str]
    pros: List[str]
    cons: List[str]
    price_info: str = ""
    where_to_buy: List[str] = field(default_factory=list)


@dataclass
class Comparison:
    """Сравнение двух товаров."""

    title: str
    product_a_name: str
    product_b_name: str
    verdict: str
    comparison_table: Dict[str, Dict[str, str]]
    winner: str = ""
    recommendation: str = ""


@dataclass
class Guide:
    """Гайд / инструкция."""

    title: str
    introduction: str
    steps: List[Dict[str, str]]
    conclusion: str
    tags: List[str] = field(default_factory=list)
    reading_time_min: int = 0


@dataclass
class BlogArticle:
    """Блог-статья о товаре / категории."""

    title: str
    subtitle: str
    introduction: str
    sections: List[Dict[str, str]]
    conclusion: str
    tags: List[str] = field(default_factory=list)
    reading_time_min: int = 0
    product_mentions: List[str] = field(default_factory=list)
    cta_text: str = ""
    featured_image_prompt: str = ""


# ═══════════════════════════════════════════════════════════════════════════════
# ContentGenerator — Основной класс генератора
# ═══════════════════════════════════════════════════════════════════════════════
class ContentGenerator:
    """
    Генератор контента для smart-skidka.ru.

    Создаёт различные типы маркетингового контента
    с помощью LLM API. Поддерживает batch-генерацию,
    валидацию и шаблонизацию.

    Attributes:
        api_key: API ключ для LLM
        model: Название модели
        base_url: URL API

    Example:
        >>> gen = ContentGenerator(api_key="sk-...")
        >>> page = await gen.generate_seo_page("Ноутбуки", ["ноутбуки со скидкой"])
        >>> blog = await gen.generate_blog_article(
        ...     product={"title": "Беспроводные наушники", "category": "электроника"}
        ... )
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "anthropic/claude-opus-4.6",
        base_url: Optional[str] = None,
    ) -> None:
        """
        Инициализация генератора.

        Args:
            api_key: API ключ LLM (или LLM_API_KEY из env)
            model: Название модели
            base_url: URL API (определяется автоматически)
        """
        self.api_key: str = api_key or os.getenv("LLM_API_KEY", "")
        self.model: str = model
        self.timeout: aiohttp.ClientTimeout = aiohttp.ClientTimeout(total=120)

        if "rrouter" in model or "anthropic" in model:
            self.base_url = "https://api.rrouter.ai/v1/chat/completions"
        else:
            self.base_url = base_url or os.getenv("LLM_BASE_URL", "https://api.deepseek.com/v1/chat/completions")

        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(3)

        if not self.api_key:
            logger.warning("API ключ не задан — генератор работает в режиме шаблонов")

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получает или создаёт HTTP-сессию."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._session

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        """
        Вызывает LLM API для генерации контента.

        Args:
            system_prompt: Системный промпт
            user_prompt: Пользовательский запрос
            temperature: Температура генерации
            max_tokens: Максимальное количество токенов

        Returns:
            Результат генерации с content, usage, elapsed_ms
        """
        if not self.api_key:
            logger.warning("API ключ не задан, возвращаем шаблон")
            return {"content": "", "usage": {}, "elapsed_ms": 0, "error": "No API key"}

        async with self._semaphore:
            session = await self._get_session()

            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }

            logger.info("Запрос к LLM", prompt_length=len(user_prompt))
            start = time.monotonic()

            try:
                async with session.post(self.base_url, json=payload) as resp:
                    resp.raise_for_status()
                    data = await resp.json()

                    elapsed = (time.monotonic() - start) * 1000
                    content = ""
                    if data.get("choices"):
                        content = data["choices"][0].get("message", {}).get("content", "")

                    return {
                        "content": content,
                        "usage": data.get("usage", {}),
                        "elapsed_ms": round(elapsed, 2),
                    }

            except Exception as e:
                logger.error("Ошибка LLM", error=str(e))
                return {"content": "", "usage": {}, "elapsed_ms": 0, "error": str(e)}

    def _parse_json_response(self, content: str) -> Dict[str, Any]:
        """
        Извлекает JSON из ответа LLM.

        Убирает markdown-обёртку и парсит JSON.

        Args:
            content: Сырой текст от LLM

        Returns:
            Распарсенный словарь
        """
        content = content.strip()

        # Убираем ```json ... ```
        if content.startswith("```"):
            lines = content.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Пробуем найти JSON в тексте
            import re

            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError:
                    pass
            return {"raw_text": content, "parse_error": True}

    # ─── SEO-страница ─────────────────────────────────────────────────────────

    async def generate_seo_page(
        self,
        category: str,
        keywords: List[str],
        extra_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Генерирует SEO-страницу для категории товаров.

        Создаёт оптимизированные title, meta-description, H1 и контент.

        Args:
            category: Название категории (например, "Смартфоны")
            keywords: Список ключевых слов
            extra_context: Дополнительный контекст

        Returns:
            Словарь с SEO-элементами:
                - title: Заголовок страницы
                - meta_description: Мета-описание
                - h1: Заголовок H1
                - content: Основной контент
                - keywords: Ключевые слова
                - canonical_url: Канонический URL
                - og_tags: Open Graph теги
        """
        system_prompt = (
            "Ты — эксперт по SEO для e-commerce сайта агрегатора скидок smart-skidka.ru. "
            "Твоя задача — создать оптимизированную SEO-страницу для категории товаров. "
            "Верни результат строго в формате JSON."
        )

        keywords_str = ", ".join(keywords)
        context = extra_context or {}
        popular = context.get("popular_products", "")
        trends = context.get("trends", "")

        user_prompt = f"""Создай SEO-страницу для категории "{category}".

Ключевые слова: {keywords_str}

Требования:
1. Title: 50-60 символов, включай ключевые слова и бренд smart-skidka.ru
2. Meta description: 150-160 символов, привлекательное с CTA
3. H1: 20-60 символов, естественное включение ключевых слов
4. Контент: 500-800 символов, полезный текст о категории
5. Укажи canonical_url
6. Создай og_tags (title, description, image)

Формат ответа (JSON):
{{
    "title": "...",
    "meta_description": "...",
    "h1": "...",
    "content": "...",
    "keywords": ["..."],
    "canonical_url": "https://smart-skidka.ru/category/...",
    "og_tags": {{
        "og:title": "...",
        "og:description": "...",
        "og:image": "..."
    }}
}}"""

        logger.info("Генерация SEO-страницы", category=category)
        llm_result = await self._call_llm(system_prompt, user_prompt, temperature=0.6)

        if llm_result.get("error"):
            logger.error("Ошибка генерации SEO", error=llm_result["error"])
            return self._fallback_seo_page(category, keywords)

        parsed = self._parse_json_response(llm_result["content"])

        # Если не удалось распарсить, используем fallback
        if parsed.get("parse_error"):
            return self._fallback_seo_page(category, keywords)

        # Добавляем метаданные
        parsed["_metadata"] = {
            "generated_at": datetime.now().isoformat(),
            "category": category,
            "llm_model": self.model,
            "elapsed_ms": llm_result.get("elapsed_ms", 0),
            "content_type": "seo_page",
        }

        logger.info("SEO-страница сгенерирована", category=category)
        return parsed

    def _fallback_seo_page(self, category: str, keywords: List[str]) -> Dict[str, Any]:
        """Создаёт базовую SEO-страницу при ошибке LLM."""
        main_kw = keywords[0] if keywords else category.lower()
        return {
            "title": f"{category} со скидкой до 70% — smart-skidka.ru 2024",
            "meta_description": (
                f"Лучшие предложения на {category.lower()}. "
                f"Сравнивайте цены и находите выгодные скидки на smart-skidka.ru. "
                f"Экономьте на покупках уже сегодня!"
            ),
            "h1": f"{category}: лучшие предложения и скидки",
            "content": (
                f"На этой странице собраны лучшие предложения на {category.lower()}. "
                f"Мы ежедневно обновляем базу и добавляем новые скидки от проверенных магазинов. "
                f"Сравнивайте цены, читайте отзывы и выбирайте лучшее!"
            ),
            "keywords": keywords[:10],
            "canonical_url": f"https://smart-skidka.ru/category/{category.lower().replace(' ', '-')}",
            "og_tags": {
                "og:title": f"{category} со скидкой — smart-skidka.ru",
                "og:description": f"Лучшие скидки на {category.lower()}",
                "og:image": "https://smart-skidka.ru/images/og-default.jpg",
            },
            "_metadata": {
                "generated_at": datetime.now().isoformat(),
                "category": category,
                "fallback": True,
                "content_type": "seo_page",
            },
        }

    # ─── Описание товара ──────────────────────────────────────────────────────

    async def generate_product_description(
        self,
        product: Dict[str, Any],
        style: str = "informative",
    ) -> Dict[str, Any]:
        """
        Генерирует описание товара.

        Создаёт структурированное описание с характеристиками,
        плюсами и минусами товара.

        Args:
            product: Информация о товаре:
                - name: Название товара
                - brand: Бренд
                - category: Категория
                - specs: Характеристики
                - price: Цена
                - discount: Скидка
            style: Стиль описания (informative, selling, review)

        Returns:
            Словарь с описанием:
                - title: Заголовок
                - description: Полное описание
                - features: Ключевые особенности
                - pros: Плюсы
                - cons: Минусы
                - price_info: Информация о цене
        """
        name = product.get("name", "Товар")
        brand = product.get("brand", "")
        category = product.get("category", "")
        specs = product.get("specs", {})
        price = product.get("price", "")
        discount = product.get("discount", "")

        system_prompt = (
            "Ты — эксперт по написанию описаний товаров для агрегатора скидок smart-skidka.ru. "
            "Создавай информативные, продающие описания. Верни результат в JSON."
        )

        specs_str = "\n".join([f"- {k}: {v}" for k, v in specs.items()]) if specs else ""

        user_prompt = f"""Создай описание товара:

Название: {name}
Бренд: {brand}
Категория: {category}
Цена: {price}
Скидка: {discount}
Характеристики:
{specs_str}

Стиль: {style}

Требования:
1. Заголовок: привлекательный, 50-80 символов
2. Описание: 300-600 символов, полезная информация
3. Особенности: 4-6 пунктов
4. Плюсы: 3-5 пунктов
5. Минусы: 2-3 пункта (честно)
6. Price_info: краткая информация о цене

Формат (JSON):
{{
    "title": "...",
    "description": "...",
    "features": ["..."],
    "pros": ["..."],
    "cons": ["..."],
    "price_info": "..."
}}"""

        logger.info("Генерация описания товара", product=name)
        llm_result = await self._call_llm(system_prompt, user_prompt, temperature=0.7)

        if llm_result.get("error"):
            return self._fallback_product_description(product)

        parsed = self._parse_json_response(llm_result["content"])

        if parsed.get("parse_error"):
            return self._fallback_product_description(product)

        parsed["_metadata"] = {
            "generated_at": datetime.now().isoformat(),
            "product_name": name,
            "style": style,
            "llm_model": self.model,
            "elapsed_ms": llm_result.get("elapsed_ms", 0),
            "content_type": "product_description",
        }

        return parsed

    def _fallback_product_description(self, product: Dict[str, Any]) -> Dict[str, Any]:
        """Создаёт базовое описание при ошибке LLM."""
        name = product.get("name", "Товар")
        brand = product.get("brand", "")
        category = product.get("category", "")
        price = product.get("price", "")
        discount = product.get("discount", "")

        return {
            "title": f"{name} — обзор и лучшие цены",
            "description": (
                f"{name} от {brand} — отличный выбор в категории {category}. "
                f"Товар пользуется популярностью у покупателей благодаря "
                f"оптимальному соотношению цены и качества."
            ),
            "features": [
                f"Надёжный бренд {brand}",
                f"Категория: {category}",
                "Проверенные магазины",
            ],
            "pros": ["Хорошее соотношение цена/качество", "Наличие гарантии"],
            "cons": ["Может быть недоступен в некоторых магазинах"],
            "price_info": (f"Цена: {price}, скидка: {discount}" if discount else f"Цена от {price}"),
            "_metadata": {
                "generated_at": datetime.now().isoformat(),
                "fallback": True,
                "content_type": "product_description",
            },
        }

    # ─── Сравнение товаров ────────────────────────────────────────────────────

    async def generate_comparison(
        self,
        product_a: Dict[str, Any],
        product_b: Dict[str, Any],
        criteria: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Генерирует сравнение двух товаров.

        Создаёт подробное сравнение с таблицей характеристик
        и вердиктом о лучшем выборе.

        Args:
            product_a: Информация о первом товаре
            product_b: Информация о втором товаре
            criteria: Критерии сравнения (если None — используются стандартные)

        Returns:
            Словарь со сравнением:
                - title: Заголовок
                - product_a_name: Название товара A
                - product_b_name: Название товара B
                - comparison_table: Таблица сравнения
                - verdict: Вердикт
                - winner: Победитель (A, B или tie)
                - recommendation: Рекомендация
        """
        name_a = product_a.get("name", "Товар A")
        name_b = product_b.get("name", "Товар B")
        specs_a = product_a.get("specs", {})
        specs_b = product_b.get("specs", {})
        price_a = product_a.get("price", "N/A")
        price_b = product_b.get("price", "N/A")

        criteria = criteria or ["Цена", "Качество", "Популярность", "Надёжность"]

        system_prompt = (
            "Ты — эксперт по сравнению товаров для smart-skidka.ru. "
            "Создавай честные, объективные сравнения. Верни результат в JSON."
        )

        user_prompt = f"""Создай сравнение товаров:

Товар A: {name_a}
Цена A: {price_a}
Характеристики A: {json.dumps(specs_a, ensure_ascii=False)}

Товар B: {name_b}
Цена B: {price_b}
Характеристики B: {json.dumps(specs_b, ensure_ascii=False)}

Критерии сравнения: {', '.join(criteria)}

Требования:
1. Заголовок: "{name_a} vs {name_b}: что выбрать"
2. Таблица сравнения: по каждому критерию указать "A", "B" или "="
3. Вердикт: краткий вывод
4. Winner: "A", "B" или "tie"
5. Рекомендация: для кого какой товар лучше

Формат (JSON):
{{
    "title": "...",
    "product_a_name": "...",
    "product_b_name": "...",
    "comparison_table": {{
        "Критерий": {{"A": "значение", "B": "значение", "winner": "A/B/="}}
    }},
    "verdict": "...",
    "winner": "A/B/tie",
    "recommendation": "..."
}}"""

        logger.info("Генерация сравнения", product_a=name_a, product_b=name_b)
        llm_result = await self._call_llm(system_prompt, user_prompt, temperature=0.5)

        if llm_result.get("error"):
            return self._fallback_comparison(product_a, product_b, criteria)

        parsed = self._parse_json_response(llm_result["content"])

        if parsed.get("parse_error"):
            return self._fallback_comparison(product_a, product_b, criteria)

        parsed["_metadata"] = {
            "generated_at": datetime.now().isoformat(),
            "llm_model": self.model,
            "elapsed_ms": llm_result.get("elapsed_ms", 0),
            "content_type": "comparison",
        }

        return parsed

    def _fallback_comparison(
        self,
        product_a: Dict[str, Any],
        product_b: Dict[str, Any],
        criteria: List[str],
    ) -> Dict[str, Any]:
        """Создаёт базовое сравнение при ошибке LLM."""
        name_a = product_a.get("name", "Товар A")
        name_b = product_b.get("name", "Товар B")

        table = {}
        for criterion in criteria:
            table[criterion] = {
                "A": product_a.get("specs", {}).get(criterion, "N/A"),
                "B": product_b.get("specs", {}).get(criterion, "N/A"),
                "winner": "=",
            }

        return {
            "title": f"{name_a} vs {name_b}: сравнение",
            "product_a_name": name_a,
            "product_b_name": name_b,
            "comparison_table": table,
            "verdict": f"Оба товара имеют свои преимущества. Выбор зависит от ваших приоритетов.",
            "winner": "tie",
            "recommendation": "Сравните цены и характеристики, чтобы сделать выбор.",
            "_metadata": {
                "generated_at": datetime.now().isoformat(),
                "fallback": True,
                "content_type": "comparison",
            },
        }

    # ─── Гайд / инструкция ────────────────────────────────────────────────────

    async def generate_guide(
        self,
        topic: str,
        steps: Optional[List[str]] = None,
        target_audience: str = "general",
    ) -> Dict[str, Any]:
        """
        Генерирует гайд / инструкцию.

        Создаёт пошаговое руководство по заданной теме
        с советами и рекомендациями.

        Args:
            topic: Тема гайда
            steps: Опциональные шаги (если None — генерируются автоматически)
            target_audience: Целевая аудитория

        Returns:
            Словарь с гайдом:
                - title: Заголовок
                - introduction: Введение
                - steps: Список шагов
                - conclusion: Заключение
                - tags: Теги
                - reading_time_min: Время чтения
        """
        system_prompt = (
            "Ты — эксперт по созданию гайдов для агрегатора скидок smart-skidka.ru. "
            "Создавай полезные, практичные инструкции. Верни результат в JSON."
        )

        steps_instruction = ""
        if steps:
            steps_str = "\n".join([f"- {s}" for s in steps])
            steps_instruction = f"\nПредложенные шаги:\n{steps_str}"

        user_prompt = f"""Создай гайд на тему: "{topic}"

Целевая аудитория: {target_audience}{steps_instruction}

Требования:
1. Заголовок: привлекательный, 40-80 символов, включай ключевые слова
2. Введение: 150-300 символов, заинтересовывает читателя
3. Шаги: 5-10 шагов, каждый с заголовком и описанием (100-300 символов)
4. Заключение: 100-200 символов, подводит итог
5. Теги: 3-7 релевантных тегов
6. Reading_time_min: оценочное время чтения

Формат (JSON):
{{
    "title": "...",
    "introduction": "...",
    "steps": [
        {{"title": "Шаг 1: ...", "description": "..."}},
        {{"title": "Шаг 2: ...", "description": "..."}}
    ],
    "conclusion": "...",
    "tags": ["..."],
    "reading_time_min": 5
}}"""

        logger.info("Генерация гайда", topic=topic)
        llm_result = await self._call_llm(system_prompt, user_prompt, temperature=0.7)

        if llm_result.get("error"):
            return self._fallback_guide(topic, steps)

        parsed = self._parse_json_response(llm_result["content"])

        if parsed.get("parse_error"):
            return self._fallback_guide(topic, steps)

        # Расчёт времени чтения
        content_text = parsed.get("introduction", "") + " ".join(
            s.get("description", "") for s in parsed.get("steps", [])
        )
        word_count = len(content_text.split())
        parsed["reading_time_min"] = max(1, round(word_count / 200))

        parsed["_metadata"] = {
            "generated_at": datetime.now().isoformat(),
            "topic": topic,
            "target_audience": target_audience,
            "llm_model": self.model,
            "elapsed_ms": llm_result.get("elapsed_ms", 0),
            "word_count": word_count,
            "content_type": "guide",
        }

        return parsed

    async def generate_blog_article(
        self,
        product: Dict[str, Any],
        angle: str = "story",
        tone: str = "friendly",
    ) -> Dict[str, Any]:
        """
        Генерирует блог-статью о товаре — с историей, применением, лайфхаками.

        Создаёт нарративный контент: рассказ о товаре, сценарии использования,
        личный опыт, советы. Публикуется в блоге smart-skidka.ru/blog/

        Args:
            product: Данные о товаре:
                - title: Название товара
                - category: Категория
                - price: Цена со скидкой
                - original_price: Цена без скидки
                - features: Список характеристик
                - image_url: URL изображения (опционально)
            angle: Угол статьи — "story" (история), "review" (обзор),
                   "howto" (лайфхаки), "comparison" (vs конкуренты)
            tone: Тон — "friendly" (дружелюбный), "expert" (экспертный),
                  "humorous" (юмористический)

        Returns:
            Словарь с блог-статьёй:
                - title: Заголовок
                - subtitle: Подзаголовок
                - introduction: Введение (150-300 символов)
                - sections: Разделы статьи (3-5 шт.)
                - conclusion: Заключение с CTA
                - tags: Теги
                - reading_time_min: Время чтения
                - product_mentions: Упоминания товаров
                - cta_text: Призыв к действию
                - featured_image_prompt: Промпт для картинки
        """
        title = product.get("title", "Товар")
        category = product.get("category", "")
        price = product.get("price", 0)
        original = product.get("original_price", 0)
        discount = product.get("discount", 0)
        features = product.get("features", [])
        features_str = "\n".join([f"- {f}" for f in features]) if features else ""

        angle_prompts = {
            "story": "Расскажи историю: как этот товар появился в твоей жизни, что изменил, как используешь каждый день. Личный нарратив.",
            "review": "Честный обзор: плюсы, минусы, кому подходит, кому нет. Экспертная оценка.",
            "howto": "10 лайфхаков и неожиданных способов применения. Практические советы.",
            "comparison": "Сравни с аналогами: почему этот товар выигрывает. Таблица сравнения.",
        }
        angle_desc = angle_prompts.get(angle, angle_prompts["story"])

        tone_prompts = {
            "friendly": "Пиши как другу: тёпло, просто, с эмодзи, без заумных слов.",
            "expert": "Пиши как эксперт: факты, цифры, технические детали, профессиональный тон.",
            "humorous": "Пиши с юмором: шутки, ирония, забавные ситуации, лёгкий тон.",
        }
        tone_desc = tone_prompts.get(tone, tone_prompts["friendly"])

        system_prompt = (
            "Ты — блогер и эксперт по товарам с AliExpress. "
            "Пишешь увлекательные статьи для блога smart-skidka.ru. "
            "Статьи читаются как рассказы, а не рекламу. Верни результат в JSON."
        )

        user_prompt = f"""Создай блог-статью о товаре: "{title}"

Категория: {category}
Цена со скидкой: {price}₽ (было {original}₽, скидка {discount}%)

Характеристики:
{features_str}

Угол статьи: {angle_desc}

Тон: {tone_desc}

Требования:
1. Заголовок: цепляющий, 50-90 символов, с цифрой или вопросом
2. Подзаголовок: 1-2 предложения, раскрывает тему
3. Введение: 200-400 символов — личная история или интригующий факт
4. Разделы: 3-5 шт., каждый с заголовком и текстом (300-800 символов):
   - "Как я открыл для себя..." (история открытия)
   - "{angle} в деталях" (основная часть)
   - "Лайфхаки и хитрости" (советы)
   - "Стоит ли покупать?" (выводы)
   - "Где купить дешевле" (упоминание smart-skidka.ru)
5. Заключение: 150-300 символов, CTA — перейти на smart-skidka.ru
6. Теги: 5-8 релевантных тегов
7. Reading_time_min: оценочное время чтения
8. Product_mentions: список упомянутых товаров
9. Cta_text: короткий призыв к действию (1-2 предложения)
10. Featured_image_prompt: описание для генерации картинки к статье

Формат (JSON):
{{
    "title": "...",
    "subtitle": "...",
    "introduction": "...",
    "sections": [
        {{"heading": "...", "body": "..."}},
        {{"heading": "...", "body": "..."}}
    ],
    "conclusion": "...",
    "tags": ["..."],
    "reading_time_min": 5,
    "product_mentions": ["..."],
    "cta_text": "...",
    "featured_image_prompt": "..."
}}"""

        logger.info("Генерация блог-статьи", product=title, angle=angle, tone=tone)
        llm_result = await self._call_llm(system_prompt, user_prompt, temperature=0.8, max_tokens=4096)

        if llm_result.get("error"):
            return self._fallback_blog_article(product, angle)

        parsed = self._parse_json_response(llm_result["content"])

        if parsed.get("parse_error"):
            return self._fallback_blog_article(product, angle)

        # Расчёт времени чтения
        content_text = " ".join(
            s.get("body", "") for s in parsed.get("sections", [])
        )
        word_count = len(content_text.split())
        parsed["reading_time_min"] = max(1, round(word_count / 200))

        parsed["_metadata"] = {
            "generated_at": datetime.now().isoformat(),
            "product": title,
            "category": category,
            "angle": angle,
            "tone": tone,
            "llm_model": self.model,
            "elapsed_ms": llm_result.get("elapsed_ms", 0),
            "word_count": word_count,
            "content_type": "blog_article",
        }

        return parsed

    def _fallback_blog_article(
        self,
        product: Dict[str, Any],
        angle: str = "story",
    ) -> Dict[str, Any]:
        """Создаёт базовую блог-статью при ошибке LLM."""
        title = product.get("title", "Товар")
        category = product.get("category", "")
        return {
            "title": f"Как я купил {title} и не пожалел",
            "subtitle": f"Личный опыт использования {title} из категории {category}",
            "introduction": f"Всем привет! Сегодня расскажу о {title} — товаре, который полностью изменил мой подход к {category}. Нашёл его на smart-skidka.ru со скидкой и решил попробовать.",
            "sections": [
                {
                    "heading": "Как я открыл для себя этот товар",
                    "body": f"Искал что-то недорогое и функциональное. {title} привлёк внимание отзывами и ценой. Заказал через smart-skidka.ru — доставка быстрая, упаковка надёжная.",
                },
                {
                    "heading": "Первые впечатления",
                    "body": f"Качество материалов приятно удивило. {title} оказался удобнее, чем ожидал. Использую каждый день уже месяц — нареканий нет.",
                },
                {
                    "heading": "Лайфхаки и хитрости",
                    "body": "Совет №1: читайте инструкцию — там есть полезные функции. Совет №2: следите за акциями на smart-skidka.ru, цены меняются. Совет №3: сравнивайте аналоги перед покупкой.",
                },
                {
                    "heading": "Стоит ли покупать?",
                    "body": f"Однозначно да. {title} — отличное соотношение цены и качества. Особенно со скидкой на smart-skidka.ru.",
                },
            ],
            "conclusion": f"Если ищете {category} — рекомендую {title}. Проверено лично. Скидки и актуальные цены всегда на smart-skidka.ru.",
            "tags": [category, "обзор", "aliexpress", "скидки", "лайфхаки"],
            "reading_time_min": 3,
            "product_mentions": [title],
            "cta_text": f"Хотите такой же {title}? Смотрите лучшие цены на smart-skidka.ru!",
            "featured_image_prompt": f"Фото {title} в интерьере, тёплое освещение, уютная атмосфера",
            "_metadata": {
                "generated_at": datetime.now().isoformat(),
                "product": title,
                "category": category,
                "angle": angle,
                "content_type": "blog_article",
                "fallback": True,
            },
        }

    def _fallback_guide(
        self,
        topic: str,
        steps: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Создаёт базовый гайд при ошибке LLM."""
        default_steps = [
            {
                "title": "Определите свои потребности",
                "description": "Подумайте, что именно вам нужно и какой бюджет вы готовы выделить.",
            },
            {
                "title": "Изучите рынок",
                "description": "Посмотрите актуальные предложения на smart-skidka.ru и сравните цены.",
            },
            {
                "title": "Сравните характеристики",
                "description": "Обратите внимание на ключевые параметры и отзывы покупателей.",
            },
            {
                "title": "Выберите лучшее предложение",
                "description": "Используйте фильтры и сортировку для поиска оптимального варианта.",
            },
            {
                "title": "Оформите покупку со скидкой",
                "description": "Не забудьте применить промокод или перейти по специальной ссылке.",
            },
        ]

        return {
            "title": f"Как выбрать {topic}: полное руководство",
            "introduction": (
                f"В этом гайде мы подробно расскажем, как выбрать {topic}. "
                f"Следуйте нашим рекомендациям, чтобы найти лучшее предложение "
                f"и сэкономить на покупке."
            ),
            "steps": (steps if steps else [s["title"] + ": " + s["description"] for s in default_steps]),
            "conclusion": (
                f"Теперь вы знаете, как выбрать {topic}. "
                f"Используйте smart-skidka.ru для поиска лучших скидок и выгодных предложений."
            ),
            "tags": [topic, "гайд", "советы", "скидки", "покупки"],
            "reading_time_min": 5,
            "_metadata": {
                "generated_at": datetime.now().isoformat(),
                "fallback": True,
                "content_type": "guide",
            },
        }

    # ─── Batch-генерация ──────────────────────────────────────────────────────

    async def batch_generate(
        self,
        count: int,
        content_type: str,
        params: Optional[Dict[str, Any]] = None,
        max_concurrency: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Генерирует несколько единиц контента параллельно.

        Args:
            count: Количество единиц контента
            content_type: Тип контента:
                - "seo_page" — SEO-страницы
                - "product_description" — Описания товаров
                - "comparison" — Сравнения
                - "guide" — Гайды
            params: Параметры для генерации (зависят от типа)
            max_concurrency: Максимальное число параллельных задач

        Returns:
            Список сгенерированных единиц контента
        """
        params = params or {}
        logger.info(
            "Batch-генерация",
            count=count,
            content_type=content_type,
        )

        # Создаём семафор для ограничения concurrency
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _generate_one(index: int) -> Dict[str, Any]:
            async with semaphore:
                try:
                    if content_type == "seo_page":
                        categories = params.get("categories", [])
                        keywords = params.get("keywords", [])
                        category = categories[index % len(categories)] if categories else f"Категория {index + 1}"
                        kw = keywords[index % len(keywords)] if keywords else [category.lower()]
                        return await self.generate_seo_page(category, kw)

                    elif content_type == "product_description":
                        products = params.get("products", [])
                        if products:
                            product = products[index % len(products)]
                        else:
                            product = {
                                "name": f"Товар {index + 1}",
                                "brand": "Популярный бренд",
                                "category": "Электроника",
                                "specs": {"экран": '6.1"', "память": "128 ГБ"},
                                "price": "29 990 ₽",
                                "discount": "15%",
                            }
                        return await self.generate_product_description(product)

                    elif content_type == "comparison":
                        products = params.get("products", [])
                        if len(products) >= 2:
                            a = products[index * 2 % len(products)]
                            b = products[(index * 2 + 1) % len(products)]
                        else:
                            a = {
                                "name": f"Товар A-{index + 1}",
                                "specs": {},
                                "price": "20 000 ₽",
                            }
                            b = {
                                "name": f"Товар B-{index + 1}",
                                "specs": {},
                                "price": "25 000 ₽",
                            }
                        return await self.generate_comparison(a, b)

                    elif content_type == "guide":
                        topics = params.get("topics", [])
                        topic = topics[index % len(topics)] if topics else f"Тема {index + 1}"
                        return await self.generate_guide(topic)

                    elif content_type == "blog_article":
                        products = params.get("products", [])
                        product = products[index % len(products)] if products else {"title": f"Товар {index + 1}"}
                        angle = params.get("angle", "story")
                        tone = params.get("tone", "friendly")
                        return await self.generate_blog_article(product, angle=angle, tone=tone)

                    else:
                        return {
                            "error": f"Неизвестный тип контента: {content_type}",
                            "_metadata": {"content_type": content_type, "index": index},
                        }

                except Exception as e:
                    logger.error("Ошибка batch-генерации", index=index, error=str(e))
                    return {
                        "error": str(e),
                        "_metadata": {"content_type": content_type, "index": index},
                    }

        # Запускаем все задачи
        tasks = [_generate_one(i) for i in range(count)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Обрабатываем результаты
        final_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    {
                        "error": str(result),
                        "_metadata": {"content_type": content_type, "index": i},
                    }
                )
            else:
                final_results.append(result)

        logger.info(
            "Batch-генерация завершена",
            requested=count,
            successful=sum(1 for r in final_results if not r.get("error")),
            failed=sum(1 for r in final_results if r.get("error")),
        )

        return final_results

    # ─── Вспомогательные методы ───────────────────────────────────────────────

    async def generate_meta_tags(
        self,
        content: str,
        max_keywords: int = 10,
    ) -> Dict[str, Any]:
        """
        Генерирует мета-теги для существующего контента.

        Args:
            content: Исходный контент
            max_keywords: Максимальное количество ключевых слов

        Returns:
            Словарь с title, meta_description, keywords
        """
        system_prompt = "Ты — SEO-эксперт. Создай мета-теги для данного контента. " "Верни результат в JSON."

        content_preview = content[:2000] if len(content) > 2000 else content

        user_prompt = f"""Создай мета-теги для следующего контента:

{content_preview}

Требования:
1. Title: 50-60 символов
2. Meta description: 150-160 символов
3. Keywords: до {max_keywords} ключевых слов

Формат (JSON):
{{
    "title": "...",
    "meta_description": "...",
    "keywords": ["..."]
}}"""

        llm_result = await self._call_llm(system_prompt, user_prompt, temperature=0.5)

        if llm_result.get("error"):
            # Простой fallback
            words = content.split()[:10]
            title_text = " ".join(words)
            return {
                "title": (title_text[:60] if len(title_text) > 60 else title_text + " — smart-skidka.ru"),
                "meta_description": content[:160],
                "keywords": [],
            }

        return self._parse_json_response(llm_result["content"])

    async def rewrite_for_platform(
        self,
        content: str,
        platform: str,
    ) -> Dict[str, Any]:
        """
        Переписывает контент для конкретной платформы.

        Args:
            content: Исходный контент
            platform: Целевая платформа (twitter, instagram, vk, telegram)

        Returns:
            Адаптированный контент
        """
        limits = {
            "twitter": 280,
            "instagram": 2200,
            "vk": 10000,
            "telegram": 4096,
        }
        limit = limits.get(platform, 2000)

        system_prompt = (
            f"Ты — SMM-эксперт. Адаптируй контент для публикации в {platform}. "
            f"Лимит: {limit} символов. Верни результат в JSON."
        )

        user_prompt = f"""Адаптируй следующий контент для {platform} (макс. {limit} символов):

{content[:1500]}

Требования:
1. Сохрани ключевую мысль
2. Добавь хештеги (3-10 штук)
3. Добавь CTA
4. Уложись в {limit} символов

Формат (JSON):
{{
    "text": "...",
    "hashtags": ["#..."],
    "cta": "...",
    "character_count": 0
}}"""

        llm_result = await self._call_llm(system_prompt, user_prompt, temperature=0.8)
        return self._parse_json_response(llm_result["content"])

    # ─── Закрытие ─────────────────────────────────────────────────────────────

    async def close(self) -> None:
        """Закрывает HTTP-сессию."""
        if self._session and not self._session.closed:
            await self._session.close()
            logger.info("ContentGenerator сессия закрыта")


# ═══════════════════════════════════════════════════════════════════════════════
# Удобные функции-обёртки
# ═══════════════════════════════════════════════════════════════════════════════
async def generate_seo_page(category: str, keywords: List[str]) -> Dict[str, Any]:
    """
    Генерирует SEO-страницу (функция-обёртка).

    Args:
        category: Название категории
        keywords: Ключевые слова

    Returns:
        Словарь с SEO-элементами
    """
    gen = ContentGenerator()
    try:
        return await gen.generate_seo_page(category, keywords)
    finally:
        await gen.close()


async def generate_product_description(product: Dict[str, Any]) -> Dict[str, Any]:
    """
    Генерирует описание товара (функция-обёртка).

    Args:
        product: Информация о товаре

    Returns:
        Словарь с описанием
    """
    gen = ContentGenerator()
    try:
        return await gen.generate_product_description(product)
    finally:
        await gen.close()


async def generate_comparison(
    product_a: Dict[str, Any],
    product_b: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Генерирует сравнение товаров (функция-обёртка).

    Args:
        product_a: Первый товар
        product_b: Второй товар

    Returns:
        Словарь со сравнением
    """
    gen = ContentGenerator()
    try:
        return await gen.generate_comparison(product_a, product_b)
    finally:
        await gen.close()


async def generate_guide(topic: str, steps: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Генерирует гайд (функция-обёртка).

    Args:
        topic: Тема гайда
        steps: Опциональные шаги

    Returns:
        Словарь с гайдом
    """
    gen = ContentGenerator()
    try:
        return await gen.generate_guide(topic, steps)
    finally:
        await gen.close()


async def generate_blog_article(
    product: Dict[str, Any],
    angle: str = "story",
    tone: str = "friendly",
) -> Dict[str, Any]:
    """
    Генерирует блог-статью о товаре (функция-обёртка).

    Args:
        product: Данные о товаре
        angle: Угол статьи — "story", "review", "howto", "comparison"
        tone: Тон — "friendly", "expert", "humorous"

    Returns:
        Словарь с блог-статьёй
    """
    gen = ContentGenerator()
    try:
        return await gen.generate_blog_article(product, angle=angle, tone=tone)
    finally:
        await gen.close()


async def batch_generate(
    count: int,
    content_type: str,
    params: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Batch-генерация контента (функция-обёртка).

    Args:
        count: Количество
        content_type: Тип контента
        params: Параметры

    Returns:
        Список результатов
    """
    gen = ContentGenerator()
    try:
        return await gen.batch_generate(count, content_type, params)
    finally:
        await gen.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Точка входа для тестирования
# ═══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":

    async def test():
        """Тестирование генератора контента."""
        gen = ContentGenerator()

        print("=" * 60)
        print("ТЕСТ ContentGenerator")
        print("=" * 60)

        # Тест SEO-страницы
        print("\n1. Генерация SEO-страницы...")
        seo = await gen.generate_seo_page(
            category="Смартфоны",
            keywords=[
                "смартфоны со скидкой",
                "купить смартфон дешево",
                "лучшие смартфоны 2024",
            ],
        )
        print(f"   Title: {seo.get('title', 'N/A')[:60]}...")
        print(f"   Meta: {seo.get('meta_description', 'N/A')[:80]}...")
        print(f"   H1: {seo.get('h1', 'N/A')}")

        # Тест описания товара
        print("\n2. Генерация описания товара...")
        product = {
            "name": "iPhone 15 Pro 128GB",
            "brand": "Apple",
            "category": "Смартфоны",
            "specs": {
                "экран": '6.1" OLED',
                "процессор": "A17 Pro",
                "память": "128 ГБ",
                "камера": "48 МП",
                "батарея": "3274 мАч",
            },
            "price": "89 990 ₽",
            "discount": "20%",
        }
        desc = await gen.generate_product_description(product)
        print(f"   Title: {desc.get('title', 'N/A')}")
        print(f"   Features: {len(desc.get('features', []))} пунктов")
        print(f"   Pros: {len(desc.get('pros', []))} пунктов")

        # Тест сравнения
        print("\n3. Генерация сравнения...")
        product_a = {
            "name": "Samsung Galaxy S24",
            "specs": {
                "экран": '6.2"',
                "процессор": "Snapdragon 8 Gen 3",
                "память": "256 ГБ",
            },
            "price": "74 990 ₽",
        }
        product_b = {
            "name": "iPhone 15",
            "specs": {"экран": '6.1"', "процессор": "A16 Bionic", "память": "128 ГБ"},
            "price": "79 990 ₽",
        }
        comp = await gen.generate_comparison(product_a, product_b)
        print(f"   Title: {comp.get('title', 'N/A')}")
        print(f"   Winner: {comp.get('winner', 'N/A')}")
        print(f"   Table keys: {list(comp.get('comparison_table', {}).keys())}")

        # Тест гайда
        print("\n4. Генерация гайда...")
        guide = await gen.generate_guide(
            topic="как выбрать первый смартфон для ребёнка",
            target_audience="parents",
        )
        print(f"   Title: {guide.get('title', 'N/A')}")
        print(f"   Steps: {len(guide.get('steps', []))}")
        print(f"   Reading time: {guide.get('reading_time_min', 'N/A')} min")

        # Тест batch
        print("\n5. Batch-генерация (2 SEO + 2 описания)...")
        batch_seo = await gen.batch_generate(
            count=2,
            content_type="seo_page",
            params={
                "categories": ["Ноутбуки", "Наушники"],
                "keywords": [["ноутбуки со скидкой"], ["наушники беспроводные"]],
            },
        )
        print(f"   Сгенерировано SEO-страниц: {len(batch_seo)}")
        for i, item in enumerate(batch_seo):
            title = item.get("title", "ERROR")[:50]
            print(f"   [{i + 1}] {title}...")

        await gen.close()
        print("\n✅ Тестирование завершено!")

    print("Запуск тестов ContentGenerator...")
    print("Убедитесь, что LLM_API_KEY задан в .env для полной функциональности")
    print("(Fallback-шаблоны будут использованы при отсутствии API ключа)")
    print()
    asyncio.run(test())
