#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for subgoal-based evaluation (P3-8)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import unittest

from subgoal_evaluator import (
    Checkers,
    SubgoalEvaluation,
    SubgoalEvaluator,
    SubgoalResult,
    SubgoalStatus,
    evaluate_subgoals,
    get_evaluator,
)


class TestCheckers(unittest.TestCase):
    """Unit tests for reusable checkers."""

    def test_field_exists_true(self):
        ok, msg = Checkers.field_exists({"title": "Hello"}, "title")
        self.assertTrue(ok)
        self.assertIn("присутствует", msg)

    def test_field_exists_false(self):
        ok, msg = Checkers.field_exists({}, "title")
        self.assertFalse(ok)
        self.assertIn("отсутствует", msg)

    def test_string_length_optimal(self):
        score, msg = Checkers.string_length({"t": "a" * 45}, "t", 30, 60)
        self.assertEqual(score, 1.0)

    def test_string_length_too_short(self):
        score, msg = Checkers.string_length({"t": "a" * 15}, "t", 30, 60)
        self.assertLess(score, 1.0)
        self.assertGreater(score, 0.0)

    def test_string_length_too_long(self):
        score, msg = Checkers.string_length({"t": "a" * 100}, "t", 30, 60)
        self.assertLess(score, 1.0)

    def test_contains_any_found(self):
        ok, msg = Checkers.contains_any({"t": "smart-skidka rules"}, "t", ["smart-skidka"])
        self.assertTrue(ok)

    def test_contains_any_missing(self):
        ok, msg = Checkers.contains_any({"t": "hello"}, "t", ["smart-skidka"])
        self.assertFalse(ok)

    def test_list_size_optimal(self):
        score, msg = Checkers.list_size({"k": [1, 2, 3, 4, 5]}, "k", 3, 10)
        self.assertEqual(score, 1.0)

    def test_no_duplicates_clean(self):
        ok, msg = Checkers.no_duplicates({"k": ["a", "b", "c"]}, "k")
        self.assertTrue(ok)

    def test_no_duplicates_has_dups(self):
        ok, msg = Checkers.no_duplicates({"k": ["a", "a", "b"]}, "k")
        self.assertFalse(ok)

    def test_fields_differ(self):
        score, msg = Checkers.fields_differ({"t": "Best phones", "h1": "Top smartphones"}, "t", "h1")
        self.assertEqual(score, 1.0)

    def test_fields_similar(self):
        score, msg = Checkers.fields_differ(
            {
                "t": "one two three four five six seven eight nine ten",
                "h1": "one two three four five six seven eight nine eleven",
            },
            "t",
            "h1",
        )
        self.assertLess(score, 1.0)
        self.assertGreater(score, 0.0)

    def test_has_structure_complete(self):
        score, msg = Checkers.has_structure(
            {"og": {"og:title": "x", "og:description": "y", "og:image": "z"}},
            "og",
            ["og:title", "og:description", "og:image"],
        )
        self.assertEqual(score, 1.0)

    def test_has_structure_partial(self):
        score, msg = Checkers.has_structure({"og": {"og:title": "x"}}, "og", ["og:title", "og:description", "og:image"])
        self.assertEqual(score, 1 / 3)

    def test_word_count_range_optimal(self):
        score, msg = Checkers.word_count_range({"c": "word " * 100}, "c", 50, 200)
        self.assertEqual(score, 1.0)


class TestSubgoalEvaluatorSEO(unittest.TestCase):
    """SEO subgoal evaluation tests."""

    def setUp(self):
        self.evaluator = SubgoalEvaluator()
        self.perfect_seo = {
            "title": "Лучшие скидки на электронику — smart-skidka.ru",
            "meta_description": "Найдите лучшие скидки на электронику. Перейти на smart-skidka.ru, сравнивать цены и экономить до 50% на покупках уже сегодня!",
            "keywords": ["скидки", "электроника", "дешевые гаджеты", "распродажа"],
            "h1": "Скидки на электронику: лучшие предложения",
            "og_tags": {"og:title": "x", "og:description": "y", "og:image": "z"},
            "structured_data": {"@type": "Product"},
        }

    def test_perfect_seo_all_passed(self):
        result = self.evaluator.evaluate("seo", self.perfect_seo)
        self.assertGreaterEqual(result.overall_score, 0.9)
        self.assertEqual(result.passed_count, len(result.subgoals))
        self.assertEqual(result.failed_count, 0)

    def test_seo_missing_title(self):
        data = {**self.perfect_seo, "title": ""}
        result = self.evaluator.evaluate("seo", data)
        title_sg = next(s for s in result.subgoals if s.name == "title_exists")
        self.assertEqual(title_sg.status, SubgoalStatus.FAILED)
        self.assertEqual(title_sg.score, 0.0)

    def test_seo_title_too_short(self):
        data = {**self.perfect_seo, "title": "Hi"}
        result = self.evaluator.evaluate("seo", data)
        sg = next(s for s in result.subgoals if s.name == "title_length")
        self.assertLess(sg.score, 1.0)
        self.assertGreater(sg.score, 0.0)

    def test_seo_h1_same_as_title(self):
        data = {**self.perfect_seo, "h1": self.perfect_seo["title"]}
        result = self.evaluator.evaluate("seo", data)
        sg = next(s for s in result.subgoals if s.name == "h1_unique")
        self.assertLess(sg.score, 1.0)

    def test_seo_overall_score_calculation(self):
        """Проверяем что overall_score = weighted average."""
        result = self.evaluator.evaluate("seo", self.perfect_seo)
        expected = result.weighted_score
        self.assertAlmostEqual(result.overall_score, expected, places=3)

    def test_seo_to_dict_structure(self):
        result = self.evaluator.evaluate("seo", self.perfect_seo)
        d = result.to_dict()
        self.assertIn("overall_score", d)
        self.assertIn("subgoals", d)
        self.assertIn("passed", d)
        self.assertIn("summary", d)
        self.assertTrue(all("name" in sg for sg in d["subgoals"]))


class TestSubgoalEvaluatorSMM(unittest.TestCase):
    """SMM subgoal evaluation tests."""

    def test_smm_perfect(self):
        data = {
            "text": "🔥 Новые скидки! Перейдите на smart-skidka.ru и сравните цены. #скидки #дешево",
            "image_url": "https://img.jpg",
            "platform": "instagram",
        }
        result = evaluate_subgoals("smm", data)
        self.assertGreaterEqual(result.overall_score, 0.8)

    def test_smm_twitter_too_long(self):
        data = {
            "text": "x" * 300,
            "platform": "twitter",
        }
        result = evaluate_subgoals("smm", data)
        sg = next(s for s in result.subgoals if s.name == "platform_optimal")
        self.assertEqual(sg.status, SubgoalStatus.FAILED)

    def test_smm_no_hashtags(self):
        data = {"text": "Hello world", "platform": "instagram"}
        result = evaluate_subgoals("smm", data)
        sg = next(s for s in result.subgoals if s.name == "has_hashtags")
        self.assertEqual(sg.status, SubgoalStatus.FAILED)


class TestSubgoalEvaluatorContent(unittest.TestCase):
    """Content subgoal evaluation tests."""

    def test_content_perfect(self):
        data = {
            "title": "Guide",
            "content": "<h1>Intro</h1><p>" + "word " * 1600 + "</p>",
            "content_type": "guide",
            "keywords": ["a", "b"],
            "featured_image": "img.jpg",
            "internal_links": ["link1"],
        }
        result = evaluate_subgoals("content", data)
        self.assertGreaterEqual(result.overall_score, 0.8)

    def test_content_too_short(self):
        data = {
            "title": "Short",
            "content": "<p>word word</p>",
            "content_type": "article",
        }
        result = evaluate_subgoals("content", data)
        sg = next(s for s in result.subgoals if s.name == "content_length")
        self.assertLess(sg.score, 1.0)

    def test_content_no_headings(self):
        data = {
            "title": "No headings",
            "content": "plain text without html headings",
            "content_type": "article",
        }
        result = evaluate_subgoals("content", data)
        sg = next(s for s in result.subgoals if s.name == "has_headings")
        self.assertEqual(sg.status, SubgoalStatus.FAILED)


class TestSubgoalEvaluatorEmail(unittest.TestCase):
    """Email subgoal evaluation tests."""

    def test_email_perfect(self):
        data = {
            "subject": "Your weekly deals from smart-skidka",
            "body": "Hello! Check out our latest deals. " + "word " * 150 + "<a href='#'>Отписаться от рассылки</a>",
        }
        result = evaluate_subgoals("email", data)
        self.assertGreaterEqual(result.overall_score, 0.7)

    def test_email_high_spam(self):
        data = {
            "subject": "СРОЧНО!!! КУПИ СЕЙЧАС БЕСПЛАТНО!!!",
            "body": "100% БЕСПЛАТНО $$$ ПОСЛЕДНИЙ ШАНС",
        }
        result = evaluate_subgoals("email", data)
        sg = next(s for s in result.subgoals if s.name == "low_spam_score")
        self.assertLess(sg.score, 0.5)

    def test_email_no_unsubscribe(self):
        data = {
            "subject": "Newsletter",
            "body": "Hello there, some content here.",
        }
        result = evaluate_subgoals("email", data)
        sg = next(s for s in result.subgoals if s.name == "has_unsubscribe")
        self.assertEqual(sg.status, SubgoalStatus.FAILED)


class TestSubgoalEvaluatorPerformance(unittest.TestCase):
    """Performance subgoal evaluation tests."""

    def test_performance_perfect(self):
        data = {
            "headline": "Скидки до 50% на электронику",
            "description": "Лучшие предложения",
            "target_audience": "25-45, техно-энтузиасты",
            "budget": "50000",
            "duration_days": 14,
        }
        result = evaluate_subgoals("performance", data)
        self.assertGreaterEqual(result.overall_score, 0.8)

    def test_performance_no_cta(self):
        data = {
            "headline": "Some generic headline",
            "description": "Description here",
        }
        result = evaluate_subgoals("performance", data)
        sg = next(s for s in result.subgoals if s.name == "cta_strong")
        self.assertEqual(sg.status, SubgoalStatus.FAILED)


class TestSubgoalEvaluatorAnalytics(unittest.TestCase):
    """Analytics subgoal evaluation tests."""

    def test_analytics_perfect(self):
        from datetime import datetime, timezone

        data = {
            "metrics": ["visits", "conversion", "bounce_rate"],
            "trend_direction": "up",
            "recommendations": "Do more SEO",
            "data_date": datetime.now(timezone.utc).isoformat(),
            "charts": ["chart1"],
            "comparison_period": "last_30_days",
        }
        result = evaluate_subgoals("analytics", data)
        self.assertGreaterEqual(result.overall_score, 0.8)

    def test_analytics_stale_data(self):
        data = {
            "metrics": ["visits"],
            "data_date": "2024-01-01T00:00:00+00:00",
        }
        result = evaluate_subgoals("analytics", data)
        sg = next(s for s in result.subgoals if s.name == "data_fresh")
        self.assertLess(sg.score, 0.5)


class TestSubgoalEvaluatorTrend(unittest.TestCase):
    """Trend subgoal evaluation tests."""

    def test_trend_perfect(self):
        data = {
            "trend_name": "AI-powered shopping assistants",
            "confidence": 0.85,
            "sources": ["TechCrunch", "VC.ru"],
            "recommended_actions": ["Write article"],
            "category": "technology",
        }
        result = evaluate_subgoals("trend", data)
        self.assertGreaterEqual(result.overall_score, 0.85)

    def test_trend_low_confidence(self):
        data = {
            "trend_name": "Maybe something",
            "confidence": 0.3,
            "sources": ["Blog"],
        }
        result = evaluate_subgoals("trend", data)
        sg = next(s for s in result.subgoals if s.name == "confidence_score")
        self.assertLess(sg.score, 0.5)


class TestSubgoalEvaluatorEdgeCases(unittest.TestCase):
    """Edge cases and utilities."""

    def test_unknown_agent_type(self):
        result = evaluate_subgoals("unknown_type", {})
        self.assertEqual(result.overall_score, 0.0)
        self.assertEqual(len(result.subgoals), 0)

    def test_empty_result(self):
        result = evaluate_subgoals("seo", {})
        self.assertLess(result.overall_score, 0.5)
        self.assertGreater(result.failed_count, 0)

    def test_singleton(self):
        e1 = get_evaluator()
        e2 = get_evaluator()
        self.assertIs(e1, e2)

    def test_add_subgoal_runtime(self):
        evaluator = SubgoalEvaluator()
        evaluator.add_subgoal(
            "custom",
            {
                "name": "has_magic",
                "weight": 1.0,
                "check": lambda d: ("magic" in d, "magic check"),
                "binary": True,
            },
        )
        result = evaluator.evaluate("custom", {"magic": True})
        self.assertEqual(len(result.subgoals), 1)
        self.assertEqual(result.subgoals[0].name, "has_magic")

    def test_get_subgoal_names(self):
        evaluator = SubgoalEvaluator()
        names = evaluator.get_subgoal_names("seo")
        self.assertIn("title_exists", names)
        self.assertIn("meta_length", names)

    def test_merge_with_validation(self):
        evaluator = SubgoalEvaluator()
        seo = {
            "title": "Test",
            "meta_description": "Desc",
            "keywords": ["a"],
            "h1": "H1",
        }
        sg = evaluator.evaluate("seo", seo)

        # Mock validation result
        class MockVal:
            def to_dict(self):
                return {"status": "passed", "score": 0.9}

        merged = evaluator.merge_with_validation(sg, MockVal())
        self.assertIn("combined_score", merged)
        self.assertIn("validation", merged)
        self.assertAlmostEqual(merged["combined_score"], (sg.weighted_score + 0.9) / 2, places=2)

    def test_subgoal_result_bounds(self):
        sg = SubgoalResult("test", SubgoalStatus.PASSED, 1.5, 2.0)
        self.assertEqual(sg.score, 1.0)
        self.assertEqual(sg.weight, 1.0)

        sg2 = SubgoalResult("test", SubgoalStatus.FAILED, -0.5, -1.0)
        self.assertEqual(sg2.score, 0.0)
        self.assertEqual(sg2.weight, 0.0)


if __name__ == "__main__":
    unittest.main()
