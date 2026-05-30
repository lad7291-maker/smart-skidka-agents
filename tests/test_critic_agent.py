#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Critic Agent (P3-10).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.critic_agent import (
    CriticAgent,
    CriticFinding,
    CriticReport,
    CriticSeverity,
    EscalationQualityAssessor,
    HallucinationDetector,
    PlanAdherenceChecker,
    audit_cycle,
    get_critic,
)


class TestPlanAdherenceChecker(unittest.TestCase):
    def setUp(self):
        self.checker = PlanAdherenceChecker()

    def test_all_fields_present(self):
        result = {
            "agent_name": "seo-agent",
            "data": {
                "title": "Best SEO Title",
                "meta_description": "A great meta description here",
                "keywords": ["seo", "marketing"],
                "h1": "Main Heading",
            },
        }
        findings = self.checker.check("seo-agent", result)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, CriticSeverity.INFO)
        self.assertIn("присутствуют", findings[0].message)

    def test_missing_fields(self):
        result = {
            "agent_name": "seo-agent",
            "data": {"title": "Only title"},
        }
        findings = self.checker.check("seo-agent", result)
        errors = [f for f in findings if f.severity == CriticSeverity.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("meta_description", errors[0].message)
        self.assertIn("keywords", errors[0].message)
        self.assertIn("h1", errors[0].message)

    def test_empty_fields(self):
        result = {
            "agent_name": "seo-agent",
            "data": {
                "title": "T",
                "meta_description": "",
                "keywords": [],
                "h1": "  ",
            },
        }
        findings = self.checker.check("seo-agent", result)
        warnings = [f for f in findings if f.severity == CriticSeverity.WARNING]
        self.assertEqual(len(warnings), 1)
        self.assertIn("title", warnings[0].message)

    def test_unknown_agent_type(self):
        result = {"agent_name": "unknown-agent", "data": {"foo": "bar"}}
        findings = self.checker.check("unknown-agent", result)
        self.assertEqual(len(findings), 0)

    def test_result_without_data_key(self):
        """Если result — dict без data, используем сам result."""
        result = {
            "title": "Best SEO Title",
            "meta_description": "A great meta description here",
            "keywords": ["seo", "marketing"],
            "h1": "Main Heading",
        }
        findings = self.checker.check("seo-agent", result)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, CriticSeverity.INFO)


class TestHallucinationDetector(unittest.TestCase):
    def setUp(self):
        self.detector = HallucinationDetector()

    def test_no_hallucination(self):
        result = {
            "data": {
                "title": "Real Product Title",
                "metrics": {"clicks": 150, "ctr": 2.5},
            }
        }
        findings = self.detector.check("seo-agent", result)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, CriticSeverity.INFO)

    def test_placeholder_url(self):
        result = {"data": {"source": "https://example.com/product"}}
        findings = self.detector.check("content-agent", result)
        warnings = [f for f in findings if f.severity == CriticSeverity.WARNING]
        self.assertTrue(any("placeholder_url" in f.details.get("pattern", "") for f in warnings))

    def test_lorem_ipsum(self):
        result = {"data": {"body": "Lorem ipsum dolor sit amet"}}
        findings = self.detector.check("content-agent", result)
        warnings = [f for f in findings if f.severity == CriticSeverity.WARNING]
        self.assertTrue(any("lorem_ipsum" in f.details.get("pattern", "") for f in warnings))

    def test_todo_marker(self):
        result = {"data": {"description": "Need to add CTA here TODO"}}
        findings = self.detector.check("performance-agent", result)
        warnings = [f for f in findings if f.severity == CriticSeverity.WARNING]
        self.assertTrue(any("placeholder_marker" in f.details.get("pattern", "") for f in warnings))

    def test_unrealistic_number(self):
        result = {"data": {"budget": 10_000_000_000}}
        findings = self.detector.check("performance-agent", result)
        warnings = [f for f in findings if f.severity == CriticSeverity.WARNING]
        self.assertTrue(any("числовые" in f.message for f in warnings))

    def test_contradiction_keywords_count(self):
        result = {"data": {"keywords": ["a", "b", "c"], "keywords_count": 5}}
        findings = self.detector.check("seo-agent", result)
        errors = [f for f in findings if f.severity == CriticSeverity.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("keywords_count", errors[0].message)


class TestEscalationQualityAssessor(unittest.TestCase):
    def setUp(self):
        self.assessor = EscalationQualityAssessor()

    def test_success_no_escalation_needed(self):
        result = {"success": True, "data": {"title": "OK"}}
        findings = self.assessor.check("seo-agent", result)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, CriticSeverity.INFO)

    def test_error_without_description(self):
        result = {"success": False, "error": "", "retry_attempts": 0}
        findings = self.assessor.check("seo-agent", result)
        errors = [f for f in findings if f.severity == CriticSeverity.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("без описания", errors[0].message)

    def test_error_without_retry(self):
        result = {"success": False, "error": "Connection timeout", "retry_attempts": 0}
        findings = self.assessor.check("seo-agent", result)
        warnings = [f for f in findings if f.severity == CriticSeverity.WARNING]
        self.assertTrue(any("без попытки retry" in f.message for f in warnings))

    def test_retry_exhausted(self):
        result = {
            "success": False,
            "error": "Persistent failure",
            "retry_attempts": 3,
        }
        findings = self.assessor.check("seo-agent", result)
        errors = [f for f in findings if f.severity == CriticSeverity.ERROR]
        self.assertTrue(any("Исчерпаны" in f.message for f in errors))

    def test_retry_success(self):
        result = {
            "success": False,
            "error": "Temporary glitch",
            "retry_attempts": 1,
        }
        findings = self.assessor.check("seo-agent", result)
        infos = [f for f in findings if f.severity == CriticSeverity.INFO]
        self.assertTrue(any("Retry сработал" in f.message for f in infos))

    def test_repeated_errors(self):
        prev = [
            {"error": "Connection timeout"},
            {"error": "Connection timeout again"},
        ]
        result = {"success": False, "error": "Connection timeout", "retry_attempts": 0}
        findings = self.assessor.check("seo-agent", result, prev)
        errors = [f for f in findings if f.severity == CriticSeverity.ERROR]
        self.assertTrue(any("Повторяющаяся" in f.message for f in errors))


class TestCriticAgent(unittest.TestCase):
    def setUp(self):
        self.critic = CriticAgent()

    def test_audit_cycle_perfect(self):
        cycle_results = [
            {
                "agent_name": "seo-agent",
                "success": True,
                "data": {
                    "title": "Best SEO Title",
                    "meta_description": "A great meta description here",
                    "keywords": ["seo", "marketing"],
                    "h1": "Main Heading",
                },
            }
        ]
        report = self.critic.audit_cycle("cycle-001", cycle_results)
        self.assertEqual(report.cycle_id, "cycle-001")
        self.assertGreater(report.overall_score, 0.9)
        self.assertEqual(report.summary["agents_audited"], 1)

    def test_audit_cycle_with_errors(self):
        cycle_results = [
            {
                "agent_name": "seo-agent",
                "success": False,
                "error": "Connection timeout",
                "retry_attempts": 0,
                "data": {"title": "T"},
            }
        ]
        report = self.critic.audit_cycle("cycle-002", cycle_results)
        self.assertLess(report.overall_score, 1.0)
        errors = [f for f in report.findings if f.severity == CriticSeverity.ERROR]
        self.assertGreater(len(errors), 0)

    def test_audit_multiple_agents(self):
        cycle_results = [
            {
                "agent_name": "seo-agent",
                "success": True,
                "data": {
                    "title": "SEO Title",
                    "meta_description": "Meta desc",
                    "keywords": ["k1"],
                    "h1": "H1",
                },
            },
            {
                "agent_name": "smm-agent",
                "success": True,
                "data": {
                    "content": "Great post content here",
                    "hashtags": ["#marketing"],
                    "platform": "instagram",
                },
            },
        ]
        report = self.critic.audit_cycle("cycle-003", cycle_results)
        self.assertEqual(report.summary["agents_audited"], 2)
        self.assertIn("seo-agent", report.summary["agent_scores"])
        self.assertIn("smm-agent", report.summary["agent_scores"])

    def test_audit_agent_direct(self):
        result = {
            "agent_name": "seo-agent",
            "success": True,
            "data": {
                "title": "Title",
                "meta_description": "Meta",
                "keywords": ["k"],
                "h1": "H1",
            },
        }
        findings = self.critic.audit_agent("seo-agent", result)
        self.assertGreater(len(findings), 0)

    def test_overall_score_calculation(self):
        findings = [
            CriticFinding("test", CriticSeverity.INFO, "ok", "a"),
            CriticFinding("test", CriticSeverity.INFO, "ok2", "a"),
            CriticFinding("test", CriticSeverity.WARNING, "warn", "a"),
        ]
        score = self.critic._calculate_overall_score(findings, [{}])
        self.assertAlmostEqual(score, 0.99, places=2)

    def test_score_with_critical(self):
        findings = [
            CriticFinding("test", CriticSeverity.CRITICAL, "bad", "a"),
        ]
        score = self.critic._calculate_overall_score(findings, [{}])
        self.assertAlmostEqual(score, 0.70, places=2)

    def test_findings_by_severity(self):
        report = CriticReport(
            cycle_id="c1",
            overall_score=0.5,
            findings=[
                CriticFinding("a", CriticSeverity.ERROR, "e1", "ag1"),
                CriticFinding("b", CriticSeverity.WARNING, "w1", "ag1"),
                CriticFinding("c", CriticSeverity.ERROR, "e2", "ag2"),
            ],
        )
        self.assertEqual(len(report.findings_by_severity(CriticSeverity.ERROR)), 2)
        self.assertEqual(len(report.findings_by_severity(CriticSeverity.WARNING)), 1)
        self.assertEqual(len(report.findings_by_severity(CriticSeverity.INFO)), 0)

    def test_findings_for_agent(self):
        report = CriticReport(
            cycle_id="c1",
            overall_score=0.5,
            findings=[
                CriticFinding("a", CriticSeverity.ERROR, "e1", "ag1"),
                CriticFinding("b", CriticSeverity.WARNING, "w1", "ag2"),
            ],
        )
        self.assertEqual(len(report.findings_for_agent("ag1")), 1)
        self.assertEqual(len(report.findings_for_agent("ag2")), 1)
        self.assertEqual(len(report.findings_for_agent("ag3")), 0)

    def test_report_to_dict(self):
        report = audit_cycle("cycle-004", [
            {
                "agent_name": "seo-agent",
                "success": True,
                "data": {
                    "title": "T",
                    "meta_description": "M",
                    "keywords": ["k"],
                    "h1": "H",
                },
            }
        ])
        d = report.to_dict()
        self.assertEqual(d["cycle_id"], "cycle-004")
        self.assertIn("overall_score", d)
        self.assertIn("findings", d)
        self.assertIn("summary", d)
        self.assertIn("timestamp", d)

    def test_singleton(self):
        c1 = get_critic()
        c2 = get_critic()
        self.assertIs(c1, c2)

    def test_empty_cycle(self):
        report = self.critic.audit_cycle("cycle-empty", [])
        self.assertEqual(report.overall_score, 1.0)
        self.assertEqual(len(report.findings), 0)

    def test_previous_cycles_history(self):
        cycle_results = [
            {
                "agent_name": "seo-agent",
                "success": False,
                "error": "Same error",
                "retry_attempts": 0,
                "data": {"title": "T", "meta_description": "M", "keywords": ["k"], "h1": "H"},
            }
        ]
        previous = [[
            {"agent_name": "seo-agent", "error": "Same error"},
            {"agent_name": "seo-agent", "error": "Same error again"},
        ]]
        report = self.critic.audit_cycle("cycle-005", cycle_results, previous)
        repeated = [f for f in report.findings if "Повторяющаяся" in f.message]
        self.assertEqual(len(repeated), 1)


class TestCriticSeverityOrdering(unittest.TestCase):
    def test_severity_values(self):
        self.assertEqual(CriticSeverity.INFO.value, "info")
        self.assertEqual(CriticSeverity.WARNING.value, "warning")
        self.assertEqual(CriticSeverity.ERROR.value, "error")
        self.assertEqual(CriticSeverity.CRITICAL.value, "critical")


if __name__ == "__main__":
    unittest.main()
