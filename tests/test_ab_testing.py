#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для A/B тестирования промптов (P3-3).
"""

import sys
import unittest
import shutil
from pathlib import Path

sys.path.insert(0, '/opt/smart-skidka-agents')
sys.path.insert(0, '/opt/smart-skidka-agents/scripts')

from scripts.ab_testing import (
    PromptVariant,
    PromptVariantRegistry,
    ABTestEvaluator,
    ABTestResult,
)


class TestPromptVariant(unittest.TestCase):
    """Тесты PromptVariant dataclass."""

    def test_record_score(self):
        """Запись score обновляет avg."""
        v = PromptVariant("seo-agent", "v1", "prompt")
        v.record_score(0.8)
        self.assertEqual(v.experiment_count, 1)
        self.assertAlmostEqual(v.avg_score, 0.8)
        v.record_score(0.9)
        self.assertEqual(v.experiment_count, 2)
        self.assertAlmostEqual(v.avg_score, 0.85)

    def test_to_dict(self):
        """to_dict возвращает корректную структуру."""
        v = PromptVariant("seo-agent", "v1", "prompt", is_active=True)
        d = v.to_dict()
        self.assertEqual(d["agent_name"], "seo-agent")
        self.assertEqual(d["variant_name"], "v1")
        self.assertEqual(d["system_prompt"], "prompt")
        self.assertTrue(d["is_active"])


class TestPromptVariantRegistry(unittest.TestCase):
    """Тесты реестра вариантов."""

    def setUp(self):
        self.test_dir = Path("/tmp/test_ab_variants")
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.registry = PromptVariantRegistry(variants_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_add_and_get_variant(self):
        """Добавление и получение варианта."""
        v = self.registry.add_variant("seo-agent", "v1", "Test prompt")
        self.assertEqual(v.variant_name, "v1")
        self.assertEqual(v.system_prompt, "Test prompt")

        loaded = self.registry.get_variant("seo-agent", "v1")
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.system_prompt, "Test prompt")

    def test_duplicate_variant_raises(self):
        """Дубликат вызывает ValueError."""
        self.registry.add_variant("seo-agent", "v1", "Test")
        with self.assertRaises(ValueError):
            self.registry.add_variant("seo-agent", "v1", "Other")

    def test_select_variant_round_robin(self):
        """Round-robin при отсутствии активного варианта."""
        self.registry.add_variant("seo-agent", "v1", "P1")
        self.registry.add_variant("seo-agent", "v2", "P2")

        # Первый выбор — минимальный experiment_count
        v1 = self.registry.select_variant_for_run("seo-agent")
        self.assertIn(v1.variant_name, ["v1", "v2"])

    def test_select_active_with_exploration(self):
        """Активный вариант выбирается чаще (80%)."""
        self.registry.add_variant("seo-agent", "v1", "P1", is_active=True)
        self.registry.add_variant("seo-agent", "v2", "P2")

        active_count = 0
        for _ in range(100):
            v = self.registry.select_variant_for_run("seo-agent")
            if v.variant_name == "v1":
                active_count += 1

        # С высокой вероятностью v1 выбран > 60 раз из 100
        self.assertGreater(active_count, 60)

    def test_record_run_result(self):
        """Запись результата обновляет вариант."""
        self.registry.add_variant("seo-agent", "v1", "P")
        self.registry.record_run_result("seo-agent", "v1", 0.85)

        v = self.registry.get_variant("seo-agent", "v1")
        self.assertEqual(v.experiment_count, 1)
        self.assertEqual(v.avg_score, 0.85)

    def test_load_save_persistence(self):
        """Сохранение и загрузка из файла."""
        self.registry.add_variant("seo-agent", "v1", "P")
        self.registry.record_run_result("seo-agent", "v1", 0.9)

        # Новый registry — должен прочитать из файла
        registry2 = PromptVariantRegistry(variants_dir=self.test_dir)
        v = registry2.get_variant("seo-agent", "v1")
        self.assertIsNotNone(v)
        self.assertEqual(v.avg_score, 0.9)

    def test_get_active_variant(self):
        """Получение активного варианта."""
        self.registry.add_variant("seo-agent", "v1", "P1")
        self.assertIsNone(self.registry.get_active_variant("seo-agent"))

        self.registry.add_variant("seo-agent", "v2", "P2", is_active=True)
        active = self.registry.get_active_variant("seo-agent")
        self.assertEqual(active.variant_name, "v2")

    def test_list_all_variants(self):
        """Список всех вариантов."""
        self.registry.add_variant("seo-agent", "v1", "P")
        self.registry.add_variant("smm-agent", "v1", "P")
        all_v = self.registry.list_all_variants()
        self.assertEqual(len(all_v), 2)
        self.assertIn("seo-agent", all_v)
        self.assertIn("smm-agent", all_v)


class TestABTestEvaluator(unittest.TestCase):
    """Тесты оценки A/B тестов."""

    def setUp(self):
        self.test_dir = Path("/tmp/test_ab_eval")
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.registry = PromptVariantRegistry(variants_dir=self.test_dir)
        self.evaluator = ABTestEvaluator(self.registry)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_not_enough_variants(self):
        """Менее 2 вариантов — None."""
        self.registry.add_variant("seo-agent", "v1", "P")
        result = self.evaluator.evaluate("seo-agent")
        self.assertIsNone(result)

    def test_not_enough_runs(self):
        """Недостаточно запусков — None."""
        self.registry.add_variant("seo-agent", "v1", "P")
        self.registry.add_variant("seo-agent", "v2", "P")
        result = self.evaluator.evaluate("seo-agent")
        self.assertIsNone(result)

    def test_winner_selection(self):
        """Победитель выбирается по avg_score."""
        import scripts.ab_testing as ab
        original_min = ab.AB_TEST_MIN_RUNS
        ab.AB_TEST_MIN_RUNS = 2
        try:
            self.registry.add_variant("seo-agent", "v1", "P1")
            self.registry.add_variant("seo-agent", "v2", "P2")

            # v1 явно лучше
            for _ in range(5):
                self.registry.record_run_result("seo-agent", "v1", 0.95)
            for _ in range(5):
                self.registry.record_run_result("seo-agent", "v2", 0.70)

            result = self.evaluator.evaluate("seo-agent")
            self.assertIsNotNone(result)
            self.assertEqual(result.winner, "v1")
            self.assertGreater(result.confidence, 0)

            # Победитель активирован
            active = self.registry.get_active_variant("seo-agent")
            self.assertEqual(active.variant_name, "v1")
        finally:
            ab.AB_TEST_MIN_RUNS = original_min

    def test_no_winner_low_confidence(self):
        """При низкой уверенности победитель не выбирается."""
        import scripts.ab_testing as ab
        original_min = ab.AB_TEST_MIN_RUNS
        original_threshold = ab.AB_TEST_CONFIDENCE_THRESHOLD
        ab.AB_TEST_MIN_RUNS = 2
        ab.AB_TEST_CONFIDENCE_THRESHOLD = 0.99  # очень высокий порог
        try:
            self.registry.add_variant("seo-agent", "v1", "P1")
            self.registry.add_variant("seo-agent", "v2", "P2")

            for _ in range(5):
                self.registry.record_run_result("seo-agent", "v1", 0.81)
            for _ in range(5):
                self.registry.record_run_result("seo-agent", "v2", 0.80)

            result = self.evaluator.evaluate("seo-agent")
            self.assertIsNotNone(result)
            self.assertIsNone(result.winner)  # diff слишком мал
        finally:
            ab.AB_TEST_MIN_RUNS = original_min
            ab.AB_TEST_CONFIDENCE_THRESHOLD = original_threshold

    def test_evaluate_all(self):
        """Оценка всех агентов."""
        import scripts.ab_testing as ab
        original_min = ab.AB_TEST_MIN_RUNS
        ab.AB_TEST_MIN_RUNS = 2
        try:
            self.registry.add_variant("seo-agent", "v1", "P1")
            self.registry.add_variant("seo-agent", "v2", "P2")
            for _ in range(3):
                self.registry.record_run_result("seo-agent", "v1", 0.9)
                self.registry.record_run_result("seo-agent", "v2", 0.7)

            results = self.evaluator.evaluate_all()
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0].agent_name, "seo-agent")
        finally:
            ab.AB_TEST_MIN_RUNS = original_min


if __name__ == "__main__":
    unittest.main(verbosity=2)
