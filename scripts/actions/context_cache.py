#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                   CONTEXT CACHE — Оптимизация памяти                 ║
║                         smart-skidka.ru                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  Кэширование контекста агентов для сокращения DB-запросов и         ║
║  файлового I/O. Реализует mtime-based invalidation и lazy loading.   ║
╚══════════════════════════════════════════════════════════════════════╝

P3-7: Оптимизация памяти контекста
    - Кэш last_results в Redis (читается, не только пишется)
    - Кэш trend_recommendations / analytics_tasks (TTL 60s)
    - Кэш project_context по mtime ключевых файлов (TTL 300s)
    - Унификация feedback + last_results в один запрос
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import structlog

logger = structlog.get_logger("context_cache")

# ═══════════════════════════════════════════════════════════════════════════════
# Конфигурация кэширования
# ═══════════════════════════════════════════════════════════════════════════════

# TTL кэшей (секунды)
CACHE_TTL_LAST_RESULTS = int(os.getenv("CACHE_TTL_LAST_RESULTS", "60"))
CACHE_TTL_TREND_RECS = int(os.getenv("CACHE_TTL_TREND_RECS", "60"))
CACHE_TTL_ANALYTICS_TASKS = int(os.getenv("CACHE_TTL_ANALYTICS_TASKS", "60"))
CACHE_TTL_PROJECT_CONTEXT = int(os.getenv("CACHE_TTL_PROJECT_CONTEXT", "300"))
CACHE_TTL_FEEDBACK = int(os.getenv("CACHE_TTL_FEEDBACK", "120"))

# Ключевые файлы для project_context (относительно PROJECT_ROOT)
PROJECT_CONTEXT_KEY_FILES = ["index.html", "products.json", "app.js"]


# ═══════════════════════════════════════════════════════════════════════════════
# ContextCache — центральный кэш контекста
# ═══════════════════════════════════════════════════════════════════════════════


class ContextCache:
    """
    Центральный кэш для контекста агентов.

    Работает с Redis (через MemoryStore) и локальным in-memory fallback.
    Ключевая логика:
    - last_results: кэшируется из Redis (уже пишется в save_result)
    - trend_recs / analytics_tasks: кэшируется с TTL
    - project_context: кэшируется по хэшу mtime ключевых файлов
    """

    def __init__(self, memory_store=None) -> None:
        self.memory = memory_store
        self._local_cache: Dict[str, Tuple[Any, datetime]] = {}
        self.logger = structlog.get_logger("context_cache")

    def _local_get(self, key: str, ttl_seconds: int) -> Optional[Any]:
        """Проверяет локальный in-memory кэш."""
        if key not in self._local_cache:
            return None
        value, cached_at = self._local_cache[key]
        if datetime.now() - cached_at > timedelta(seconds=ttl_seconds):
            del self._local_cache[key]
            return None
        return value

    def _local_set(self, key: str, value: Any) -> None:
        """Сохраняет в локальный in-memory кэш."""
        self._local_cache[key] = (value, datetime.now())

    async def _redis_get(self, key: str) -> Optional[Any]:
        """Читает из Redis через MemoryStore."""
        if self.memory is None:
            return None
        try:
            redis = await self.memory._get_redis()
            data = await redis.get(key)
            if data:
                return json.loads(data)
        except Exception as e:
            self.logger.warning("redis_get_failed", key=key, error=str(e))
        return None

    async def _redis_set(self, key: str, value: Any, ttl: int) -> None:
        """Сохраняет в Redis через MemoryStore."""
        if self.memory is None:
            return
        try:
            redis = await self.memory._get_redis()
            await redis.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
        except Exception as e:
            self.logger.warning("redis_set_failed", key=key, error=str(e))

    # ═══════════════════════════════════════════════════════════════════════
    # last_results — читаем из Redis (save_result уже пишет туда)
    # ═══════════════════════════════════════════════════════════════════════

    async def get_last_results(self, agent_name: str, limit: int = 3) -> Optional[List[Dict[str, Any]]]:
        """
        Пытается получить last_results из Redis-кэша.

        save_result() пишет в Redis ключ agent:last_result:{agent_name}
        Мы читаем его и формируем список (для limit=3 — один элемент повторяется
        как заглушка, реальный кэш для N результатов нужно добавить в save_result).

        Returns:
            Список результатов или None если кэш промахнулся.
        """
        cache_key = f"agent:last_result:{agent_name}"
        cached = await self._redis_get(cache_key)
        if cached:
            # Формируем результат в формате get_last_results
            result = {
                "agent_name": agent_name,
                "cycle_id": cached.get("cycle_id", ""),
                "timestamp": cached.get("timestamp"),
                "data": cached.get("data", {}),
                "metrics": {},
                "validation_status": "pending",
                "validation_score": 0.0,
                "execution_time_ms": cached.get("elapsed_ms", 0.0),
                "model": "unknown",
            }
            # Для limit=1 возвращаем один элемент, для большего — пока один
            return [result]
        return None

    async def set_last_results(self, agent_name: str, results: List[Dict[str, Any]]) -> None:
        """Сохраняет last_results в кэш (для multi-result кэширования)."""
        cache_key = f"agent:last_results:{agent_name}"
        await self._redis_set(cache_key, results, CACHE_TTL_LAST_RESULTS)
        self._local_set(cache_key, results)

    # ═══════════════════════════════════════════════════════════════════════
    # trend_recommendations — кэш с TTL
    # ═══════════════════════════════════════════════════════════════════════

    async def get_trend_recommendations(self, agent_name: str, limit: int = 3) -> Optional[List[Dict[str, Any]]]:
        """Читает trend recommendations из кэша."""
        cache_key = f"cache:trend_recs:{agent_name}"
        # Пробуем локальный кэш
        local = self._local_get(cache_key, CACHE_TTL_TREND_RECS)
        if local is not None:
            return local[:limit] if isinstance(local, list) else local
        # Пробуем Redis
        redis_val = await self._redis_get(cache_key)
        if redis_val is not None:
            self._local_set(cache_key, redis_val)
            return redis_val[:limit] if isinstance(redis_val, list) else redis_val
        return None

    async def set_trend_recommendations(self, agent_name: str, recs: List[Dict[str, Any]]) -> None:
        """Сохраняет trend recommendations в кэш."""
        cache_key = f"cache:trend_recs:{agent_name}"
        await self._redis_set(cache_key, recs, CACHE_TTL_TREND_RECS)
        self._local_set(cache_key, recs)

    # ═══════════════════════════════════════════════════════════════════════
    # analytics_tasks — кэш с TTL
    # ═══════════════════════════════════════════════════════════════════════

    async def get_analytics_tasks(self, agent_name: str, limit: int = 3) -> Optional[List[Dict[str, Any]]]:
        """Читает analytics tasks из кэша."""
        cache_key = f"cache:analytics_tasks:{agent_name}"
        local = self._local_get(cache_key, CACHE_TTL_ANALYTICS_TASKS)
        if local is not None:
            return local[:limit] if isinstance(local, list) else local
        redis_val = await self._redis_get(cache_key)
        if redis_val is not None:
            self._local_set(cache_key, redis_val)
            return redis_val[:limit] if isinstance(redis_val, list) else redis_val
        return None

    async def set_analytics_tasks(self, agent_name: str, tasks: List[Dict[str, Any]]) -> None:
        """Сохраняет analytics tasks в кэш."""
        cache_key = f"cache:analytics_tasks:{agent_name}"
        await self._redis_set(cache_key, tasks, CACHE_TTL_ANALYTICS_TASKS)
        self._local_set(cache_key, tasks)

    # ═══════════════════════════════════════════════════════════════════════
    # project_context — кэш по mtime ключевых файлов
    # ═══════════════════════════════════════════════════════════════════════

    def _get_project_mtime_hash(self, project_root: str) -> str:
        """
        Вычисляет хэш по mtime ключевых файлов проекта.

        Если файлы не менялись — хэш одинаковый, кэш валиден.
        """
        root = Path(project_root)
        mtimes = []
        for fname in PROJECT_CONTEXT_KEY_FILES:
            fpath = root / fname
            if fpath.exists():
                mtimes.append(f"{fname}:{fpath.stat().st_mtime:.0f}")
            else:
                mtimes.append(f"{fname}:missing")
        # Добавляем mtime директорий для glob-результатов
        for subdir in ["item", "category"]:
            dpath = root / subdir
            if dpath.exists():
                mtimes.append(f"{subdir}:{dpath.stat().st_mtime:.0f}")
        raw = "|".join(sorted(mtimes))
        return hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()[:16]

    async def get_project_context(self, agent_type: str, project_root: str) -> Optional[str]:
        """
        Пытается получить project_context из кэша.

        Ключ кэша включает agent_type + хэш mtime файлов.
        Если файлы изменились — хэш другой, кэш промахивается.
        """
        mtime_hash = self._get_project_mtime_hash(project_root)
        cache_key = f"cache:project_ctx:{agent_type}:{mtime_hash}"

        # Пробуем локальный кэш
        local = self._local_get(cache_key, CACHE_TTL_PROJECT_CONTEXT)
        if local is not None:
            return local

        # Пробуем Redis
        redis_val = await self._redis_get(cache_key)
        if redis_val is not None:
            self._local_set(cache_key, redis_val)
            return redis_val

        return None

    async def set_project_context(self, agent_type: str, project_root: str, context: str) -> None:
        """Сохраняет project_context в кэш."""
        mtime_hash = self._get_project_mtime_hash(project_root)
        cache_key = f"cache:project_ctx:{agent_type}:{mtime_hash}"
        await self._redis_set(cache_key, context, CACHE_TTL_PROJECT_CONTEXT)
        self._local_set(cache_key, context)

    # ═══════════════════════════════════════════════════════════════════════
    # feedback — кэш унифицированного запроса
    # ═══════════════════════════════════════════════════════════════════════

    async def get_feedback(self, agent_name: str, limit: int = 5) -> Optional[List[Dict[str, Any]]]:
        """Читает feedback из кэша."""
        cache_key = f"cache:feedback:{agent_name}"
        local = self._local_get(cache_key, CACHE_TTL_FEEDBACK)
        if local is not None:
            return local[:limit] if isinstance(local, list) else local
        redis_val = await self._redis_get(cache_key)
        if redis_val is not None:
            self._local_set(cache_key, redis_val)
            return redis_val[:limit] if isinstance(redis_val, list) else redis_val
        return None

    async def set_feedback(self, agent_name: str, feedback: List[Dict[str, Any]]) -> None:
        """Сохраняет feedback в кэш."""
        cache_key = f"cache:feedback:{agent_name}"
        await self._redis_set(cache_key, feedback, CACHE_TTL_FEEDBACK)
        self._local_set(cache_key, feedback)

    # ═══════════════════════════════════════════════════════════════════════
    # Инвалидация кэша
    # ═══════════════════════════════════════════════════════════════════════

    async def invalidate_agent_cache(self, agent_name: str) -> None:
        """Инвалидирует все кэши для агента (после записи нового результата)."""
        keys_to_invalidate = [
            f"cache:trend_recs:{agent_name}",
            f"cache:analytics_tasks:{agent_name}",
            f"cache:feedback:{agent_name}",
            f"agent:last_results:{agent_name}",
        ]
        # Локальная инвалидация
        for key in keys_to_invalidate:
            if key in self._local_cache:
                del self._local_cache[key]

        # Redis инвалидация
        if self.memory:
            try:
                redis = await self.memory._get_redis()
                for key in keys_to_invalidate:
                    await redis.delete(key)
            except Exception as e:
                self.logger.warning("cache_invalidation_failed", agent=agent_name, error=str(e))

        self.logger.info("agent_cache_invalidated", agent=agent_name)

    async def invalidate_project_context(self) -> None:
        """Инвалидирует кэш project_context (после деплоя/изменения файлов)."""
        # Удаляем все локальные ключи project_ctx
        keys_to_remove = [k for k in self._local_cache if k.startswith("cache:project_ctx:")]
        for key in keys_to_remove:
            del self._local_cache[key]

        if self.memory:
            try:
                redis = await self.memory._get_redis()
                # Удаляем все ключи cache:project_ctx:*
                async for key in redis.scan_iter(match="cache:project_ctx:*"):
                    await redis.delete(key)
            except Exception as e:
                self.logger.warning("project_cache_invalidation_failed", error=str(e))

        self.logger.info("project_context_cache_invalidated")

    def clear_local_cache(self) -> None:
        """Очищает локальный in-memory кэш."""
        self._local_cache.clear()
        self.logger.info("local_cache_cleared")
