#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                      LLM-as-a-Judge Module                           ║
║                         smart-skidka.ru                              ║
╠══════════════════════════════════════════════════════════════════════╣
║  Модуль качественной оценки результатов агентов через LLM.          ║
║  Дополняет rule-based валидацию оценкой:                            ║
║    - Релевантности контента бизнес-задаче                           ║
║    - Читаемости и стиля текста                                      ║
║    - Структурированности и полезности                               ║
║    - Отсутствия галлюцинаций и фактических ошибок                   ║
╚══════════════════════════════════════════════════════════════════════╝

Использование:
    >>> from llm_judge import LLMJudge
    >>> judge = LLMJudge()
    >>> result = await judge.evaluate_content(content_result, agent_type="content")
    >>> print(result.score, result.feedback)
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import aiohttp
import structlog

logger = structlog.get_logger("llm_judge")

# ═══════════════════════════════════════════════════════════════════════════════
# Константы
# ═══════════════════════════════════════════════════════════════════════════════

JUDGE_MODEL = os.getenv("LLM_JUDGE_MODEL", os.getenv("DEFAULT_LLM_MODEL", "nvidia/nemotron-nano-9b-v2"))
JUDGE_API_URL = os.getenv("LLM_API_URL", "https://routerai.ru/api/v1/chat/completions")
JUDGE_API_KEY = os.getenv("LLM_API_KEY", "")
JUDGE_TIMEOUT = aiohttp.ClientTimeout(total=30)


# ═══════════════════════════════════════════════════════════════════════════════
# Data-классы
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class JudgeResult:
    """Результат оценки LLM-as-a-Judge."""
    score: float = 0.0  # 0.0 – 1.0
    passed: bool = False
    feedback: str = ""
    criteria: Dict[str, float] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════════
# LLM Judge
# ═══════════════════════════════════════════════════════════════════════════════

class LLMJudge:
    """
    LLM-as-a-Judge для качественной оценки результатов агентов.

    Использует отдельный LLM-вызов с judge-промптом для оценки:
    - Релевантности и полезности контента
    - Качества текста (стиль, читаемость)
    - Структуры и полноты
    - Отсутствия галлюцинаций
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        api_url: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or JUDGE_API_KEY
        self.model = model or JUDGE_MODEL
        self.api_url = api_url or JUDGE_API_URL
        self._session: Optional[aiohttp.ClientSession] = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=JUDGE_TIMEOUT)
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _call_llm(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.3,
        max_tokens: int = 1024,
    ) -> Dict[str, Any]:
        """Вызов LLM API для judge-оценки."""
        if not self.api_key:
            return {
                "success": False,
                "error": "LLM_API_KEY not configured",
                "content": "",
            }

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

        try:
            async with session.post(
                self.api_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            ) as response:
                if response.status != 200:
                    text = await response.text()
                    return {
                        "success": False,
                        "error": f"HTTP {response.status}: {text[:200]}",
                        "content": "",
                    }

                data = await response.json()
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                return {
                    "success": True,
                    "content": content,
                    "usage": data.get("usage", {}),
                }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "content": "",
            }

    def _parse_judge_response(self, raw: str) -> JudgeResult:
        """Парсит JSON-ответ judge-LLM."""
        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            raw = "\n".join(lines).strip()

        try:
            data = json.loads(raw)
            return JudgeResult(
                score=float(data.get("score", 0)),
                passed=bool(data.get("passed", False)),
                feedback=data.get("feedback", ""),
                criteria=data.get("criteria", {}),
                errors=data.get("errors", []),
            )
        except (json.JSONDecodeError, ValueError) as e:
            # Fallback: пытаемся извлечь score из текста
            import re
            score_match = re.search(r'["\']?score["\']?\s*[:=]\s*([0-9.]+)', raw)
            score = float(score_match.group(1)) if score_match else 0.5
            return JudgeResult(
                score=score,
                passed=score >= 0.6,
                feedback=raw[:500],
                errors=[f"Parse error: {e}"],
            )

    # ─── Оценка контента ──────────────────────────────────────────────────────

    async def evaluate_content(
        self,
        result: Dict[str, Any],
        agent_type: str = "content",
    ) -> JudgeResult:
        """
        Оценивает качество сгенерированного контента.

        Args:
            result: Результат работы агента (title, content, keywords, etc.)
            agent_type: Тип агента (content, seo, smm, email)

        Returns:
            JudgeResult с оценкой и обратной связью
        """
        system_prompt = """Ты — экспертный редактор и SEO-аналитик. 
Твоя задача — оценить качество сгенерированного контента для агрегатора скидок smart-skidka.ru.

Оцени контент по 5 критериям (каждый от 0 до 1):
1. **relevance** — Релевантность теме и целевой аудитории (экономия на покупках)
2. **readability** — Читаемость, стиль, структура предложений
3. **structure** — Логическая структура, наличие заголовков, списков, CTA
4. **usefulness** — Практическая полезность для читателя (конкретные советы, цифры, примеры)
5. **no_hallucinations** — Отсутствие выдуманных фактов, несуществующих магазинов/промокодов

Верни результат СТРОГО в формате JSON:
{
  "score": 0.0-1.0,  // среднее по критериям
  "passed": true/false,  // score >= 0.6
  "feedback": "Краткий разбор: что хорошо, что плохо, 2-3 предложения",
  "criteria": {
    "relevance": 0.0-1.0,
    "readability": 0.0-1.0,
    "structure": 0.0-1.0,
    "usefulness": 0.0-1.0,
    "no_hallucinations": 0.0-1.0
  },
  "errors": []
}

Не добавляй пояснений вне JSON."""

        title = result.get("title", "")
        content = result.get("content", "")[:3000]  # ограничиваем длину
        content_type = result.get("content_type", "article")
        keywords = result.get("keywords", [])

        user_prompt = f"""Оцени следующий контент:

**Тип:** {content_type}
**Заголовок:** {title}
**Ключевые слова:** {', '.join(keywords) if isinstance(keywords, list) else keywords}

**Текст:**
{content}

**Требования к контенту для smart-skidka.ru:**
- Целевая аудитория: люди 18-45 лет, ищущие скидки и промокоды
- Контент должен быть практичным: конкретные магазины, реальные цифры экономии
- Не должно быть выдуманных промокодов или несуществующих акций
- Должен быть призыв к действию (перейти на сайт, найти скидку)
"""

        llm_result = await self._call_llm(system_prompt, user_prompt, temperature=0.3)
        if not llm_result["success"]:
            logger.warning("LLM judge failed", error=llm_result.get("error"))
            return JudgeResult(
                score=0.0,
                passed=False,
                feedback=f"Judge error: {llm_result.get('error')}",
                errors=[llm_result.get("error", "Unknown error")],
            )

        return self._parse_judge_response(llm_result["content"])

    # ─── Оценка SEO ───────────────────────────────────────────────────────────

    async def evaluate_seo(
        self,
        result: Dict[str, Any],
    ) -> JudgeResult:
        """Оценивает качество SEO-результата."""
        system_prompt = """Ты — SEO-эксперт. Оцени SEO-мета-данные для агрегатора скидок.

Критерии (0-1):
1. **title_quality** — Привлекательность title, наличие ключевых слов, длина
2. **meta_quality** — Информативность description, CTA, уникальность
3. **keyword_relevance** — Релевантность ключевых слов теме скидок
4. **commercial_intent** — Коммерческая направленность (покупка, сравнение цен)

Верни JSON:
{"score": 0.0-1.0, "passed": true/false, "feedback": "...", "criteria": {...}, "errors": []}"""

        user_prompt = f"""Оцени SEO-результат:

Title: {result.get('title', '')}
Meta Description: {result.get('meta_description', '')}
H1: {result.get('h1', '')}
Keywords: {result.get('keywords', [])}
"""

        llm_result = await self._call_llm(system_prompt, user_prompt, temperature=0.3)
        if not llm_result["success"]:
            return JudgeResult(
                score=0.0,
                passed=False,
                feedback=f"Judge error: {llm_result.get('error')}",
                errors=[llm_result.get("error", "")],
            )
        return self._parse_judge_response(llm_result["content"])

    # ─── Оценка SMM ───────────────────────────────────────────────────────────

    async def evaluate_smm(
        self,
        result: Dict[str, Any],
    ) -> JudgeResult:
        """Оценивает качество SMM-поста."""
        system_prompt = """Ты — SMM-менеджер. Оцени пост для Telegram-канала агрегатора скидок.

Критерии (0-1):
1. **engagement** — Привлекательность, интрига, хочется прочитать
2. **clarity** — Понятность, конкретика (что, где, сколько)
3. **cta** — Наличие призыва к действию
4. **hashtag_quality** — Релевантность хештегов

Верни JSON:
{"score": 0.0-1.0, "passed": true/false, "feedback": "...", "criteria": {...}, "errors": []}"""

        user_prompt = f"""Оцени SMM-пост:

Платформа: {result.get('platform', 'telegram')}
Текст:
{result.get('text', '')}

Хештеги: {result.get('hashtags', [])}
CTA: {result.get('cta', '')}
"""

        llm_result = await self._call_llm(system_prompt, user_prompt, temperature=0.3)
        if not llm_result["success"]:
            return JudgeResult(
                score=0.0,
                passed=False,
                feedback=f"Judge error: {llm_result.get('error')}",
                errors=[llm_result.get("error", "")],
            )
        return self._parse_judge_response(llm_result["content"])

    # ─── Универсальная оценка ─────────────────────────────────────────────────

    async def evaluate(
        self,
        result: Dict[str, Any],
        agent_type: str,
    ) -> JudgeResult:
        """
        Универсальная точка входа для оценки результата любого агента.

        Args:
            result: Результат работы агента
            agent_type: Тип агента (seo, smm, content, email, performance, trend, analytics)

        Returns:
            JudgeResult с оценкой
        """
        evaluators = {
            "seo": self.evaluate_seo,
            "smm": self.evaluate_smm,
            "content": self.evaluate_content,
            "email": self.evaluate_content,
            "performance": self.evaluate_content,
            "trend": self.evaluate_content,
            "analytics": self.evaluate_content,
        }

        evaluator = evaluators.get(agent_type.lower(), self.evaluate_content)
        return await evaluator(result)


# ═══════════════════════════════════════════════════════════════════════════════
# Fallback judge (без LLM — heuristic-based)
# ═══════════════════════════════════════════════════════════════════════════════

class HeuristicJudge:
    """
    Heuristic-based judge для случаев, когда LLM недоступен.
    Использует простые эвристики для оценки качества.
    """

    @staticmethod
    def evaluate_content(result: Dict[str, Any]) -> JudgeResult:
        """Эвристическая оценка контента без LLM."""
        content = result.get("content", "")
        title = result.get("title", "")
        criteria: Dict[str, float] = {}
        errors: List[str] = []

        # relevance: наличие ключевых слов скидок/промокодов
        discount_keywords = ["скидк", "промокод", "распродаж", "дешев", "акци", "кешбэк", "эконом"]
        content_lower = content.lower()
        has_discount_kw = any(kw in content_lower for kw in discount_keywords)
        criteria["relevance"] = 0.8 if has_discount_kw else 0.3
        if not has_discount_kw:
            errors.append("В контенте отсутствуют ключевые слова о скидках/промокодах")

        # readability: оценка по длине предложений
        sentences = [s.strip() for s in content.split(".") if s.strip()]
        avg_len = sum(len(s.split()) for s in sentences) / len(sentences) if sentences else 0
        if avg_len <= 15:
            criteria["readability"] = 0.9
        elif avg_len <= 25:
            criteria["readability"] = 0.7
        else:
            criteria["readability"] = 0.4
            errors.append(f"Слишком длинные предложения (средн. {avg_len:.0f} слов)")

        # structure: наличие заголовков, списков
        has_headers = bool(re.search(r"<h[23]|^#{2,3}", content, re.MULTILINE))
        has_lists = bool(re.search(r"<li|^\s*[-*]", content, re.MULTILINE))
        structure_score = 0.3
        if has_headers:
            structure_score += 0.35
        if has_lists:
            structure_score += 0.35
        criteria["structure"] = structure_score

        # usefulness: наличие цифр, цен, процентов
        has_numbers = bool(re.search(r"\d+%|\d+\s*руб|\d+\s*₽|экономи[ять]|выгод", content_lower))
        criteria["usefulness"] = 0.8 if has_numbers else 0.4
        if not has_numbers:
            errors.append("В контенте нет конкретных цифр, цен или процентов экономии")

        # no_hallucinations: эвристика — проверка на подозрительные фразы
        suspicious = ["100% гарантия", "лучший в мире", "никогда не видели", "уникальная возможность"]
        has_suspicious = any(s in content_lower for s in suspicious)
        criteria["no_hallucinations"] = 0.3 if has_suspicious else 0.85
        if has_suspicious:
            errors.append("Обнаружены маркетинговые клише, возможны галлюцинации")

        score = sum(criteria.values()) / len(criteria)
        return JudgeResult(
            score=round(score, 3),
            passed=score >= 0.6,
            feedback=(
                f"Эвристическая оценка: релевантность={criteria['relevance']}, "
                f"читаемость={criteria['readability']}, структура={criteria['structure']}, "
                f"полезность={criteria['usefulness']}, достоверность={criteria['no_hallucinations']}. "
                f"{'Хороший контент' if score >= 0.6 else 'Требует доработки'}."
            ),
            criteria=criteria,
            errors=errors,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Утилита: комбинированная валидация (rule-based + LLM judge)
# ═══════════════════════════════════════════════════════════════════════════════

async def combined_validate(
    result: Dict[str, Any],
    agent_type: str,
    rule_validator: Any,
    use_llm_judge: bool = True,
) -> Dict[str, Any]:
    """
    Комбинированная валидация: rule-based + LLM-as-a-Judge.

    Args:
        result: Результат работы агента
        agent_type: Тип агента
        rule_validator: Функция rule-based валидации (например, validate_by_type)
        use_llm_judge: Использовать ли LLM judge

    Returns:
        Словарь с объединённым результатом:
            - rule_validation: результат rule-based валидации
            - llm_judge: результат LLM judge (если использовался)
            - final_score: взвешенная итоговая оценка
            - passed: итоговый статус
    """
    # Rule-based валидация
    rule_result = rule_validator(result, agent_type)

    # LLM judge
    llm_result = None
    if use_llm_judge:
        judge = LLMJudge()
        try:
            llm_result = await judge.evaluate(result, agent_type)
        except Exception as e:
            logger.warning("LLM judge failed, using heuristic fallback", error=str(e))
            heuristic = HeuristicJudge()
            llm_result = heuristic.evaluate_content(result)
        finally:
            await judge.close()

    # Комбинированная оценка
    rule_score = rule_result.score if hasattr(rule_result, "score") else 0.5
    llm_score = llm_result.score if llm_result else rule_score

    # Веса: rule-based 40%, LLM judge 60%
    final_score = rule_score * 0.4 + llm_score * 0.6

    passed = (
        rule_result.is_valid if hasattr(rule_result, "is_valid") else rule_score >= 0.6
    ) and final_score >= 0.55

    return {
        "rule_validation": {
            "status": rule_result.status.value if hasattr(rule_result, "status") else "unknown",
            "score": rule_score,
            "errors": rule_result.errors if hasattr(rule_result, "errors") else [],
            "warnings": rule_result.warnings if hasattr(rule_result, "warnings") else [],
        },
        "llm_judge": {
            "score": llm_result.score if llm_result else None,
            "passed": llm_result.passed if llm_result else None,
            "feedback": llm_result.feedback if llm_result else None,
            "criteria": llm_result.criteria if llm_result else {},
            "errors": llm_result.errors if llm_result else [],
        } if llm_result else None,
        "final_score": round(final_score, 3),
        "passed": passed,
        "agent_type": agent_type,
    }
