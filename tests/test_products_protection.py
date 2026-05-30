#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для защиты products.json (P1-9).
"""

import sys
import unittest

sys.path.insert(0, '/opt/smart-skidka-agents')
sys.path.insert(0, '/opt/smart-skidka-agents/scripts')

from scripts.actions.file_utils import (
    validate_products_update,
    PRODUCTS_ALLOWED_FIELDS,
    PRODUCTS_PROTECTED_FIELDS,
)


class TestProductsProtection(unittest.TestCase):
    """Тесты whitelist-защиты products.json."""

    def test_allowed_fields_list(self):
        """Разрешённые поля определены."""
        self.assertIn("description", PRODUCTS_ALLOWED_FIELDS)
        self.assertIn("badge", PRODUCTS_ALLOWED_FIELDS)
        self.assertIn("promo_code", PRODUCTS_ALLOWED_FIELDS)

    def test_protected_fields_list(self):
        """Защищённые поля определены."""
        self.assertIn("id", PRODUCTS_PROTECTED_FIELDS)
        self.assertIn("price", PRODUCTS_PROTECTED_FIELDS)
        self.assertIn("name", PRODUCTS_PROTECTED_FIELDS)

    def test_allow_description(self):
        """description разрешено."""
        allowed, reason = validate_products_update("123", "description", "test")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_allow_badge(self):
        """badge разрешено."""
        allowed, reason = validate_products_update("123", "badge", "🔥 Тренд")
        self.assertTrue(allowed)

    def test_allow_promo_code(self):
        """promo_code разрешено."""
        allowed, reason = validate_products_update("123", "promo_code", "SALE2026")
        self.assertTrue(allowed)

    def test_block_price(self):
        """price защищено."""
        allowed, reason = validate_products_update("123", "price", 999)
        self.assertFalse(allowed)
        self.assertIn("protected", reason.lower())

    def test_block_name(self):
        """name защищено."""
        allowed, reason = validate_products_update("123", "name", "Hacked Product")
        self.assertFalse(allowed)

    def test_block_id(self):
        """id защищено."""
        allowed, reason = validate_products_update("123", "id", "999")
        self.assertFalse(allowed)

    def test_block_unknown_field(self):
        """Неизвестное поле блокируется."""
        allowed, reason = validate_products_update("123", "hacked_field", "evil")
        self.assertFalse(allowed)
        self.assertIn("not in allowed", reason.lower())

    def test_no_overlap_allowed_protected(self):
        """Разрешённые и защищённые поля не пересекаются."""
        overlap = PRODUCTS_ALLOWED_FIELDS & PRODUCTS_PROTECTED_FIELDS
        self.assertEqual(overlap, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
