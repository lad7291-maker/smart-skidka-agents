#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for i18n module (P3-6) — full gettext-style localization."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import i18n


class TestI18NCore(unittest.TestCase):
    """Core translation functions: _, n_, p_, np_."""

    def setUp(self):
        i18n.reload_translations()
        i18n.set_locale("ru")

    def tearDown(self):
        i18n.reload_translations()
        i18n.set_locale("ru")

    # ─── _() gettext ───────────────────────────────────────────────────────

    def test_translate_ru(self):
        """Перевод на русском через _()."""
        result = i18n._("agent.status.running")
        self.assertEqual(result, "Запущен")

    def test_translate_en(self):
        """Перевод на английском через _()."""
        result = i18n._("agent.status.running", locale="en")
        self.assertEqual(result, "Running")

    def test_translate_with_format(self):
        """Перевод с форматированием kwargs."""
        result = i18n._("errors.config_not_found", path="/test/config.json")
        self.assertEqual(result, "Файл конфигурации не найден: /test/config.json")

    def test_translate_en_with_format(self):
        """Английский перевод с форматированием."""
        result = i18n._("errors.unknown_agent_type", locale="en", type="seo")
        self.assertEqual(result, "Unknown agent type: seo")

    def test_fallback_to_key(self):
        """Если ключ не найден — возвращается сам ключ."""
        result = i18n._("nonexistent.key.here")
        self.assertEqual(result, "nonexistent.key.here")

    # ─── n_() plural ───────────────────────────────────────────────────────

    def test_plural_ru_singular(self):
        """Русское склонение: 1 товар."""
        result = i18n.n_("{count} item", "{count} items", 1)
        self.assertEqual(result, "1 товар")

    def test_plural_ru_few(self):
        """Русское склонение: 2 товара."""
        result = i18n.n_("{count} item", "{count} items", 2)
        self.assertEqual(result, "2 товара")

    def test_plural_ru_many(self):
        """Русское склонение: 5 товаров."""
        result = i18n.n_("{count} item", "{count} items", 5)
        self.assertEqual(result, "5 товаров")

    def test_plural_ru_11_14(self):
        """Русское склонение: 11-14 товаров (исключение)."""
        result = i18n.n_("{count} item", "{count} items", 11)
        self.assertEqual(result, "11 товаров")
        result = i18n.n_("{count} item", "{count} items", 111)
        self.assertEqual(result, "111 товаров")

    def test_plural_en_singular(self):
        """Английское склонение: 1 item."""
        result = i18n.n_("{count} item", "{count} items", 1, locale="en")
        self.assertEqual(result, "1 item")

    def test_plural_en_plural(self):
        """Английское склонение: 5 items."""
        result = i18n.n_("{count} item", "{count} items", 5, locale="en")
        self.assertEqual(result, "5 items")

    def test_plural_fallback_no_data(self):
        """Fallback на правило языка если plural данных нет в JSON."""
        result = i18n.n_("unknown.singular", "unknown.plural", 1)
        self.assertEqual(result, "unknown.singular")
        result = i18n.n_("unknown.singular", "unknown.plural", 5)
        self.assertEqual(result, "unknown.plural")

    # ─── p_() context ──────────────────────────────────────────────────────

    def test_context_translation(self):
        """Контекстный перевод через p_()."""
        i18n.add_translation("Open", "Открыть", locale="ru", context="menu")
        i18n.add_translation("Open", "Открытый", locale="ru", context="state")
        self.assertEqual(i18n.p_("menu", "Open"), "Открыть")
        self.assertEqual(i18n.p_("state", "Open"), "Открытый")

    def test_context_fallback_to_msgid(self):
        """Если контекст не найден — fallback на msgid."""
        result = i18n.p_("nonexistent", "Some key")
        self.assertEqual(result, "Some key")

    # ─── np_() context + plural ────────────────────────────────────────────

    def test_context_plural_translation(self):
        """Контекстный plural перевод."""
        i18n.add_translation(
            "{count} file",
            "{count} файл|{count} файла|{count} файлов",
            locale="ru",
            context="document",
        )
        result = i18n.np_("document", "{count} file", "{count} files", 1)
        self.assertEqual(result, "1 файл")
        result = i18n.np_("document", "{count} file", "{count} files", 3)
        self.assertEqual(result, "3 файла")

    # ─── Locale management ─────────────────────────────────────────────────

    def test_set_locale(self):
        """Изменение глобальной локали."""
        i18n.set_locale("en")
        self.assertEqual(i18n.get_locale(), "en")
        result = i18n._("agent.status.paused")
        self.assertEqual(result, "Paused")

    def test_list_locales(self):
        """Список доступных локалей."""
        locales = i18n.list_locales()
        self.assertIn("ru", locales)
        self.assertIn("en", locales)

    def test_locale_from_env(self):
        """Локаль из переменной окружения AGENT_LOCALE."""
        old = os.environ.get("AGENT_LOCALE")
        try:
            os.environ["AGENT_LOCALE"] = "en"
            import importlib

            importlib.reload(i18n)
            self.assertEqual(i18n.get_locale(), "en")
        finally:
            if old is None:
                os.environ.pop("AGENT_LOCALE", None)
            else:
                os.environ["AGENT_LOCALE"] = old
            importlib.reload(i18n)

    # ─── Runtime operations ────────────────────────────────────────────────

    def test_add_translation_runtime(self):
        """Добавление перевода в runtime."""
        i18n.add_translation("runtime.test", "Runtime Value")
        result = i18n._("runtime.test")
        self.assertEqual(result, "Runtime Value")

    def test_reload_clears_cache(self):
        """reload_translations сбрасывает кэш."""
        i18n.add_translation("cache.test", "Cached")
        i18n._("cache.test")
        i18n.reload_translations()
        result = i18n._("cache.test")
        self.assertEqual(result, "cache.test")

    # ─── Lazy translations ─────────────────────────────────────────────────

    def test_lazy_translation(self):
        """LazyString вычисляется при str()."""
        lazy = i18n.lazy_("agent.status.running")
        self.assertIsInstance(lazy, i18n.LazyString)
        self.assertEqual(str(lazy), "Запущен")

    def test_lazy_plural_translation(self):
        """Lazy plural вычисляется при str()."""
        lazy = i18n.lazy_n_("{count} item", "{count} items", 5)
        self.assertEqual(str(lazy), "5 товаров")

    def test_lazy_format(self):
        """LazyString поддерживает .format()."""
        lazy = i18n.lazy_("errors.config_not_found", path="/x.json")
        self.assertEqual(lazy.format(), "Файл конфигурации не найден: /x.json")


class TestI18NExtractor(unittest.TestCase):
    """String extraction from Python source."""

    def test_extract_simple_underscore(self):
        """Извлечение _() вызовов."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write('x = _("Hello world")\n')
            f.write('y = _("Goodbye")\n')
            f.flush()
            path = f.name

        try:
            results = i18n.Extractor.extract_file(path)
            msgids = [r["msgid"] for r in results if "msgid" in r]
            self.assertIn("Hello world", msgids)
            self.assertIn("Goodbye", msgids)
        finally:
            os.unlink(path)

    def test_extract_plural(self):
        """Извлечение n_() вызовов."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write('x = n_("one item", "many items", count)\n')
            f.flush()
            path = f.name

        try:
            results = i18n.Extractor.extract_file(path)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["singular"], "one item")
            self.assertEqual(results[0]["plural"], "many items")
        finally:
            os.unlink(path)

    def test_extract_context(self):
        """Извлечение p_() вызовов."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write('x = p_("menu", "File")\n')
            f.flush()
            path = f.name

        try:
            results = i18n.Extractor.extract_file(path)
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["context"], "menu")
            self.assertEqual(results[0]["msgid"], "File")
        finally:
            os.unlink(path)

    def test_generate_pot(self):
        """Генерация .pot файла."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "test.py"
            src.write_text('x = _("Hello")\ny = n_("one", "many", n)\n', encoding="utf-8")
            pot = Path(tmpdir) / "messages.pot"

            i18n.Extractor.generate_pot(tmpdir, pot)
            content = pot.read_text(encoding="utf-8")
            self.assertIn('msgid "Hello"', content)
            self.assertIn('msgid "one"', content)
            self.assertIn('msgid_plural "many"', content)


class TestI18NStructlogIntegration(unittest.TestCase):
    """structlog processor integration."""

    def test_processor_translates_i18n_prefix(self):
        """Процессор переводит строки с префиксом i18n:."""
        processor = i18n.I18nProcessor(locale="ru")
        event_dict = {"event": "i18n:agent.status.running", "level": "info"}
        result = processor(None, "info", event_dict)
        self.assertEqual(result["event"], "Запущен")

    def test_processor_skips_regular_strings(self):
        """Процессор не трогает обычные строки."""
        processor = i18n.I18nProcessor(locale="ru")
        event_dict = {"event": "Regular log message", "level": "info"}
        result = processor(None, "info", event_dict)
        self.assertEqual(result["event"], "Regular log message")

    def test_processor_handles_msg_field(self):
        """Процессор переводит поле msg."""
        processor = i18n.I18nProcessor(locale="en")
        event_dict = {"msg": "i18n:agent.status.paused"}
        result = processor(None, "info", event_dict)
        self.assertEqual(result["msg"], "Paused")


if __name__ == "__main__":
    unittest.main()
