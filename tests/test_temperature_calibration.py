#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для автокалибровки temperature (P3-4).
"""

import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

from scripts.temperature_calibration import (
    DEFAULT_EMA_ALPHA,
    DEFAULT_EPSILON,
    DEFAULT_MIN_RUNS_PER_ARM,
    DEFAULT_TEMPERATURE_ARMS,
    AgentCalibration,
    TemperatureArm,
    TemperatureCalibrator,
)


class TestTemperatureArm(unittest.TestCase):
    """Тесты TemperatureArm."""

    def test_initial_state(self):
        """Начальное состояние arm."""
        arm = TemperatureArm(0.7)
        self.assertEqual(arm.temperature, 0.7)
        self.assertEqual(arm.ema_score, 0.0)
        self.assertEqual(arm.run_count, 0)

    def test_record_first_score(self):
        """Первый score устанавливает EMA."""
        arm = TemperatureArm(0.7)
        arm.record_score(0.8, alpha=0.3)
        self.assertEqual(arm.run_count, 1)
        self.assertAlmostEqual(arm.ema_score, 0.8)

    def test_record_ema_update(self):
        """EMA обновляется корректно."""
        arm = TemperatureArm(0.7)
        arm.record_score(0.8, alpha=0.3)
        arm.record_score(0.9, alpha=0.3)
        # EMA = 0.3 * 0.9 + 0.7 * 0.8 = 0.83
        self.assertAlmostEqual(arm.ema_score, 0.83, places=5)
        self.assertEqual(arm.run_count, 2)

    def test_last_used_updated(self):
        """last_used обновляется при записи."""
        arm = TemperatureArm(0.7)
        self.assertIsNone(arm.last_used)
        arm.record_score(0.8, alpha=0.3)
        self.assertIsNotNone(arm.last_used)


class TestAgentCalibration(unittest.TestCase):
    """Тесты AgentCalibration."""

    def test_default_arms_created(self):
        """По умолчанию создаются все arms."""
        cal = AgentCalibration("seo-agent")
        temps = [a.temperature for a in cal.arms]
        self.assertEqual(temps, DEFAULT_TEMPERATURE_ARMS)

    def test_forced_exploration(self):
        """Сначала идёт forced exploration (все arms)."""
        cal = AgentCalibration("seo-agent", min_runs_per_arm=1)
        selected = []
        for _ in range(len(DEFAULT_TEMPERATURE_ARMS) * 3):
            t = cal.select_temperature()
            selected.append(t)
            cal.record_result(t, 0.7)
        # Все arms должны быть выбраны хотя бы раз (forced exploration)
        self.assertEqual(len(set(selected)), len(DEFAULT_TEMPERATURE_ARMS))

    def test_exploitation_prefers_best(self):
        """Exploitation выбирает лучший arm."""
        cal = AgentCalibration("seo-agent", epsilon=0.0, min_runs_per_arm=1)
        # Запускаем каждый arm один раз
        for arm in cal.arms:
            cal.record_result(arm.temperature, arm.temperature)  # higher = better

        # Теперь exploitation должен выбрать 0.9
        best = cal.select_temperature()
        self.assertEqual(best, 0.9)

    def test_disabled_returns_default(self):
        """Отключенная калибровка возвращает default."""
        cal = AgentCalibration("seo-agent", enabled=False, default_temperature=0.65)
        t = cal.select_temperature()
        self.assertAlmostEqual(t, 0.65)

    def test_get_stats(self):
        """Статистика содержит все поля."""
        cal = AgentCalibration("seo-agent")
        cal.record_result(0.7, 0.8)
        stats = cal.get_stats()
        self.assertIn("agent_name", stats)
        self.assertIn("arms", stats)
        self.assertIn("best_arm", stats)
        self.assertEqual(stats["agent_name"], "seo-agent")

    def test_get_best_arm_none(self):
        """Без запусков best_arm = None."""
        cal = AgentCalibration("seo-agent")
        self.assertIsNone(cal._get_best_arm())

    def test_persistence_roundtrip(self):
        """Сериализация / десериализация."""
        cal = AgentCalibration("seo-agent")
        cal.record_result(0.7, 0.85)
        cal.record_result(0.8, 0.90)

        data = cal.to_dict()
        cal2 = AgentCalibration.from_dict(data)

        self.assertEqual(cal2.agent_name, "seo-agent")
        self.assertEqual(len(cal2.arms), len(cal.arms))
        # Найдём arm 0.7
        arm1 = next(a for a in cal.arms if a.temperature == 0.7)
        arm2 = next(a for a in cal2.arms if a.temperature == 0.7)
        self.assertEqual(arm1.run_count, arm2.run_count)
        self.assertAlmostEqual(arm1.ema_score, arm2.ema_score)


class TestTemperatureCalibrator(unittest.TestCase):
    """Тесты TemperatureCalibrator."""

    def setUp(self):
        self.test_dir = Path("/tmp/test_temp_calib")
        shutil.rmtree(self.test_dir, ignore_errors=True)
        self.calibrator = TemperatureCalibrator(calibration_dir=self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_load_new_calibration(self):
        """Загрузка несуществующей калибровки создаёт новую."""
        cal = self.calibrator.load_calibration("new-agent")
        self.assertEqual(cal.agent_name, "new-agent")
        self.assertTrue(cal.enabled)

    def test_save_and_load(self):
        """Сохранение и загрузка."""
        cal = self.calibrator.load_calibration("seo-agent")
        cal.record_result(0.7, 0.8)
        self.calibrator.save_calibration("seo-agent")

        cal2 = self.calibrator.load_calibration("seo-agent")
        arm = next(a for a in cal2.arms if a.temperature == 0.7)
        self.assertEqual(arm.run_count, 1)
        self.assertAlmostEqual(arm.ema_score, 0.8)

    def test_is_enabled(self):
        """Проверка включения."""
        self.assertTrue(self.calibrator.is_enabled("any-agent"))
        self.calibrator.disable("any-agent")
        self.assertFalse(self.calibrator.is_enabled("any-agent"))
        self.calibrator.enable("any-agent")
        self.assertTrue(self.calibrator.is_enabled("any-agent"))

    def test_select_and_record(self):
        """Полный цикл: select → record."""
        t = self.calibrator.select_temperature("seo-agent")
        self.assertIn(t, DEFAULT_TEMPERATURE_ARMS)
        self.calibrator.record_result("seo-agent", t, 0.85)

        cal = self.calibrator.load_calibration("seo-agent")
        arm = next(a for a in cal.arms if abs(a.temperature - t) < 0.001)
        self.assertEqual(arm.run_count, 1)

    def test_get_stats_all(self):
        """Статистика всех агентов."""
        self.calibrator.record_result("agent-a", 0.7, 0.8)
        self.calibrator.record_result("agent-b", 0.8, 0.9)
        stats = self.calibrator.get_stats()
        self.assertIn("agent-a", stats)
        self.assertIn("agent-b", stats)

    def test_reset(self):
        """Сброс калибровки."""
        self.calibrator.record_result("seo-agent", 0.7, 0.8)
        self.calibrator.reset("seo-agent")
        cal = self.calibrator.load_calibration("seo-agent")
        self.assertTrue(all(a.run_count == 0 for a in cal.arms))

    def test_record_disabled(self):
        """Запись для отключённого агента игнорируется."""
        self.calibrator.disable("seo-agent")
        self.calibrator.record_result("seo-agent", 0.7, 0.8)
        cal = self.calibrator.load_calibration("seo-agent")
        arm = next(a for a in cal.arms if a.temperature == 0.7)
        self.assertEqual(arm.run_count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
