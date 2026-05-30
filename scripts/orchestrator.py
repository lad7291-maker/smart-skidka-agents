#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                   ORCHESTRATOR — Multi-Agent System                  ║
║                         smart-skidka.ru                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  Главный модуль оркестратора для координации AI-агентов маркетинга   ║
║  агрегатора скидок. Управляет запуском, валидацией, хранением      ║
║  результатов и отправкой отчётов.                                    ║
╚══════════════════════════════════════════════════════════════════════╝

Архитектура:
    - AgentConfig      : Загрузка конфигурации агента из JSON
    - AgentRunner      : Запуск агента через LLM API
    - ResultValidator  : Валидация результатов работы агентов
    - Orchestrator     : Главный оркестратор — координирует всех агентов
    - LLMClient        : Клиент для LLM API (RouterAI/DeepSeek)
    - MemoryStore      : Хранение памяти агентов (PostgreSQL + Redis)
    - TelegramReporter : Отправка отчётов в Telegram

Пример использования:
    >>> orchestrator = Orchestrator(
    ...     config_path="./configs",
    ...     db_url="postgresql://user:pass@localhost/agents",
    ...     redis_url="redis://localhost:6379"
    ... )
    >>> await orchestrator.run()  # Запуск бесконечного цикла
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiohttp
import redis.asyncio as aioredis
import asyncpg
import structlog
from dotenv import load_dotenv

# ═══════════════════════════════════════════════════════════════════════════════
# Actions — реальные операции агентов с файлами проекта
# ═══════════════════════════════════════════════════════════════════════════════
from actions.telegram_actions import post_discount, post_to_channel
from actions.site_actions import (
    add_badge,
    create_category_page,
    prioritize_products,
    update_item_description,
    update_meta_tags,
    update_product_field,
)

# ═══════════════════════════════════════════════════════════════════════════════
# Загрузка переменных окружения
# ═══════════════════════════════════════════════════════════════════════════════
load_dotenv()

# ═══════════════════════════════════════════════════════════════════════════════
# Настройка логирования через structlog
# ═══════════════════════════════════════════════════════════════════════════════
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.processors.JSONRenderer(),
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger("orchestrator")


# ═══════════════════════════════════════════════════════════════════════════════
# Перечисления и константы
# ═══════════════════════════════════════════════════════════════════════════════
class AgentType(str, Enum):
    """Типы агентов в системе."""
    SEO = "seo"
    SMM = "smm"
    PERFORMANCE = "performance"
    EMAIL = "email"
    ANALYTICS = "analytics"
    CONTENT = "content"
    TREND = "trend"


class ValidationStatus(str, Enum):
    """Статусы валидации результата."""
    PASSED = "passed"
    FAILED = "failed"
    WARNING = "warning"
    SKIPPED = "skipped"


# Значения по умолчанию для retry-логики
DEFAULT_MAX_RETRIES: int = 3
DEFAULT_RETRY_DELAY: float = 2.0  # секунды
RETRY_BACKOFF_MULTIPLIER: float = 2.0

# Значения по умолчанию для цикла оркестратора
DEFAULT_CYCLE_INTERVAL: int = 300  # 5 минут между циклами

# Список имён агентов в системе
AGENT_NAMES: List[str] = [
    "seo_agent",
    "smm_agent",
    "performance_agent",
    "email_agent",
    "analytics_agent",
    "content_agent",
    "trend_agent",
]


# ═══════════════════════════════════════════════════════════════════════════════
# Data-классы
# ═══════════════════════════════════════════════════════════════════════════════
@dataclass
class ValidationResult:
    """
    Результат валидации агента.

    Attributes:
        status: Статус валидации (passed/failed/warning)
        score: Оценка качества от 0.0 до 1.0
        errors: Список ошибок, если валидация не пройдена
        warnings: Список предупреждений
        metadata: Дополнительные метаданные валидации
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


@dataclass
class AgentResult:
    """
    Результат выполнения агента.

    Attributes:
        agent_name: Имя агента
        agent_type: Тип агента
        cycle_id: ID цикла оркестратора
        timestamp: Время выполнения
        data: Данные результата
        metrics: Метрики выполнения
        validation: Результат валидации
        execution_time_ms: Время выполнения в миллисекундах
    """
    agent_name: str
    agent_type: str
    cycle_id: str
    timestamp: datetime
    data: Dict[str, Any]
    metrics: Dict[str, Any] = field(default_factory=dict)
    validation: Optional[ValidationResult] = None
    execution_time_ms: float = 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# AgentConfig — Загрузка конфигурации агента
# ═══════════════════════════════════════════════════════════════════════════════
class AgentConfig:
    """
    Загрузка и управление конфигурацией агента из JSON-файла.

    Каждый агент имеет свой конфигурационный файл в формате JSON,
    содержащий системный промпт, расписание, правила валидации
    и другие параметры.

    Example:
        >>> config = AgentConfig("seo-agent", "./configs")
        >>> prompt = config.get_system_prompt()
        >>> schedule = config.get_schedule()
    """

    def __init__(self, agent_name: str, config_path: str) -> None:
        """
        Инициализация конфигурации агента.

        Args:
            agent_name: Имя агента (имя JSON-файла без расширения)
            config_path: Путь к директории с конфигурациями
        """
        self.agent_name: str = agent_name
        self.config_path: Path = Path(config_path)
        self._config: Dict[str, Any] = {}
        self._loaded: bool = False
        self.logger = structlog.get_logger("agent_config").bind(agent=agent_name)

    def _get_config_file(self) -> Path:
        """Возвращает путь к файлу конфигурации агента."""
        return self.config_path / f"{self.agent_name}.json"

    def load_config(self) -> Dict[str, Any]:
        """
        Загружает конфигурацию агента из JSON-файла.

        Returns:
            Словарь с конфигурацией агента

        Raises:
            FileNotFoundError: Если файл конфигурации не найден
            json.JSONDecodeError: Если файл содержит невалидный JSON
        """
        config_file = self._get_config_file()
        self.logger.info("Загрузка конфигурации", config_file=str(config_file))

        if not config_file.exists():
            self.logger.error("Файл конфигурации не найден", config_file=str(config_file))
            raise FileNotFoundError(f"Конфигурация агента не найдена: {config_file}")

        try:
            with open(config_file, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            self._loaded = True
            self.logger.info(
                "Конфигурация загружена успешно",
                version=self._config.get("version", "unknown"),
            )
            return self._config
        except json.JSONDecodeError as e:
            self.logger.error("Ошибка парсинга JSON", error=str(e))
            raise

    def get_system_prompt(self) -> str:
        """
        Возвращает системный промпт для LLM.

        Returns:
            Системный промпт агента

        Raises:
            KeyError: Если системный промпт не найден в конфигурации
        """
        if not self._loaded:
            self.load_config()

        prompt = self._config.get("system_prompt", "")
        if not prompt:
            self.logger.warning("Системный промпт не задан, используется пустой")
        return prompt

    def get_schedule(self) -> Dict[str, Any]:
        """
        Возвращает расписание запуска агента.

        Returns:
            Словарь с параметрами расписания:
                - interval: интервал в секундах
                - cron: cron-выражение (опционально)
                - enabled: включён ли агент
        """
        if not self._loaded:
            self.load_config()

        default_schedule = {
            "interval": DEFAULT_CYCLE_INTERVAL,
            "enabled": True,
            "run_once": False,
        }
        return self._config.get("schedule", default_schedule)

    def get_validation_rules(self) -> Dict[str, Any]:
        """
        Возвращает правила валидации для результатов агента.

        Returns:
            Словарь с правилами валидации:
                - required_fields: обязательные поля в результате
                - min_score: минимальная оценка качества
                - max_execution_time: максимальное время выполнения
        """
        if not self._loaded:
            self.load_config()

        return self._config.get("validation_rules", {})

    def get_llm_settings(self) -> Dict[str, Any]:
        """
        Возвращает настройки LLM для агента.

        Returns:
            Словарь с настройками:
                - model: название модели
                - temperature: температура генерации
                - max_tokens: максимальное количество токенов
        """
        if not self._loaded:
            self.load_config()

        defaults = {
            "model": os.getenv("DEFAULT_LLM_MODEL", "deepseek/deepseek-chat-v3.1"),
            "temperature": 0.7,
            "max_tokens": 4096,
        }
        return self._config.get("llm_settings", defaults)

    def is_enabled(self) -> bool:
        """Проверяет, включён ли агент в расписании."""
        return self.get_schedule().get("enabled", True)

    def __repr__(self) -> str:
        return f"AgentConfig(name={self.agent_name}, loaded={self._loaded})"


# ═══════════════════════════════════════════════════════════════════════════════
# LLMClient — Клиент для LLM API
# ═══════════════════════════════════════════════════════════════════════════════
class LLMClient:
    """
    Асинхронный клиент для взаимодействия с LLM API.

    Поддерживает RouterAI и DeepSeek API. Реализует retry-логику
    с экспоненциальным backoff и обработку ошибок.

    Example:
        >>> client = LLMClient(api_key="sk-...", model="deepseek/deepseek-chat-v3.1")
        >>> result = await client.generate(
        ...     system_prompt="Ты SEO-эксперт...",
        ...     user_prompt="Создай мета-теги для..."
        ... )
    """

    # Поддерживаемые API endpoints
    ROUTERAI_URL: str = "https://api.rrouter.ai/v1/chat/completions"
    DEEPSEEK_URL: str = "https://api.deepseek.com/v1/chat/completions"

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "deepseek/deepseek-chat-v3.1",
        base_url: Optional[str] = None,
        timeout: float = 120.0,
    ) -> None:
        """
        Инициализация клиента LLM.

        Args:
            api_key: API ключ (если None, берётся из переменной окружения LLM_API_KEY)
            model: Название модели для генерации
            base_url: Базовый URL API (если None, определяется автоматически)
            timeout: Таймаут запроса в секундах
        """
        self.api_key: str = api_key or os.getenv("LLM_API_KEY", "")
        if not self.api_key:
            raise ValueError(
                "API ключ не задан. Укажите LLM_API_KEY в .env или передайте в конструктор."
            )

        self.model: str = model
        self.timeout: aiohttp.ClientTimeout = aiohttp.ClientTimeout(total=timeout)
        self.logger = structlog.get_logger("llm_client").bind(model=model)

        # Определение base_url
        if base_url:
            self.base_url = base_url
        elif "rrouter" in self.model or "anthropic" in self.model:
            self.base_url = self.ROUTERAI_URL
        else:
            self.base_url = os.getenv("LLM_BASE_URL", self.DEEPSEEK_URL)

        # Сессия будет создана при первом использовании
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore: asyncio.Semaphore = asyncio.Semaphore(5)  # Ограничение параллельных запросов

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получает или создаёт aiohttp-сессию."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._session

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Генерирует ответ от LLM.

        Args:
            system_prompt: Системный промпт
            user_prompt: Пользовательский запрос
            tools: Опциональный список инструментов для function calling
            temperature: Температура генерации (переопределяет настройки)
            max_tokens: Максимальное количество токенов

        Returns:
            Словарь с результатом генерации:
                - content: текстовый ответ
                - usage: информация об использовании токенов
                - model: использованная модель

        Raises:
            aiohttp.ClientError: При ошибках HTTP
            asyncio.TimeoutError: При превышении таймаута
        """
        async with self._semaphore:
            session = await self._get_session()

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]

            payload: Dict[str, Any] = {
                "model": self.model,
                "messages": messages,
            }

            if temperature is not None:
                payload["temperature"] = temperature
            if max_tokens is not None:
                payload["max_tokens"] = max_tokens
            if tools:
                payload["tools"] = tools
                payload["tool_choice"] = "auto"

            self.logger.info(
                "Отправка запроса к LLM",
                model=self.model,
                has_tools=bool(tools),
                prompt_length=len(user_prompt),
            )

            start_time = time.monotonic()

            try:
                async with session.post(self.base_url, json=payload) as response:
                    response.raise_for_status()
                    result = await response.json()

                    elapsed_ms = (time.monotonic() - start_time) * 1000

                    # Извлечение контента из ответа
                    content = ""
                    if "choices" in result and result["choices"]:
                        choice = result["choices"][0]
                        message = choice.get("message", {})

                        # Проверка на tool_calls
                        if "tool_calls" in message and message["tool_calls"]:
                            content = json.dumps({
                                "tool_calls": message["tool_calls"]
                            }, ensure_ascii=False)
                        else:
                            content = message.get("content", "")

                    usage = result.get("usage", {})

                    self.logger.info(
                        "Ответ получен от LLM",
                        elapsed_ms=round(elapsed_ms, 2),
                        prompt_tokens=usage.get("prompt_tokens", 0),
                        completion_tokens=usage.get("completion_tokens", 0),
                    )

                    return {
                        "content": content,
                        "usage": usage,
                        "model": result.get("model", self.model),
                        "elapsed_ms": round(elapsed_ms, 2),
                    }

            except aiohttp.ClientResponseError as e:
                self.logger.error(
                    "HTTP ошибка от LLM API",
                    status=e.status,
                    message=str(e.message),
                )
                raise
            except asyncio.TimeoutError:
                self.logger.error("Таймаут запроса к LLM API")
                raise
            except Exception as e:
                self.logger.error("Неожиданная ошибка при запросе к LLM", error=str(e))
                raise

    async def generate_with_tools(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: List[Dict[str, Any]],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Генерирует ответ от LLM с использованием инструментов (function calling).

        Args:
            system_prompt: Системный промпт
            user_prompt: Пользовательский запрос
            tools: Список доступных инструментов
            temperature: Температура генерации
            max_tokens: Максимальное количество токенов

        Returns:
            Словарь с результатом, включая tool_calls если модель их вызвала
        """
        return await self.generate(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            tools=tools,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    async def close(self) -> None:
        """Закрывает HTTP-сессию."""
        if self._session and not self._session.closed:
            await self._session.close()
            self.logger.info("LLM сессия закрыта")

    async def __aenter__(self) -> LLMClient:
        """Асинхронный контекстный менеджер — вход."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Асинхронный контекстный менеджер — выход."""
        await self.close()


# ═══════════════════════════════════════════════════════════════════════════════
# ResultValidator — Валидация результатов работы агентов
# ═══════════════════════════════════════════════════════════════════════════════
class ResultValidator:
    """
    Валидатор результатов работы агентов.

    Проверяет соответствие результатов заданным правилам валидации.
    Каждый тип агента имеет свои специфические проверки.

    Example:
        >>> validator = ResultValidator(rules={"min_score": 0.7})
        >>> result = validator.validate(data, AgentType.SEO)
        >>> if result.is_valid:
        ...     print("Валидация пройдена")
    """

    def __init__(self, rules: Dict[str, Any]) -> None:
        """
        Инициализация валидатора.

        Args:
            rules: Словарь с правилами валидации
        """
        self.rules: Dict[str, Any] = rules
        self.logger = structlog.get_logger("validator")

    def validate(self, result: Dict[str, Any], agent_type: str) -> ValidationResult:
        """
        Валидирует результат агента в зависимости от его типа.

        Args:
            result: Результат работы агента
            agent_type: Тип агента (seo, smm, performance, email, analytics, content)

        Returns:
            ValidationResult с результатом проверки
        """
        self.logger.info("Начало валидации", agent_type=agent_type)

        if not result:
            return ValidationResult(
                status=ValidationStatus.FAILED,
                errors=["Результат пустой"],
                score=0.0,
            )

        # Определяем метод валидации по типу агента
        validation_methods = {
            AgentType.SEO.value: self.validate_seo,
            AgentType.SMM.value: self.validate_smm,
            AgentType.PERFORMANCE.value: self.validate_performance,
            AgentType.EMAIL.value: self.validate_email,
            AgentType.ANALYTICS.value: self.validate_analytics,
            AgentType.CONTENT.value: self.validate_content,
            AgentType.TREND.value: self.validate_trend,
        }

        validator = validation_methods.get(agent_type)
        if not validator:
            self.logger.warning(
                "Неизвестный тип агента, пропуск валидации",
                agent_type=agent_type,
            )
            return ValidationResult(
                status=ValidationStatus.SKIPPED,
                score=0.0,
                warnings=[f"Неизвестный тип агента: {agent_type}"],
            )

        try:
            return validator(result)
        except Exception as e:
            self.logger.error("Ошибка при валидации", error=str(e))
            return ValidationResult(
                status=ValidationStatus.FAILED,
                errors=[f"Ошибка валидации: {str(e)}"],
                score=0.0,
            )

    def validate_seo(self, result: Dict[str, Any]) -> ValidationResult:
        """
        Валидирует результат SEO-агента.

        Проверяет наличие обязательных полей:
        - title, meta_description, keywords, h1
        - Длина title (30-60 символов)
        - Длина meta_description (120-160 символов)
        - Уникальность ключевых слов

        Args:
            result: Результат работы SEO-агента

        Returns:
            ValidationResult с результатом проверки
        """
        errors: List[str] = []
        warnings: List[str] = []
        score: float = 1.0

        required_fields = self.rules.get("required_fields", ["title", "meta_description", "keywords", "h1"])

        # Проверка обязательных полей
        for field in required_fields:
            if field not in result or not result[field]:
                errors.append(f"Отсутствует обязательное поле: {field}")
                score -= 0.2

        # Проверка длины title
        title = result.get("title", "")
        if title:
            if len(title) < 30:
                warnings.append(f"Title слишком короткий ({len(title)} симв., мин. 30)")
                score -= 0.1
            elif len(title) > 60:
                warnings.append(f"Title слишком длинный ({len(title)} симв., макс. 60)")
                score -= 0.1

        # Проверка длины meta_description
        meta = result.get("meta_description", "")
        if meta:
            if len(meta) < 120:
                warnings.append(f"Meta description слишком короткий ({len(meta)} симв.)")
                score -= 0.1
            elif len(meta) > 160:
                warnings.append(f"Meta description слишком длинный ({len(meta)} симв.)")
                score -= 0.1

        # Проверка ключевых слов
        keywords = result.get("keywords", [])
        if isinstance(keywords, list) and len(keywords) < 3:
            warnings.append(f"Мало ключевых слов ({len(keywords)}, рекомендуется 5-10)")
            score -= 0.1

        # Проверка наличия H1
        h1 = result.get("h1", "")
        if h1 and len(h1) < 10:
            warnings.append("H1 слишком короткий")
            score -= 0.05

        final_score = max(0.0, score)
        status = ValidationStatus.PASSED if not errors and final_score >= 0.7 else ValidationStatus.FAILED
        if warnings and not errors and final_score >= 0.7:
            status = ValidationStatus.WARNING

        return ValidationResult(
            status=status,
            score=final_score,
            errors=errors,
            warnings=warnings,
        )

    def validate_smm(self, result: Dict[str, Any]) -> ValidationResult:
        """
        Валидирует результат SMM-агента.

        Проверяет:
        - Наличие текста поста, хештегов, изображения
        - Длину поста для разных платформ
        - Количество хештегов (1-30 для Instagram)

        Args:
            result: Результат работы SMM-агента

        Returns:
            ValidationResult с результатом проверки
        """
        errors: List[str] = []
        warnings: List[str] = []
        score: float = 1.0

        # Проверка обязательных полей
        if "text" not in result or not result["text"]:
            errors.append("Отсутствует текст поста")
            score -= 0.3

        # Проверка длины поста
        text = result.get("text", "")
        platform = result.get("platform", "general")

        if platform == "twitter" and len(text) > 280:
            errors.append(f"Текст превышает лимит Twitter ({len(text)} > 280)")
            score -= 0.3
        elif platform == "instagram" and len(text) > 2200:
            warnings.append(f"Текст длинный для Instagram ({len(text)} симв.)")
            score -= 0.1

        # Проверка хештегов
        hashtags = result.get("hashtags", [])
        if isinstance(hashtags, list):
            if len(hashtags) > 30:
                warnings.append(f"Слишком много хештегов ({len(hashtags)}, макс. 30)")
                score -= 0.1
            if len(hashtags) == 0:
                warnings.append("Нет хештегов — рекомендуется добавить")
                score -= 0.1

        # Проверка CTA (call-to-action)
        if "cta" not in result:
            warnings.append("Отсутствует призыв к действию (CTA)")
            score -= 0.05

        final_score = max(0.0, score)
        status = ValidationStatus.PASSED if not errors and final_score >= 0.6 else ValidationStatus.FAILED
        if warnings and not errors and final_score >= 0.6:
            status = ValidationStatus.WARNING

        return ValidationResult(
            status=status,
            score=final_score,
            errors=errors,
            warnings=warnings,
        )

    def validate_performance(self, result: Dict[str, Any]) -> ValidationResult:
        """
        Валидирует результат performance-агента (рекламы).

        Проверяет:
        - Наличие заголовков, описаний, ключевых слов
        - Бюджетные ограничения
        - Структуру объявлений

        Args:
            result: Результат работы performance-агента

        Returns:
            ValidationResult с результатом проверки
        """
        errors: List[str] = []
        warnings: List[str] = []
        score: float = 1.0

        # Проверка обязательных полей
        required = ["headlines", "descriptions", "keywords"]
        for field in required:
            if field not in result or not result[field]:
                errors.append(f"Отсутствует обязательное поле: {field}")
                score -= 0.25

        # Проверка заголовков
        headlines = result.get("headlines", [])
        if isinstance(headlines, list):
            if len(headlines) < 3:
                warnings.append(f"Мало заголовков ({len(headlines)}, рекомендуется 5-15)")
                score -= 0.1
            for i, h in enumerate(headlines):
                if len(h) > 30:
                    warnings.append(f"Заголовок {i+1} превышает 30 символов")
                    score -= 0.03

        # Проверка описаний
        descriptions = result.get("descriptions", [])
        if isinstance(descriptions, list) and len(descriptions) < 2:
            warnings.append(f"Мало описаний ({len(descriptions)}, рекомендуется 2-4)")
            score -= 0.1

        # Проверка бюджета
        budget = result.get("daily_budget", 0)
        if budget and budget > 100000:
            warnings.append(f"Дневной бюджет высокий ({budget} руб.)")

        final_score = max(0.0, score)
        status = ValidationStatus.PASSED if not errors and final_score >= 0.6 else ValidationStatus.FAILED

        return ValidationResult(
            status=status,
            score=final_score,
            errors=errors,
            warnings=warnings,
        )

    def validate_email(self, result: Dict[str, Any]) -> ValidationResult:
        """
        Валидирует результат email-агента.

        Проверяет:
        - Наличие subject, body, preheader
        - Длину subject (рекомендуется 40-60 символов)
        - Спам-скор
        - Наличие unsubscribe-ссылки

        Args:
            result: Результат работы email-агента

        Returns:
            ValidationResult с результатом проверки
        """
        errors: List[str] = []
        warnings: List[str] = []
        score: float = 1.0

        # Проверка обязательных полей
        if "subject" not in result or not result["subject"]:
            errors.append("Отсутствует тема письма (subject)")
            score -= 0.3

        if "body" not in result or not result["body"]:
            errors.append("Отсутствует тело письма (body)")
            score -= 0.3

        # Проверка длины subject
        subject = result.get("subject", "")
        if subject:
            if len(subject) > 80:
                warnings.append(f"Тема слишком длинная ({len(subject)} симв.)")
                score -= 0.1
            elif len(subject) < 20:
                warnings.append(f"Тема слишком короткая ({len(subject)} симв.)")
                score -= 0.05

        # Проверка на спам-триггеры
        spam_keywords = ["БЕСПЛАТНО", "КУПИТЬ СЕЙЧАС", "ОГРАНИЧЕННОЕ ВРЕМЯ",
                        "$$$", "100% бесплатно", "НЕ УДАЛЯЙТЕ"]
        body_lower = result.get("body", "").upper()
        found_spam = [kw for kw in spam_keywords if kw.upper() in body_lower]
        if found_spam:
            warnings.append(f"Обнаружены спам-триггеры: {found_spam}")
            score -= 0.15 * len(found_spam)

        # Проверка наличия unsubscribe
        body = result.get("body", "")
        if "unsubscribe" not in body.lower() and "отписаться" not in body.lower():
            warnings.append("Отсутствует ссылка для отписки")
            score -= 0.1

        # Проверка preheader
        if "preheader" not in result:
            warnings.append("Отсутствует preheader текст")
            score -= 0.05

        final_score = max(0.0, score)
        status = ValidationStatus.PASSED if not errors and final_score >= 0.6 else ValidationStatus.FAILED

        return ValidationResult(
            status=status,
            score=final_score,
            errors=errors,
            warnings=warnings,
            metadata={"spam_keywords_found": found_spam if found_spam else []},
        )

    def validate_analytics(self, result: Dict[str, Any]) -> ValidationResult:
        """
        Валидирует результат аналитического агента.

        Проверяет:
        - Наличие метрик, дат, источников данных
        - Корректность числовых значений
        - Временной диапазон

        Args:
            result: Результат работы аналитического агента

        Returns:
            ValidationResult с результатом проверки
        """
        errors: List[str] = []
        warnings: List[str] = []
        score: float = 1.0

        # Проверка наличия метрик
        metrics = result.get("metrics", {})
        if not metrics:
            errors.append("Отсутствуют метрики")
            score -= 0.4

        # Проверка даты отчёта
        if "report_date" not in result:
            warnings.append("Отсутствует дата отчёта")
            score -= 0.1

        # Проверка источника данных
        if "data_source" not in result:
            warnings.append("Не указан источник данных")
            score -= 0.05

        # Проверка числовых значений
        if isinstance(metrics, dict):
            for key, value in metrics.items():
                if isinstance(value, (int, float)) and value < 0:
                    warnings.append(f"Отрицательное значение метрики: {key}")
                    score -= 0.05

        # Проверка наличия рекомендаций
        if "recommendations" not in result:
            warnings.append("Отсутствуют рекомендации на основе аналитики")
            score -= 0.1

        final_score = max(0.0, score)
        status = ValidationStatus.PASSED if not errors else ValidationStatus.FAILED

        return ValidationResult(
            status=status,
            score=final_score,
            errors=errors,
            warnings=warnings,
        )

    def validate_content(self, result: Dict[str, Any]) -> ValidationResult:
        """
        Валидирует результат контент-агента.

        Проверяет:
        - Наличие заголовка, текста, тегов
        - Длину контента
        - Уникальность (проверка на дубликаты)
        - Структуру (заголовки, абзацы)

        Args:
            result: Результат работы контент-агента

        Returns:
            ValidationResult с результатом проверки
        """
        errors: List[str] = []
        warnings: List[str] = []
        score: float = 1.0

        # Проверка обязательных полей
        if "title" not in result or not result["title"]:
            errors.append("Отсутствует заголовок")
            score -= 0.25

        if "content" not in result or not result["content"]:
            errors.append("Отсутствует основной текст")
            score -= 0.25

        # Проверка длины контента
        content = result.get("content", "")
        content_type = result.get("content_type", "article")

        min_lengths = {"article": 800, "guide": 1500, "review": 500, "news": 300}
        min_len = min_lengths.get(content_type, 500)

        if len(content) < min_len:
            warnings.append(
                f"Контент слишком короткий ({len(content)} симв., "
                f"мин. для {content_type}: {min_len})"
            )
            score -= 0.15

        # Проверка структуры (наличие заголовков)
        if "<h" not in content and "##" not in content:
            warnings.append("Контент не имеет структурированных заголовков")
            score -= 0.1

        # Проверка тегов
        tags = result.get("tags", [])
        if isinstance(tags, list) and len(tags) < 2:
            warnings.append("Мало тегов для контента")
            score -= 0.05

        # Проверка featured_image
        if "featured_image" not in result:
            warnings.append("Отсутствует изображение для контента")
            score -= 0.05

        final_score = max(0.0, score)
        status = ValidationStatus.PASSED if not errors and final_score >= 0.6 else ValidationStatus.FAILED

        return ValidationResult(
            status=status,
            score=final_score,
            errors=errors,
            warnings=warnings,
        )

    def validate_trend(self, result: Dict[str, Any]) -> ValidationResult:
        """
        Валидирует результат Trend Research Agent.

        Проверяет:
        - Корректность типа тренда и статуса
        - Достоверность (confidence) в диапазоне [0.6, 1.0]
        - Наличие заголовка, описания, метрик, источников данных
        - Корректность рекомендуемых действий (целевой агент известен)
        - Свежесть тренда (не старше 48 часов)

        Args:
            result: Результат работы Trend Research Agent

        Returns:
            ValidationResult с результатом проверки
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
            "not_expired": self._check_trend_freshness(result),
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

    def _check_trend_freshness(self, result: Dict[str, Any]) -> bool:
        """Проверка что тренд не устарел (>48 часов)."""
        detected = result.get("detected_at")
        if not detected:
            return True
        try:
            dt = datetime.fromisoformat(str(detected).replace("Z", "+00:00"))
            return (datetime.now(dt.tzinfo) - dt).total_seconds() < 48 * 3600
        except Exception:
            return True


# ═══════════════════════════════════════════════════════════════════════════════
# AgentRunner — Запуск агента через LLM API
# ═══════════════════════════════════════════════════════════════════════════════
class AgentRunner:
    """
    Исполнитель агента — запускает агента через LLM API.

    Управляет полным циклом выполнения: формирование промпта,
    вызов LLM, парсинг результата, retry при ошибках.

    Example:
        >>> config = AgentConfig("seo-agent", "./configs")
        >>> llm = LLMClient(api_key="sk-...")
        >>> runner = AgentRunner(config, llm)
        >>> result = await runner.run(context={"category": "электроника"})
    """

    def __init__(self, config: AgentConfig, llm_client: LLMClient) -> None:
        """
        Инициализация раннера агента.

        Args:
            config: Конфигурация агента
            llm_client: Клиент для LLM API
        """
        self.config: AgentConfig = config
        self.llm: LLMClient = llm_client
        self.logger = structlog.get_logger("agent_runner").bind(
            agent=config.agent_name
        )

    def _build_prompt(self, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Формирует пользовательский промпт на основе контекста.
        """
        parts: List[str] = []

        # Базовая инструкция
        parts.append(f"Запуск агента: {self.config.agent_name}")
        parts.append(f"Время: {datetime.now().isoformat()}")

        # Контекст из предыдущих запусков
        if context:
            parts.append("\n## Контекст:")
            for key, value in context.items():
                # Особое форматирование trend-рекомендаций
                if key == "trend_recommendations" and isinstance(value, list):
                    parts.append("\n### 🎯 Активные рекомендации от Trend Agent:")
                    for i, rec in enumerate(value[:3], 1):
                        parts.append(f"\n**Рекомендация #{i}** (приоритет: {rec.get('priority', 'medium')})")
                        parts.append(f"- Тренд: {rec.get('trend_title', 'N/A')}")
                        parts.append(f"- Действие: {rec.get('action', 'N/A')}")
                        if rec.get('deadline'):
                            parts.append(f"- Дедлайн: {rec['deadline']}")
                        if rec.get('confidence'):
                            parts.append(f"- Уверенность: {rec['confidence']}")
                        if rec.get('trend_description'):
                            desc = rec['trend_description'][:200]
                            parts.append(f"- Описание: {desc}")
                    parts.append("\n⚠️ Важно: при планировании действий учитывай эти рекомендации.")

                # Особое форматирование analytics-задач
                elif key == "analytics_tasks" and isinstance(value, list):
                    parts.append("\n### 📊 Задачи от Analytics Agent:")
                    for i, task in enumerate(value[:3], 1):
                        parts.append(f"\n**Задача #{i}** (приоритет: {task.get('priority', 'medium')})")
                        parts.append(f"- Название: {task.get('title', 'N/A')}")
                        if task.get('description'):
                            desc = task['description'][:300]
                            parts.append(f"- Описание: {desc}")
                        if task.get('deadline'):
                            parts.append(f"- Дедлайн: {task['deadline']}")
                        if task.get('metrics'):
                            metrics = task['metrics']
                            if isinstance(metrics, dict):
                                for mk, mv in metrics.items():
                                    parts.append(f"  - {mk}: {mv}")
                    parts.append("\n⚠️ Важно: выполни хотя бы одну задачу из списка.")

                # Особое форматирование project_context
                elif key == "project_context":
                    parts.append(f"\n{value}")
                elif key == "fresh_start" and value:
                    parts.append("- Это первый запуск агента, нет предыдущих результатов.")
                elif key == "recent_summaries":
                    parts.append("- Последние запуски (ключи результатов):")
                    for s in value[:3]:
                        ts = s.get('timestamp', '')[:16]
                        keys = ', '.join(s.get('keys', [])[:5])
                        parts.append(f"  - {ts}: {keys}")
                elif key == "latest_metrics" and isinstance(value, dict):
                    parts.append("- Последние метрики:")
                    for mk, mv in list(value.items())[:5]:
                        parts.append(f"  - {mk}: {mv}")
                else:
                    parts.append(f"- {key}: {value}")

        # Инструкция по формату ответа
        parts.append("\n## Требования к ответу:")
        parts.append("Верни результат строго в формате JSON.")
        parts.append("Не добавляй пояснений вне JSON.")

        return "\n".join(parts)

    def _parse_result(self, raw_content: str) -> Dict[str, Any]:
        """
        Парсит сырой ответ LLM в структурированный словарь.

        Args:
            raw_content: Сырой текст от LLM

        Returns:
            Распарсенный словарь с результатом

        Raises:
            json.JSONDecodeError: Если не удалось распарсить JSON
        """
        # Попытка найти JSON в ответе (модели иногда оборачивают в markdown)
        content = raw_content.strip()

        # Удаление markdown-обёртки ```json ... ```
        if content.startswith("```"):
            lines = content.split("\n")
            # Убираем первую и последнюю строки с ```
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            content = "\n".join(lines).strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Если JSON невалидный, пробуем найти JSON-подстроку
            import re
            json_match = re.search(r'\{[\s\S]*\}', content)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

            # Если всё равно не удалось, возвращаем как текст
            self.logger.warning("Не удалось распарсить JSON, возвращаем как текст")
            return {"raw_text": content, "parse_error": True}

    async def run(self, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Запускает агента через LLM API.

        Args:
            context: Контекст для агента (предыдущие результаты и т.д.)

        Returns:
            Словарь с результатом выполнения агента:
                - data: распарсенные данные
                - raw: сырой ответ от LLM
                - usage: информация об использовании токенов
                - success: флаг успешности
                - error: сообщение об ошибке (если есть)
        """
        self.logger.info("Запуск агента")
        start_time = time.monotonic()

        try:
            system_prompt = self.config.get_system_prompt()
            user_prompt = self._build_prompt(context)
            llm_settings = self.config.get_llm_settings()

            # Вызов LLM
            llm_result = await self.llm.generate(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                temperature=llm_settings.get("temperature", 0.7),
                max_tokens=llm_settings.get("max_tokens", 4096),
            )

            # Парсинг результата
            parsed_data = self._parse_result(llm_result["content"])

            elapsed_ms = (time.monotonic() - start_time) * 1000

            self.logger.info(
                "Агент выполнен успешно",
                elapsed_ms=round(elapsed_ms, 2),
                prompt_tokens=llm_result["usage"].get("prompt_tokens", 0),
                completion_tokens=llm_result["usage"].get("completion_tokens", 0),
            )

            return {
                "data": parsed_data,
                "raw": llm_result["content"],
                "usage": llm_result["usage"],
                "model": llm_result.get("model", self.llm.model),
                "success": True,
                "elapsed_ms": round(elapsed_ms, 2),
                "error": None,
            }

        except Exception as e:
            elapsed_ms = (time.monotonic() - start_time) * 1000
            self.logger.error("Ошибка при выполнении агента", error=str(e))

            return {
                "data": {},
                "raw": "",
                "usage": {},
                "model": self.llm.model,
                "success": False,
                "elapsed_ms": round(elapsed_ms, 2),
                "error": str(e),
            }

    async def retry(
        self,
        previous_result: Dict[str, Any],
        error: str,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> Dict[str, Any]:
        """
        Повторный запуск агента с экспоненциальным backoff.

        Args:
            previous_result: Результат предыдущей попытки
            error: Описание ошибки
            max_retries: Максимальное количество попыток

        Returns:
            Результат выполнения (успешный или с ошибкой после всех попыток)
        """
        self.logger.info(
            "Начало retry-цикла",
            max_retries=max_retries,
            error=error,
        )

        for attempt in range(1, max_retries + 1):
            delay = DEFAULT_RETRY_DELAY * (RETRY_BACKOFF_MULTIPLIER ** (attempt - 1))

            self.logger.info(
                f"Попытка {attempt}/{max_retries}",
                delay_seconds=round(delay, 2),
            )

            # Экспоненциальная задержка
            await asyncio.sleep(delay)

            # Формируем контекст с информацией об ошибке
            retry_context = {
                "previous_error": error,
                "retry_attempt": attempt,
                "previous_result_snippet": previous_result.get("raw", "")[:500],
            }

            result = await self.run(context=retry_context)

            if result["success"]:
                self.logger.info(f"Retry успешен на попытке {attempt}")
                result["retry_attempts"] = attempt
                return result

        self.logger.error(f"Все {max_retries} попытки исчерпаны")
        return {
            **previous_result,
            "retry_attempts": max_retries,
            "retry_exhausted": True,
        }


# ═══════════════════════════════════════════════════════════════════════════════
# MemoryStore — Хранение памяти агентов (PostgreSQL + Redis)
# ═══════════════════════════════════════════════════════════════════════════════
class MemoryStore:
    """
    Хранилище памяти агентов — управляет сохранением и получением результатов.

    Использует PostgreSQL для долгосрочного хранения и Redis
    для кэширования и быстрого доступа к последним результатам.

    Example:
        >>> store = MemoryStore("postgresql://...", "redis://...")
        >>> await store.save_result("seo-agent", result, cycle_id="cycle-001")
        >>> history = await store.get_last_results("seo-agent", limit=5)
    """

    def __init__(self, db_url: str, redis_url: str) -> None:
        """
        Инициализация хранилища памяти.

        Args:
            db_url: URL подключения к PostgreSQL
            redis_url: URL подключения к Redis
        """
        self.db_url: str = db_url
        self.redis_url: str = redis_url
        self.logger = structlog.get_logger("memory_store")

        # Пул подключений будет создан при первом использовании
        self._db_pool: Optional[asyncpg.Pool] = None
        self._redis: Optional[aioredis.Redis] = None

    async def _get_db_pool(self) -> asyncpg.Pool:
        """Получает или создаёт пул подключений к PostgreSQL."""
        if self._db_pool is None or self._db_pool._closed:
            self.logger.info("Создание пула подключений к PostgreSQL")
            self._db_pool = await asyncpg.create_pool(
                self.db_url,
                min_size=2,
                max_size=10,
                command_timeout=60,
            )
        return self._db_pool

    async def _get_redis(self) -> aioredis.Redis:
        """Получает или создаёт подключение к Redis."""
        if self._redis is None:
            self.logger.info("Подключение к Redis")
            self._redis = await aioredis.from_url(
                self.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    async def init_schema(self) -> None:
        """
        Инициализирует схему базы данных.

        Создаёт необходимые таблицы если они не существуют.
        """
        pool = await self._get_db_pool()

        async with pool.acquire() as conn:
            self.logger.info("Инициализация схемы БД")

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_results (
                    id SERIAL PRIMARY KEY,
                    agent_name VARCHAR(100) NOT NULL,
                    agent_type VARCHAR(50) NOT NULL,
                    cycle_id VARCHAR(100) NOT NULL,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    data JSONB NOT NULL,
                    metrics JSONB DEFAULT '{}',
                    validation_status VARCHAR(20) DEFAULT 'pending',
                    validation_score FLOAT DEFAULT 0.0,
                    validation_errors JSONB DEFAULT '[]',
                    execution_time_ms FLOAT DEFAULT 0.0,
                    model VARCHAR(100),
                    usage_tokens JSONB DEFAULT '{}'
                )
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_results_name
                ON agent_results(agent_name)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_results_cycle
                ON agent_results(cycle_id)
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_results_timestamp
                ON agent_results(timestamp DESC)
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_metrics (
                    id SERIAL PRIMARY KEY,
                    agent_name VARCHAR(100) NOT NULL,
                    timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    metrics JSONB NOT NULL
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS orchestrator_cycles (
                    id SERIAL PRIMARY KEY,
                    cycle_id VARCHAR(100) UNIQUE NOT NULL,
                    started_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
                    completed_at TIMESTAMP WITH TIME ZONE,
                    status VARCHAR(20) DEFAULT 'running',
                    agents_count INTEGER DEFAULT 0,
                    errors_count INTEGER DEFAULT 0
                )
            """)

            self.logger.info("Схема БД инициализирована")

    async def save_result(
        self,
        agent_name: str,
        result: Dict[str, Any],
        cycle_id: str,
    ) -> None:
        """
        Сохраняет результат работы агента.

        Args:
            agent_name: Имя агента
            result: Результат работы агента (от AgentRunner)
            cycle_id: ID цикла оркестратора
        """
        pool = await self._get_db_pool()
        redis = await self._get_redis()

        data = result.get("data", {})
        metrics = result.get("usage", {})
        model = result.get("model", "unknown")
        elapsed_ms = result.get("elapsed_ms", 0.0)

        # Извлекаем тип агента из имени
        agent_type = agent_name.split("-")[0] if "-" in agent_name else agent_name

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_results (
                    agent_name, agent_type, cycle_id, data, metrics,
                    model, execution_time_ms, usage_tokens
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                agent_name,
                agent_type,
                cycle_id,
                json.dumps(data),
                json.dumps(metrics),
                model,
                elapsed_ms,
                json.dumps(metrics),
            )

        # Кэшируем в Redis
        cache_key = f"agent:last_result:{agent_name}"
        await redis.setex(
            cache_key,
            3600,  # TTL 1 час
            json.dumps({
                "cycle_id": cycle_id,
                "timestamp": datetime.now().isoformat(),
                "data": data,
                "elapsed_ms": elapsed_ms,
            }, ensure_ascii=False),
        )

        self.logger.info(
            "Результат сохранён",
            agent=agent_name,
            cycle_id=cycle_id,
            elapsed_ms=elapsed_ms,
        )

    async def get_last_results(
        self,
        agent_name: str,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Получает последние результаты агента.

        Сначала проверяет Redis-кэш, затем обращается к PostgreSQL.

        Args:
            agent_name: Имя агента
            limit: Максимальное количество результатов

        Returns:
            Список последних результатов
        """
        pool = await self._get_db_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT agent_name, cycle_id, timestamp, data,
                       metrics, validation_status, validation_score,
                       execution_time_ms, model
                FROM agent_results
                WHERE agent_name = $1
                ORDER BY timestamp DESC
                LIMIT $2
                """,
                agent_name,
                limit,
            )

        results = []
        for row in rows:
            results.append({
                "agent_name": row["agent_name"],
                "cycle_id": row["cycle_id"],
                "timestamp": row["timestamp"].isoformat() if row["timestamp"] else None,
                "data": row["data"] if isinstance(row["data"], dict) else json.loads(row["data"]),
                "metrics": row["metrics"] if isinstance(row["metrics"], dict) else json.loads(row["metrics"]),
                "validation_status": row["validation_status"],
                "validation_score": row["validation_score"],
                "execution_time_ms": row["execution_time_ms"],
                "model": row["model"],
            })

        return results

    async def get_context(self, agent_name: str) -> Dict[str, Any]:
        """
        Формирует контекст для следующего запуска агента.

        Собирает информацию из последних результатов, метрик
        и активных trend-рекомендаций для передачи агенту.
        """
        last_results = await self.get_last_results(agent_name, limit=3)

        if not last_results:
            context = {"fresh_start": True}
        else:
            context: Dict[str, Any] = {
                "previous_runs_count": len(last_results),
                "last_run": {
                    "timestamp": last_results[0].get("timestamp"),
                    "validation_score": last_results[0].get("validation_score"),
                    "execution_time_ms": last_results[0].get("execution_time_ms"),
                },
            }

            # Добавляем краткую сводку последних результатов
            recent_summaries = []
            for r in last_results[:3]:
                data = r.get("data", {})
                summary = {
                    "timestamp": r.get("timestamp"),
                    "keys": list(data.keys())[:10],
                }
                recent_summaries.append(summary)

            context["recent_summaries"] = recent_summaries

            # Получаем метрики
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                metrics_row = await conn.fetchrow(
                    """
                    SELECT metrics FROM agent_metrics
                    WHERE agent_name = $1
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    agent_name,
                )

            if metrics_row:
                context["latest_metrics"] = metrics_row["metrics"]

        # ═══ PUSH-МОДЕЛЬ: Trend рекомендации для этого агента ═══
        trend_recs = await self.get_trend_recommendations(agent_name, limit=3)
        if trend_recs:
            context["trend_recommendations"] = trend_recs
            self.logger.info(
                "trend_context_injected",
                agent=agent_name,
                count=len(trend_recs),
            )

        # ═══ PUSH-МОДЕЛЬ: Analytics задачи для этого агента ═══
        analytics_tasks = await self.get_analytics_tasks(agent_name, limit=3)
        if analytics_tasks:
            context["analytics_tasks"] = analytics_tasks
            self.logger.info(
                "analytics_tasks_injected",
                agent=agent_name,
                count=len(analytics_tasks),
            )

        # ═══ PROJECT CONTEXT: Файлы проекта для этого агента ═══
        try:
            from scripts.project_context import get_project_context_for_agent
            atype = agent_name.split("-")[0] if "-" in agent_name else agent_name
            project_ctx = get_project_context_for_agent(atype)
            if project_ctx:
                context["project_context"] = project_ctx
                self.logger.info(
                    "project_context_injected",
                    agent=agent_name,
                    chars=len(project_ctx),
                )
        except Exception as e:
            self.logger.warning("project_context_failed", agent=agent_name, error=str(e))

        return context

    async def get_trend_recommendations(self, agent_name: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Получает активные (pending) trend-рекомендации для агента.
        """
        try:
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT trend_title, action, priority, deadline, confidence, trend_description, metrics
                    FROM trend_recommendations
                    WHERE target_agent = $1 AND status = 'pending'
                    ORDER BY 
                        CASE priority 
                            WHEN 'high' THEN 1 
                            WHEN 'medium' THEN 2 
                            WHEN 'low' THEN 3 
                            ELSE 4 
                        END,
                        confidence DESC
                    LIMIT $2
                    """,
                    agent_name,
                    limit,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            self.logger.error("Failed to get trend recommendations", agent=agent_name, error=str(e))
            return []

    async def mark_trend_recommendations_completed(self, agent_name: str, actions: List[str]) -> None:
        """
        Помечает trend-рекомендации как выполненные.
        """
        try:
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                for action_text in actions:
                    await conn.execute(
                        """
                        UPDATE trend_recommendations
                        SET status = 'completed', completed_at = NOW()
                        WHERE target_agent = $1 AND action = $2 AND status = 'pending'
                        """,
                        agent_name,
                        action_text,
                    )
        except Exception as e:
            self.logger.error("Failed to mark trend recommendations", agent=agent_name, error=str(e))

    async def get_analytics_tasks(self, agent_name: str, limit: int = 5) -> List[Dict[str, Any]]:
        """
        Получает активные (pending) задачи от analytics_agent для агента.
        """
        try:
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT title, description, priority, deadline, metrics, created_at
                    FROM agent_tasks
                    WHERE target_agent = $1 AND status = 'pending'
                    ORDER BY
                        CASE priority
                            WHEN 'high' THEN 1
                            WHEN 'medium' THEN 2
                            WHEN 'low' THEN 3
                            ELSE 4
                        END,
                        created_at DESC
                    LIMIT $2
                    """,
                    agent_name,
                    limit,
                )
                return [dict(r) for r in rows]
        except Exception as e:
            self.logger.error("Failed to get analytics tasks", agent=agent_name, error=str(e))
            return []

    async def mark_analytics_tasks_completed(self, agent_name: str, titles: List[str]) -> None:
        """
        Помечает analytics-задачи как выполненные.
        """
        try:
            pool = await self._get_db_pool()
            async with pool.acquire() as conn:
                for title in titles:
                    await conn.execute(
                        """
                        UPDATE agent_tasks
                        SET status = 'completed', completed_at = NOW()
                        WHERE target_agent = $1 AND title = $2 AND status = 'pending'
                        """,
                        agent_name,
                        title,
                    )
        except Exception as e:
            self.logger.error("Failed to mark analytics tasks", agent=agent_name, error=str(e))

    async def save_metrics(self, agent_name: str, metrics: Dict[str, Any]) -> None:
        """
        Сохраняет метрики агента.

        Args:
            agent_name: Имя агента
            metrics: Словарь с метриками
        """
        pool = await self._get_db_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_metrics (agent_name, metrics)
                VALUES ($1, $2)
                """,
                agent_name,
                json.dumps(metrics),
            )

        self.logger.info("Метрики сохранены", agent=agent_name, metrics_keys=list(metrics.keys()))

        """
        Сохраняет метрики агента.

        Args:
            agent_name: Имя агента
            metrics: Словарь с метриками
        """
        pool = await self._get_db_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO agent_metrics (agent_name, metrics)
                VALUES ($1, $2)
                """,
                agent_name,
                json.dumps(metrics),
            )

        self.logger.info("Метрики сохранены", agent=agent_name, metrics_keys=list(metrics.keys()))

    async def update_validation_status(
        self,
        agent_name: str,
        cycle_id: str,
        validation: ValidationResult,
    ) -> None:
        """
        Обновляет статус валидации результата.

        Args:
            agent_name: Имя агента
            cycle_id: ID цикла
            validation: Результат валидации
        """
        pool = await self._get_db_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE agent_results
                SET validation_status = $1,
                    validation_score = $2,
                    validation_errors = $3
                WHERE agent_name = $4 AND cycle_id = $5
                """,
                validation.status.value,
                validation.score,
                json.dumps(validation.errors + validation.warnings),
                agent_name,
                cycle_id,
            )

    async def save_task(self, task: Dict[str, Any]) -> None:
        """
        Сохраняет задачу в очередь приоритетных задач в Redis.

        Args:
            task: Словарь с описанием задачи (agent, type, priority, context)
        """
        redis = await self._get_redis()
        await redis.lpush("agent:priority_tasks", json.dumps(task, ensure_ascii=False))
        self.logger.info(
            "Приоритетная задача сохранена",
            agent=task.get("agent"),
            task_type=task.get("type"),
            priority=task.get("priority"),
        )

    async def get_pending_tasks(self, agent_name: str) -> List[Dict[str, Any]]:
        """
        Получает ожидающие задачи для указанного агента.

        Args:
            agent_name: Имя агента для фильтрации задач

        Returns:
            Список задач, назначенных данному агенту
        """
        redis = await self._get_redis()
        tasks_raw = await redis.lrange("agent:priority_tasks", 0, -1)
        result: List[Dict[str, Any]] = []
        for task_json in tasks_raw:
            try:
                task = json.loads(task_json)
                if task.get("agent") == agent_name:
                    result.append(task)
            except json.JSONDecodeError:
                self.logger.warning("Невалидная задача в очереди", raw=task_json[:200])
                continue
        return result

    async def complete_task(self, task_id: str) -> bool:
        """
        Отмечает задачу как выполненную — перемещает из очереди
        ожидающих в очередь выполненных.

        Args:
            task_id: Идентификатор задачи для завершения

        Returns:
            True если задача найдена и перемещена
        """
        redis = await self._get_redis()
        tasks_raw = await redis.lrange("agent:priority_tasks", 0, -1)
        for task_json in tasks_raw:
            try:
                task = json.loads(task_json)
                if task.get("id") == task_id or task.get("created_from_trend") == task_id:
                    await redis.lrem("agent:priority_tasks", 0, task_json)
                    await redis.lpush("agent:completed_tasks", task_json)
                    self.logger.info("Задача отмечена как выполненная", task_id=task_id)
                    return True
            except json.JSONDecodeError:
                continue
        self.logger.warning("Задача для завершения не найдена", task_id=task_id)
        return False

    async def close(self) -> None:
        """Закрывает все подключения."""
        if self._db_pool and not self._db_pool._closed:
            await self._db_pool.close()
            self.logger.info("Пул PostgreSQL закрыт")

        if self._redis:
            await self._redis.close()
            self.logger.info("Подключение к Redis закрыто")


# ═══════════════════════════════════════════════════════════════════════════════
# TelegramReporter — Отправка отчётов в Telegram
# ═══════════════════════════════════════════════════════════════════════════════
class TelegramReporter:
    """
    Репортёр в Telegram — отправляет отчёты и алерты.

    Отправляет ежедневные отчёты, алерты при ошибках,
    сводки по циклам. Поддерживает форматирование Markdown.

    Example:
        >>> reporter = TelegramReporter(bot_token="...", chat_id="...")
        >>> await reporter.send_daily_report(report)
        >>> await reporter.send_alert("seo-agent", "Ошибка подключения")
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ) -> None:
        """
        Инициализация репортёра.

        Args:
            bot_token: Токен Telegram бота (или из env TELEGRAM_BOT_TOKEN)
            chat_id: ID чата для отправки (или из env TELEGRAM_CHAT_ID)
        """
        self.bot_token: str = bot_token or os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id: str = chat_id or os.getenv("TELEGRAM_CHAT_ID", "")
        self.logger = structlog.get_logger("telegram_reporter")

        if not self.bot_token or not self.chat_id:
            self.logger.warning(
                "TeleReporter не полностью настроен — проверьте TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID"
            )

        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        """Получает или создаёт HTTP-сессию."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30))
        return self._session

    async def _send_message(self, text: str, parse_mode: str = "Markdown") -> bool:
        """
        Отправляет сообщение в Telegram.

        Args:
            text: Текст сообщения
            parse_mode: Режим парсинга (Markdown, HTML)

        Returns:
            True если отправка успешна
        """
        if not self.bot_token or not self.chat_id:
            self.logger.warning("Telegram не настроен, сообщение не отправлено")
            return False

        url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": parse_mode,
        }

        try:
            session = await self._get_session()
            async with session.post(url, json=payload) as response:
                if response.status == 200:
                    self.logger.info("Сообщение отправлено в Telegram")
                    return True
                else:
                    error_text = await response.text()
                    self.logger.error(
                        "Ошибка отправки в Telegram",
                        status=response.status,
                        error=error_text,
                    )
                    return False
        except Exception as e:
            self.logger.error("Исключение при отправке в Telegram", error=str(e))
            return False

    async def send_daily_report(self, report: Dict[str, Any]) -> bool:
        """
        Отправляет ежедневный отчёт.

        Args:
            report: Словарь с данными отчёта:
                - date: дата отчёта
                - total_agents: всего агентов
                - successful_runs: успешных запусков
                - failed_runs: неудачных запусков
                - avg_validation_score: средняя оценка валидации
                - agent_details: детали по каждому агенту

        Returns:
            True если отправка успешна
        """
        date = report.get("date", datetime.now().strftime("%Y-%m-%d"))
        total = report.get("total_agents", 0)
        successful = report.get("successful_runs", 0)
        failed = report.get("failed_runs", 0)
        avg_score = report.get("avg_validation_score", 0.0)

        # Определяем эмодзи статуса
        if failed == 0:
            status_emoji = "✅"
        elif failed < successful:
            status_emoji = "⚠️"
        else:
            status_emoji = "❌"

        text = f"""
📊 *Ежедневный отчёт оркестратора*
📅 Дата: `{date}`

{status_emoji} *Общая сводка:*
• Всего агентов: {total}
• Успешных запусков: {successful}
• Неудачных: {failed}
• Средняя оценка: {avg_score:.2f}

📋 *Детали по агентам:*
"""

        for agent in report.get("agent_details", []):
            name = agent.get("name", "unknown")
            status = agent.get("status", "unknown")
            score = agent.get("validation_score", 0.0)
            emoji = "✅" if status == "success" else "❌" if status == "failed" else "⚠️"
            text += f"\n{emoji} `{name}`: {status} (score: {score:.2f})"

        if report.get("errors"):
            text += "\n\n🚨 *Ошибки:*\n"
            for error in report["errors"][:5]:  # Максимум 5 ошибок
                text += f"• `{error}`\n"

        return await self._send_message(text)

    async def send_alert(self, agent_name: str, error: str) -> bool:
        """
        Отправляет алерт об ошибке агента.

        Args:
            agent_name: Имя агента
            error: Текст ошибки

        Returns:
            True если отправка успешна
        """
        text = f"""
🚨 *АЛЕРТ: Ошибка агента*

👤 Агент: `{agent_name}`
⏰ Время: `{datetime.now().isoformat()}`
❌ Ошибка:
```
{error[:500]}
```
"""
        return await self._send_message(text)

    async def send_summary(self, cycle_results: Dict[str, Any]) -> bool:
        """
        Отправляет сводку по циклу оркестратора.

        Args:
            cycle_results: Результаты цикла:
                - cycle_id: ID цикла
                - results: список результатов по агентам
                - duration_ms: длительность цикла

        Returns:
            True если отправка успешна
        """
        cycle_id = cycle_results.get("cycle_id", "unknown")
        results = cycle_results.get("results", [])
        duration_ms = cycle_results.get("duration_ms", 0)

        success_count = sum(1 for r in results if r.get("success"))
        fail_count = len(results) - success_count

        text = f"""
🔄 *Сводка по циклу*
🆔 ID: `{cycle_id}`
⏱ Длительность: `{duration_ms:.0f} мс`

📈 Результаты:
• Всего: {len(results)}
• Успешно: {success_count}
• Ошибок: {fail_count}

👤 *По агентам:*
"""

        for result in results:
            name = result.get("agent_name", "unknown")
            success = result.get("success", False)
            elapsed = result.get("elapsed_ms", 0)
            emoji = "✅" if success else "❌"
            text += f"\n{emoji} `{name}` — {elapsed:.0f} мс"

        return await self._send_message(text)

    async def close(self) -> None:
        """Закрывает HTTP-сессию."""
        if self._session and not self._session.closed:
            await self._session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrator — Главный оркестратор
# ═══════════════════════════════════════════════════════════════════════════════
class Orchestrator:
    """
    Главный оркестратор — координирует всех агентов в системе.

    Управляет жизненным циклом агентов: загрузка конфигураций,
    запуск по расписанию, валидация результатов, обработка ошибок,
    хранение в БД и отправка отчётов.

    Attributes:
        config_path: Путь к директории с конфигурациями агентов
        db_url: URL подключения к PostgreSQL
        redis_url: URL подключения к Redis
        running: Флаг работы оркестратора
        paused_agents: Множество приостановленных агентов

    Example:
        >>> orch = Orchestrator("./configs", "postgresql://...", "redis://...")
        >>> await orch.load_agents()
        >>> await orch.run()  # Бесконечный цикл
    """

    def __init__(
        self,
        config_path: str = "./configs",
        db_url: Optional[str] = None,
        redis_url: Optional[str] = None,
    ) -> None:
        """
        Инициализация оркестратора.

        Args:
            config_path: Путь к директории с конфигурациями агентов
            db_url: URL PostgreSQL (или из env DATABASE_URL)
            redis_url: URL Redis (или из env REDIS_URL)
        """
        self.config_path: str = config_path
        self.db_url: str = db_url or os.getenv(
            "DATABASE_URL", "postgresql://user:pass@localhost/agents"
        )
        self.redis_url: str = redis_url or os.getenv(
            "REDIS_URL", "redis://localhost:6379"
        )

        # Компоненты системы
        self.llm_client: Optional[LLMClient] = None
        self.memory: Optional[MemoryStore] = None
        self.reporter: Optional[TelegramReporter] = None
        self.validator: Optional[ResultValidator] = None

        # Состояние агентов
        self.agents: List[AgentConfig] = []
        self.agent_runners: Dict[str, AgentRunner] = {}
        self.running: bool = False
        self.paused_agents: set = set()

        # Статистика
        self.cycle_count: int = 0
        self.total_errors: int = 0
        self.start_time: Optional[datetime] = None

        self.logger = structlog.get_logger("orchestrator")

    async def initialize(self) -> None:
        """
        Инициализирует все компоненты оркестратора.

        Создаёт подключения к БД, Redis, LLM API и инициализирует схему.
        """
        self.logger.info("Инициализация оркестратора")

        # Инициализация LLM клиента (базовый, для общих задач)
        self.llm_client = LLMClient(
            api_key=os.getenv("LLM_API_KEY"),
            model=os.getenv("DEFAULT_LLM_MODEL", "nvidia/nemotron-nano-9b-v2"),
            base_url=os.getenv("LLM_API_URL"),
        )

        # Инициализация хранилища памяти
        self.memory = MemoryStore(self.db_url, self.redis_url)
        await self.memory.init_schema()

        # Инициализация репортёра (отключено — отчёты теперь через telegram_bot.py)
        # self.reporter = TelegramReporter()
        self.reporter = None

        # Инициализация валидатора (правила будут загружены для каждого агента)
        self.validator = ResultValidator(rules={})

        # Загрузка агентов
        await self.load_agents()

        self.logger.info(
            "Оркестратор инициализирован",
            agents_count=len(self.agents),
        )

    async def load_agents(self) -> List[AgentConfig]:
        """
        Загружает конфигурации всех агентов из директории.

        Сканирует директорию config_path на наличие JSON-файлов
        и создаёт для каждого AgentConfig.

        Returns:
            Список загруженных конфигураций агентов
        """
        config_dir = Path(self.config_path)
        if not config_dir.exists():
            self.logger.warning(
                "Директория конфигураций не найдена, создаём",
                path=str(config_dir),
            )
            config_dir.mkdir(parents=True, exist_ok=True)
            return []

        self.agents = []
        self.agent_runners = {}

        for config_file in sorted(config_dir.glob("*.json")):
            agent_name = config_file.stem
            try:
                config = AgentConfig(agent_name, str(config_dir))
                config.load_config()

                if not config.is_enabled():
                    self.logger.info("Агент отключён в конфигурации", agent=agent_name)
                    continue

                self.agents.append(config)

                # Создаём раннер для агента с персональной моделью
                # Модель берётся из env вида {AGENT_NAME}_MODEL (например SMM_AGENT_MODEL)
                agent_model = os.getenv(
                    f"{agent_name.upper().replace('-', '_')}_MODEL",
                    os.getenv("DEFAULT_LLM_MODEL", "nvidia/nemotron-nano-9b-v2")
                )
                agent_llm = LLMClient(
                    api_key=os.getenv("LLM_API_KEY"),
                    model=agent_model,
                    base_url=os.getenv("LLM_API_URL"),
                )
                self.agent_runners[agent_name] = AgentRunner(config, agent_llm)

                self.logger.info(
                    "Агент загружен",
                    agent=agent_name,
                    model=agent_model,
                )

            except Exception as e:
                self.logger.error(
                    "Ошибка загрузки агента",
                    agent=agent_name,
                    error=str(e),
                )

        self.logger.info(
            "Загрузка агентов завершена",
            total=len(self.agents),
        )
        return self.agents

    async def save_priority_task(self, task: Dict[str, Any]) -> None:
        """
        Сохраняет приоритетную задачу в очередь через хранилище памяти.

        Args:
            task: Словарь с описанием приоритетной задачи
        """
        if self.memory:
            await self.memory.save_task(task)
        else:
            self.logger.warning("Хранилище памяти не инициализировано, задача не сохранена")

    async def dispatch_trend_recommendations(self, trend_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Рассылка рекомендаций от Trend Agent другим агентам.

        Сохраняет в PostgreSQL таблицу trend_recommendations.
        Другие агенты при запуске автоматически получают эти рекомендации в свой prompt.
        """
        actions = trend_result.get("recommended_actions", [])
        dispatched: List[Dict[str, Any]] = []

        pool = await self._get_db_pool()
        async with pool.acquire() as conn:
            for action in actions:
                target_agent = action.get("agent")
                if target_agent not in AGENT_NAMES or target_agent == "trend_agent":
                    self.logger.warning(
                        "Пропуск рекомендации — некорректный целевой агент",
                        target_agent=target_agent,
                        action=action.get("action"),
                    )
                    continue

                # Сохраняем в trend_recommendations
                await conn.execute(
                    """
                    INSERT INTO trend_recommendations 
                    (trend_id, target_agent, action, priority, deadline, confidence, trend_title, trend_description, metrics, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, 'pending')
                    ON CONFLICT DO NOTHING
                    """,
                    trend_result.get("trend_id"),
                    target_agent,
                    action.get("action"),
                    action.get("priority", "medium"),
                    action.get("deadline"),
                    trend_result.get("confidence"),
                    trend_result.get("title"),
                    trend_result.get("description"),
                    json.dumps(trend_result.get("metrics", {})) if trend_result.get("metrics") else None,
                )

                task = {
                    "agent": target_agent,
                    "trend_title": trend_result.get("title"),
                    "action": action.get("action"),
                    "priority": action.get("priority"),
                }
                dispatched.append(task)

                self.logger.info(
                    "trend_recommendation_saved",
                    target_agent=target_agent,
                    trend=trend_result.get("title"),
                    priority=action.get("priority"),
                )

        return {
            "trend": trend_result.get("title"),
            "total_recommendations": len(actions),
            "dispatched": len(dispatched),
            "tasks": dispatched,
        }

    async def dispatch_analytics_tasks(self, analytics_result: Dict[str, Any]) -> int:
        """
        Создание задач из рекомендаций Analytics Agent для других агентов.

        Парсит результат analytics_agent, извлекает tasks и сохраняет в agent_tasks.
        """
        # Пытаемся найти tasks в разных местах результата
        tasks = analytics_result.get("tasks", [])
        
        # Если tasks не найдены напрямую — ищем в recommendations
        if not tasks and "recommendations" in analytics_result:
            recs = analytics_result.get("recommendations", [])
            for rec in recs:
                if isinstance(rec, dict):
                    # Преобразуем рекомендацию в задачу
                    target = rec.get("executor", rec.get("target_agent", ""))
                    # Маппинг executor -> agent_name
                    agent_map = {
                        "marketing": "smm_agent",
                        "content": "content_agent",
                        "seo": "seo_agent",
                        "smm": "smm_agent",
                    }
                    target_agent = agent_map.get(target, target)
                    if target_agent in AGENT_NAMES and target_agent != "analytics_agent":
                        tasks.append({
                            "target_agent": target_agent,
                            "title": rec.get("problem", rec.get("title", "")),
                            "description": f"{rec.get('cause', '')}\n\nДействие: {rec.get('action', '')}",
                            "priority": "medium",
                            "metrics": rec.get("expected_effect", {}),
                        })

        if not tasks:
            return 0

        pool = await self._get_db_pool()
        saved_count = 0
        async with pool.acquire() as conn:
            for task in tasks:
                target_agent = task.get("target_agent", "")
                if target_agent not in AGENT_NAMES or target_agent == "analytics_agent":
                    continue

                await conn.execute(
                    """
                    INSERT INTO agent_tasks 
                    (source_agent, target_agent, title, description, priority, deadline, status, metrics)
                    VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7)
                    ON CONFLICT DO NOTHING
                    """,
                    "analytics_agent",
                    target_agent,
                    task.get("title", "")[:200],
                    task.get("description", "")[:2000],
                    task.get("priority", "medium"),
                    task.get("deadline"),
                    json.dumps(task.get("metrics", {})) if task.get("metrics") else None,
                )
                saved_count += 1

        self.logger.info("analytics_tasks_dispatched", count=saved_count)
        return saved_count

    async def run_cycle(self) -> Dict[str, Any]:
        """
        Выполняет один цикл оркестратора — запускает всех агентов.

        Для каждого агента:
        1. Получает контекст из памяти
        2. Запускает агента через LLM
        3. Валидирует результат
        4. Сохраняет в БД
        5. Обрабатывает ошибки

        Returns:
            Словарь с результатами цикла:
                - cycle_id: ID цикла
                - results: список результатов
                - duration_ms: длительность
                - errors: список ошибок
        """
        cycle_id = f"cycle-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}"
        self.cycle_count += 1

        self.logger.info(
            "=== НАЧАЛО ЦИКЛА ===",
            cycle_id=cycle_id,
            cycle_number=self.cycle_count,
            agents_count=len(self.agents),
        )

        cycle_start = time.monotonic()
        cycle_results: List[Dict[str, Any]] = []
        cycle_errors: List[str] = []

        # Запись о начале цикла в БД
        if self.memory:
            pool = await self.memory._get_db_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    "INSERT INTO orchestrator_cycles (cycle_id, agents_count) VALUES ($1, $2)",
                    cycle_id,
                    len(self.agents),
                )

        # Запуск агентов
        for config in self.agents:
            agent_name = config.agent_name

            agent_start = time.monotonic()

            try:
                # Проверка паузы через Telegram (/pause команда)
                try:
                    pause_key = f"agent:pause:{agent_name}"
                    paused = await redis.get(pause_key)
                    if paused:
                        self.logger.info("Агент на паузе, пропускаем", agent=agent_name)
                        cycle_results.append({
                            "agent_name": agent_name,
                            "success": True,
                            "elapsed_ms": 0,
                            "validation_score": 0.0,
                            "actions": ["paused"],
                            "result": {"status": "paused_by_user"},
                        })
                        continue
                except Exception:
                    pass

                # Проверка срочного запуска (/run_now команда)
                try:
                    run_now_key = f"agent:run_now:{agent_name}"
                    run_now = await redis.get(run_now_key)
                    if run_now:
                        await redis.delete(run_now_key)
                        self.logger.info("Срочный запуск агента", agent=agent_name)
                except Exception:
                    pass

                # Получаем контекст из памяти
                context = {}
                if self.memory:
                    context = await self.memory.get_context(agent_name)

                # Запускаем агента
                runner = self.agent_runners.get(agent_name)
                if not runner:
                    self.logger.warning("Раннер не найден", agent=agent_name)
                    continue

                result = await runner.run(context=context)

                # Retry при ошибке
                if not result["success"]:
                    self.logger.info("Повторная попытка после ошибки", agent=agent_name)
                    result = await runner.retry(
                        previous_result=result,
                        error=result.get("error", "Unknown error"),
                    )

                # Валидация результата
                if result["success"] and self.validator:
                    agent_type = agent_name.split("-")[0] if "-" in agent_name else agent_name
                    validation = self.validator.validate(result["data"], agent_type)
                    result["validation"] = {
                        "status": validation.status.value,
                        "score": validation.score,
                        "errors": validation.errors,
                        "warnings": validation.warnings,
                    }

                    # Обновляем валидатор в результате
                    result["validation_result"] = validation

                    # После валидации trend_agent — рассылка рекомендаций
                    if agent_name == "trend_agent" and validation.is_valid:
                        dispatch_result = await self.dispatch_trend_recommendations(result["data"])
                        self.logger.info("trend_recommendations_dispatched", **dispatch_result)

                    # После валидации analytics_agent — создание задач для других агентов
                    if agent_name == "analytics_agent" and validation.is_valid:
                        task_count = await self.dispatch_analytics_tasks(result["data"])
                        self.logger.info("analytics_tasks_dispatched", count=task_count)

                # Сохранение результата
                if self.memory:
                    await self.memory.save_result(agent_name, result, cycle_id)

                    # Обновление статуса валидации
                    if "validation_result" in result:
                        await self.memory.update_validation_status(
                            agent_name, cycle_id, result["validation_result"]
                        )

                # ═══ РЕАЛЬНЫЕ ДЕЙСТВИЯ АГЕНТОВ ═══
                if result["success"]:
                    try:
                        action_log = []
                        agent_type = agent_name.split("-")[0] if "-" in agent_name else agent_name
                        data = result.get("data", {})

                        # File operations — для всех агентов (руки, защищённые)
                        file_ops = data.get("file_ops", data.get("files", []))
                        if file_ops:
                            from scripts.safe_project_context import safe_write_file, validate_write
                            if isinstance(file_ops, list):
                                for op in file_ops[:5]:  # макс 5 операций за раз
                                    if isinstance(op, dict):
                                        path = op.get("path", op.get("file", ""))
                                        content = op.get("content", "")
                                        mode = op.get("mode", "overwrite")
                                        if path and content:
                                            # Валидация перед записью
                                            val = validate_write(path, mode)
                                            if not val["valid"]:
                                                action_log.append(f"file:{path}:BLOCKED")
                                                self.logger.warning("file_op_blocked", agent=agent_name, path=path, reason=val["error"])
                                                continue
                                            res = safe_write_file(path, content, append=(mode=="append"))
                                            action_log.append(f"file:{path}:{res.get('success', False)}")
                            elif isinstance(file_ops, dict):
                                path = file_ops.get("path", file_ops.get("file", ""))
                                content = file_ops.get("content", "")
                                mode = file_ops.get("mode", "overwrite")
                                if path and content:
                                    val = validate_write(path, mode)
                                    if not val["valid"]:
                                        action_log.append(f"file:{path}:BLOCKED")
                                        self.logger.warning("file_op_blocked", agent=agent_name, path=path, reason=val["error"])
                                    else:
                                        res = safe_write_file(path, content, append=(mode=="append"))
                                        action_log.append(f"file:{path}:{res.get('success', False)}")

                        if agent_type == "smm":
                            # SMM — публикуем посты в Telegram
                            posts = data.get("posts", data.get("content", []))
                            if isinstance(posts, list):
                                for post in posts[:3]:  # макс 3 за раз
                                    if isinstance(post, dict):
                                        ok = await post_discount(post)
                                    else:
                                        ok = await post_to_channel(str(post))
                                    action_log.append(f"tg_post:{ok}")
                            elif isinstance(posts, str):
                                ok = await post_to_channel(posts)
                                action_log.append(f"tg_post:{ok}")

                        elif agent_type == "seo":
                            # SEO — обновляем meta-теги
                            data = result.get("data", {})
                            title = data.get("title", data.get("meta_title", ""))
                            desc = data.get("description", data.get("meta_description", ""))
                            keywords = data.get("keywords", "")
                            if title and desc:
                                ok = update_meta_tags(title, desc, keywords)
                                action_log.append(f"meta_updated:{ok}")

                        elif agent_type == "performance":
                            # Performance — обновляем приоритеты товаров
                            data = result.get("data", {})
                            top_ids = data.get("top_products", data.get("prioritize", []))
                            if top_ids:
                                ok = prioritize_products(top_ids)
                                action_log.append(f"prioritized:{ok}")
                            # Добавляем бейджи на карточки (HTML + JSON)
                            featured = data.get("featured_products", [])
                            for fid in featured[:5]:
                                ok = add_badge(str(fid), "ХИТ")
                                action_log.append(f"badge:{fid}:{ok}")
                            # Дополнительные бейджи (NEW, ТОП)
                            new_items = data.get("new_products", [])
                            for nid in new_items[:3]:
                                ok = add_badge(str(nid), "NEW")
                                action_log.append(f"badge:new:{nid}:{ok}")
                            top_items = data.get("top_rated", [])
                            for tid in top_items[:3]:
                                ok = add_badge(str(tid), "ТОП")
                                action_log.append(f"badge:top:{tid}:{ok}")

                        elif agent_type == "content":
                            # Content — создаём/обновляем страницы
                            data = result.get("data", {})
                            cat = data.get("category", data.get("page_category", ""))
                            html = data.get("html", data.get("content", ""))
                            if cat and html:
                                ok = create_category_page(cat, html)
                                action_log.append(f"category_page:{cat}:{ok}")
                            # Обновляем описания товаров
                            items = data.get("items", data.get("product_descriptions", []))
                            for item in items[:3]:
                                if isinstance(item, dict):
                                    iid = item.get("id", item.get("itemId", ""))
                                    desc = item.get("description", "")
                                    if iid and desc:
                                        ok = update_item_description(str(iid), desc)
                                        action_log.append(f"item_desc:{iid}:{ok}")

                        # Сохраняем лог действий в результат
                        if action_log:
                            result["actions"] = action_log
                            self.logger.info("Agent actions executed", agent=agent_name, actions=action_log)

                        # ═══ Mark trend recommendations as completed ═══
                        if self.memory and action_log and agent_type in ("smm", "seo", "content"):
                            # Get pending trend recommendations for this agent
                            trend_recs = await self.memory.get_trend_recommendations(agent_name, limit=10)
                            if trend_recs:
                                completed_actions = [r["action"] for r in trend_recs]
                                await self.memory.mark_trend_recommendations_completed(agent_name, completed_actions)
                                self.logger.info(
                                    "trend_recommendations_marked_completed",
                                    agent=agent_name,
                                    count=len(completed_actions),
                                )

                            # Get pending analytics tasks for this agent
                            analytics_tasks = await self.memory.get_analytics_tasks(agent_name, limit=10)
                            if analytics_tasks:
                                completed_titles = [t["title"] for t in analytics_tasks]
                                await self.memory.mark_analytics_tasks_completed(agent_name, completed_titles)
                                self.logger.info(
                                    "analytics_tasks_marked_completed",
                                    agent=agent_name,
                                    count=len(completed_titles),
                                )

                    except Exception as e:
                        self.logger.error("Action execution failed", agent=agent_name, error=str(e))
                        # Не ломаем цикл — просто логируем

                # Обработка ошибок
                if not result["success"]:
                    await self.handle_failure(
                        agent_name=agent_name,
                        error=result.get("error", "Unknown"),
                        result=result,
                    )
                    cycle_errors.append(f"{agent_name}: {result.get('error', '')}")
                    self.total_errors += 1

                agent_elapsed = (time.monotonic() - agent_start) * 1000

                cycle_results.append({
                    "agent_name": agent_name,
                    "success": result["success"],
                    "elapsed_ms": agent_elapsed,
                    "validation_score": result.get("validation", {}).get("score", 0.0),
                    "actions": result.get("actions", []),
                    "result": result.get("data", {}),
                })

                self.logger.info(
                    "Агент завершён",
                    agent=agent_name,
                    success=result["success"],
                    elapsed_ms=round(agent_elapsed, 2),
                )

            except Exception as e:
                agent_elapsed = (time.monotonic() - agent_start) * 1000
                self.logger.error(
                    "Критическая ошибка агента",
                    agent=agent_name,
                    error=str(e),
                )
                await self.handle_failure(agent_name, str(e), {})
                cycle_errors.append(f"{agent_name}: {str(e)}")
                self.total_errors += 1

                cycle_results.append({
                    "agent_name": agent_name,
                    "success": False,
                    "elapsed_ms": agent_elapsed,
                    "error": str(e),
                })

        # Подсчёт итогов
        cycle_duration = (time.monotonic() - cycle_start) * 1000
        success_count = sum(1 for r in cycle_results if r["success"])

        # Обновление записи о цикле
        if self.memory:
            pool = await self.memory._get_db_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    UPDATE orchestrator_cycles
                    SET completed_at = NOW(),
                        status = $1,
                        errors_count = $2
                    WHERE cycle_id = $3
                    """,
                    "completed" if len(cycle_errors) == 0 else "completed_with_errors",
                    len(cycle_errors),
                    cycle_id,
                )

        # Отправка сводки в Telegram
        if self.reporter:
            await self.reporter.send_summary({
                "cycle_id": cycle_id,
                "results": cycle_results,
                "duration_ms": cycle_duration,
            })

        self.logger.info(
            "=== ЦИКЛ ЗАВЕРШЁН ===",
            cycle_id=cycle_id,
            duration_ms=round(cycle_duration, 2),
            success=success_count,
            failed=len(cycle_results) - success_count,
        )

        return {
            "cycle_id": cycle_id,
            "results": cycle_results,
            "duration_ms": cycle_duration,
            "errors": cycle_errors,
            "timestamp": datetime.now().isoformat(),
        }

    async def validate_and_store(
        self,
        agent_name: str,
        result: Dict[str, Any],
    ) -> ValidationResult:
        """
        Валидирует и сохраняет результат агента.

        Args:
            agent_name: Имя агента
            result: Результат для валидации и сохранения

        Returns:
            Результат валидации
        """
        if not self.validator:
            return ValidationResult(
                status=ValidationStatus.SKIPPED,
                warnings=["Валидатор не инициализирован"],
            )

        agent_type = agent_name.split("-")[0] if "-" in agent_name else agent_name
        validation = self.validator.validate(result.get("data", {}), agent_type)

        self.logger.info(
            "Валидация результата",
            agent=agent_name,
            status=validation.status.value,
            score=validation.score,
        )

        return validation

    async def handle_failure(
        self,
        agent_name: str,
        error: str,
        result: Dict[str, Any],
    ) -> None:
        """
        Обрабатывает ошибку агента.

        Логирует ошибку, отправляет алерт в Telegram.

        Args:
            agent_name: Имя агента
            error: Текст ошибки
            result: Результат (может быть пустым)
        """
        self.logger.error(
            "Ошибка агента",
            agent=agent_name,
            error=error,
        )

        # Отправка алерта
        if self.reporter:
            await self.reporter.send_alert(agent_name, error)

    async def generate_daily_report(self) -> Dict[str, Any]:
        """
        Генерирует ежедневный отчёт о работе оркестратора.

        Собирает статистику за текущий день из БД.

        Returns:
            Словарь с данными ежедневного отчёта:
                - date: дата отчёта
                - total_agents: всего агентов
                - successful_runs: успешных запусков
                - failed_runs: неудачных запусков
                - avg_validation_score: средняя оценка
                - agent_details: детали по агентам
        """
        today = datetime.now().strftime("%Y-%m-%d")

        if not self.memory:
            return {
                "date": today,
                "total_agents": len(self.agents),
                "successful_runs": 0,
                "failed_runs": 0,
                "avg_validation_score": 0.0,
                "agent_details": [],
            }

        pool = await self.memory._get_db_pool()

        async with pool.acquire() as conn:
            # Статистика по агентам за сегодня
            rows = await conn.fetch(
                """
                SELECT
                    agent_name,
                    COUNT(*) as run_count,
                    AVG(validation_score) as avg_score,
                    SUM(CASE WHEN validation_status = 'failed' THEN 1 ELSE 0 END) as fail_count
                FROM agent_results
                WHERE timestamp >= $1
                GROUP BY agent_name
                """,
                datetime.now().replace(hour=0, minute=0, second=0, microsecond=0),
            )

        agent_details = []
        total_success = 0
        total_fail = 0
        total_score = 0.0

        for row in rows:
            fail_count = row["fail_count"] or 0
            run_count = row["run_count"] or 0
            success_count = run_count - fail_count
            avg_score = row["avg_score"] or 0.0

            agent_details.append({
                "name": row["agent_name"],
                "runs": run_count,
                "successful": success_count,
                "failed": fail_count,
                "avg_score": round(avg_score, 3),
                "status": "success" if fail_count == 0 else "partial" if success_count > 0 else "failed",
                "validation_score": avg_score,
            })

            total_success += success_count
            total_fail += fail_count
            total_score += avg_score

        avg_total = total_score / len(rows) if rows else 0.0

        report = {
            "date": today,
            "total_agents": len(self.agents),
            "successful_runs": total_success,
            "failed_runs": total_fail,
            "avg_validation_score": round(avg_total, 3),
            "agent_details": agent_details,
            "cycle_count": self.cycle_count,
            "total_errors": self.total_errors,
            "uptime_hours": (
                (datetime.now() - self.start_time).total_seconds() / 3600
                if self.start_time else 0
            ),
        }

        # Отправка отчёта в Telegram
        if self.reporter:
            await self.reporter.send_daily_report(report)

        self.logger.info("Ежедневный отчёт сгенерирован", date=today)
        return report

    async def run(self) -> None:
        """
        Запускает бесконечный цикл оркестратора.

        Выполняет циклы с заданным интервалом до получения
        сигнала остановки (SIGINT, SIGTERM).

        The loop:
            1. Проверка времени для ежедневного отчёта (9:00)
            2. Запуск cycle для всех агентов
            3. Ожидание interval секунд
        """
        self.running = True
        self.start_time = datetime.now()
        last_report_date = None

        # Интервал между циклами
        interval = int(os.getenv("CYCLE_INTERVAL", DEFAULT_CYCLE_INTERVAL))

        self.logger.info(
            "Оркестратор запущен",
            interval_seconds=interval,
            agents=[a.agent_name for a in self.agents],
        )

        while self.running:
            try:
                # Проверка времени для ежедневного отчёта (9:00)
                now = datetime.now()
                if now.hour == 9 and last_report_date != now.strftime("%Y-%m-%d"):
                    self.logger.info("Генерация ежедневного отчёта")
                    await self.generate_daily_report()
                    last_report_date = now.strftime("%Y-%m-%d")

                # Выполнение цикла
                await self.run_cycle()

                # Ожидание до следующего цикла
                self.logger.info(
                    f"Ожидание {interval} секунд до следующего цикла"
                )
                await asyncio.sleep(interval)

            except asyncio.CancelledError:
                self.logger.info("Цикл оркестратора отменён")
                break
            except Exception as e:
                self.logger.error("Ошибка в цикле оркестратора", error=str(e))
                self.total_errors += 1
                await asyncio.sleep(interval)

        self.logger.info("Оркестратор остановлен")

    def pause_agent(self, agent_name: str) -> bool:
        """
        Приостанавливает агента.

        Args:
            agent_name: Имя агента для приостановки

        Returns:
            True если агент найден и приостановлен
        """
        for config in self.agents:
            if config.agent_name == agent_name:
                self.paused_agents.add(agent_name)
                self.logger.info("Агент приостановлен", agent=agent_name)
                return True
        return False

    def resume_agent(self, agent_name: str) -> bool:
        """
        Возобновляет работу агента.

        Args:
            agent_name: Имя агента для возобновления

        Returns:
            True если агент найден и возобновлён
        """
        if agent_name in self.paused_agents:
            self.paused_agents.discard(agent_name)
            self.logger.info("Агент возобновлён", agent=agent_name)
            return True
        return False

    def stop(self) -> None:
        """Останавливает оркестратор."""
        self.logger.info("Получена команда остановки")
        self.running = False

    async def close(self) -> None:
        """Закрывает все ресурсы."""
        self.stop()

        if self.llm_client:
            await self.llm_client.close()
        if self.memory:
            await self.memory.close()
        if self.reporter:
            await self.reporter.close()

        self.logger.info("Все ресурсы оркестратора освобождены")


# ═══════════════════════════════════════════════════════════════════════════════
# Обработка сигналов для graceful shutdown
# ═══════════════════════════════════════════════════════════════════════════════
def setup_signal_handlers(orchestrator: Orchestrator) -> None:
    """
    Настраивает обработчики сигналов для корректной остановки.

    Args:
        orchestrator: Экземпляр оркестратора
    """
    def signal_handler(sig, frame):
        logger.info(f"Получен сигнал {sig}, останавливаем оркестратор...")
        orchestrator.stop()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)


# ═══════════════════════════════════════════════════════════════════════════════
# Точка входа
# ═══════════════════════════════════════════════════════════════════════════════
async def main() -> None:
    """Главная точка входа — создаёт и запускает оркестратор."""
    orchestrator = Orchestrator(
        config_path=os.getenv("AGENTS_CONFIG_PATH", "./configs"),
    )

    # Настройка обработчиков сигналов
    setup_signal_handlers(orchestrator)

    try:
        # Инициализация
        await orchestrator.initialize()

        # Запуск бесконечного цикла
        await orchestrator.run()

    except KeyboardInterrupt:
        logger.info("Прервано пользователем")
    except Exception as e:
        logger.error("Критическая ошибка оркестратора", error=str(e))
        raise
    finally:
        await orchestrator.close()


if __name__ == "__main__":
    asyncio.run(main())
