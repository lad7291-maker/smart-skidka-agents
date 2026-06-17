#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для llm_judge.py — LLM-as-a-Judge и HeuristicJudge.
"""

import sys
import unittest

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

from scripts.llm_judge import HeuristicJudge, JudgeResult


class TestHeuristicJudge(unittest.TestCase):
    """Тесты эвристического judge (без LLM)."""

    def setUp(self):
        self.judge = HeuristicJudge()

    def test_good_content_passes(self):
        """Хороший контент проходит валидацию."""
        result = self.judge.evaluate_content(
            {
                "title": "Лучшие скидки на смартфоны",
                "content": (
                    "<h2>Топ-5 смартфонов</h2>"
                    "<p>Сэкономьте до 30% на покупке.</p>"
                    "<ul><li>iPhone 15 — 89 990 ₽</li></ul>"
                    "<p>Промокоды актуальны.</p>"
                ),
                "keywords": ["скидки", "смартфоны"],
            }
        )
        self.assertIsInstance(result, JudgeResult)
        self.assertGreaterEqual(result.score, 0.6)
        self.assertTrue(result.passed)

    def test_irrelevant_content_fails(self):
        """Нерелевантный контент не проходит."""
        result = self.judge.evaluate_content(
            {
                "title": "Красивые цветы летом",
                "content": "<p>Летом цветы очень красивые. Они растут в саду.</p>",
                "keywords": ["цветы", "сад"],
            }
        )
        self.assertLess(result.score, 0.6)
        self.assertFalse(result.passed)
        self.assertTrue(
            any("скидк" in e.lower() or "промокод" in e.lower() or "цен" in e.lower() for e in result.errors)
        )

    def test_no_numbers_warning(self):
        """Контент без цифр получает предупреждение."""
        result = self.judge.evaluate_content(
            {
                "title": "Скидки на электронику",
                "content": "<p>Много скидок на разные товары. Экономьте с умом.</p>",
                "keywords": ["скидки"],
            }
        )
        self.assertTrue(any("цифр" in e or "цен" in e for e in result.errors))

    def test_suspicious_phrases_detected(self):
        """Подозрительные фразы снижают оценку."""
        result = self.judge.evaluate_content(
            {
                "title": "Лучшие скидки",
                "content": "<p>100% гарантия лучших цен! Уникальная возможность!</p>",
                "keywords": ["скидки"],
            }
        )
        self.assertTrue(any("галлюцинац" in e.lower() or "маркетингов" in e.lower() for e in result.errors))

    def test_structure_scoring(self):
        """Структура влияет на оценку."""
        with_headers = self.judge.evaluate_content(
            {
                "title": "Test",
                "content": "<h2>Section</h2><p>Text</p><ul><li>Item</li></ul>",
                "keywords": ["скидки"],
            }
        )
        without_headers = self.judge.evaluate_content(
            {
                "title": "Test",
                "content": "<p>Just plain text without any structure.</p>",
                "keywords": ["скидки"],
            }
        )
        self.assertGreater(
            with_headers.criteria.get("structure", 0),
            without_headers.criteria.get("structure", 0),
        )

    def test_criteria_present(self):
        """Все критерии присутствуют в результате."""
        result = self.judge.evaluate_content(
            {
                "title": "Test",
                "content": "<p>Test content with скидки.</p>",
                "keywords": ["скидки"],
            }
        )
        expected_criteria = {
            "relevance",
            "readability",
            "structure",
            "usefulness",
            "no_hallucinations",
        }
        self.assertEqual(set(result.criteria.keys()), expected_criteria)


class TestJudgeResultDataclass(unittest.TestCase):
    """Тесты data-класса JudgeResult."""

    def test_defaults(self):
        """JudgeResult имеет корректные значения по умолчанию."""
        jr = JudgeResult()
        self.assertEqual(jr.score, 0.0)
        self.assertFalse(jr.passed)
        self.assertEqual(jr.feedback, "")
        self.assertEqual(jr.criteria, {})
        self.assertEqual(jr.errors, [])

    def test_custom_values(self):
        """JudgeResult принимает кастомные значения."""
        jr = JudgeResult(score=0.85, passed=True, feedback="Good")
        self.assertEqual(jr.score, 0.85)
        self.assertTrue(jr.passed)
        self.assertEqual(jr.feedback, "Good")


if __name__ == "__main__":
    unittest.main(verbosity=2)
