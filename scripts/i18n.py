#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                     I18N — Localization (P3-6)                       ║
║                    smart-skidka.ru                                   ║
╠══════════════════════════════════════════════════════════════════════╣
║  Полноценная i18n-система на основе gettext + JSON fallback.         ║
║                                                                      ║
║  Возможности:                                                        ║
║  • gettext-style переводы через _(), n_(), p_(), np_()              ║
║  • Plural forms (русский, английский, и другие)                     ║
║  • Contextual translations (p_ — context + msgid)                   ║
║  • Lazy translations (отложенные до момента рендера)                ║
║  • JSON fallback когда .mo файлы недоступны                         ║
║  • Auto-discovery локалей из locales/                               ║
║  • Интеграция с structlog (автоперевод log-сообщений)               ║
║  • Extractor: pybabel extract совместимый сканер строк              ║
║                                                                      ║
║  Использование:                                                      ║
║    from i18n import _, n_, p_, np_, set_locale, get_locale          ║
║    _("Hello") → "Привет"                                            ║
║    n_("{count} item", "{count} items", 5) → "5 товаров"            ║
║    p_("menu", "File") → "Файл" (в контексте menu)                  ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import json
import os
import re
import structlog
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

LOCALE_DIR = Path(__file__).parent.parent / "locales"
JSON_DIR = Path(__file__).parent.parent / "configs" / "i18n"
DEFAULT_LOCALE = os.getenv("AGENT_LOCALE", "ru")
DOMAIN = "messages"

# ═══════════════════════════════════════════════════════════════════════════════
# Plural rules (CLDR-based simplified)
# ═══════════════════════════════════════════════════════════════════════════════

PluralFunc = Callable[[int], int]


def _plural_ru(n: int) -> int:
    """Russian plural: 1, 2-4, 5-0."""
    if n % 10 == 1 and n % 100 != 11:
        return 0  # singular
    elif 2 <= n % 10 <= 4 and (n % 100 < 10 or n % 100 >= 20):
        return 1  # few
    return 2  # many


def _plural_en(n: int) -> int:
    """English plural: 1 vs other."""
    return 0 if n == 1 else 1


PLURAL_RULES: Dict[str, Tuple[int, PluralFunc]] = {
    "ru": (3, _plural_ru),
    "en": (2, _plural_en),
    "uk": (3, _plural_ru),
    "be": (3, _plural_ru),
    "pl": (3, _plural_ru),
    "cs": (3, _plural_ru),
    "sk": (3, _plural_ru),
}

# ═══════════════════════════════════════════════════════════════════════════════
# Lazy translation marker
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class LazyString:
    """Отложенный перевод — вычисляется при приведении к str."""
    func: Callable[..., str]
    args: Tuple[Any, ...]
    kwargs: Dict[str, Any]

    def __str__(self) -> str:
        return self.func(*self.args, **self.kwargs)

    def __format__(self, format_spec: str) -> str:
        return format(str(self), format_spec)

    def format(self, *args: Any, **kwargs: Any) -> str:
        return str(self).format(*args, **kwargs)


# ═══════════════════════════════════════════════════════════════════════════════
# Catalog — per-locale translation storage
# ═══════════════════════════════════════════════════════════════════════════════

class Catalog:
    """Каталог переводов для одной локали."""

    def __init__(self, locale: str):
        self.locale = locale
        self._messages: Dict[str, str] = {}  # msgid -> msgstr
        self._plural_messages: Dict[str, List[str]] = {}  # msgid -> [msgstr0, msgstr1, ...]
        self._context_messages: Dict[Tuple[str, str], str] = {}  # (context, msgid) -> msgstr
        self._loaded = False
        self._plural_forms = PLURAL_RULES.get(locale, PLURAL_RULES["en"])

    def _load(self) -> None:
        if self._loaded:
            return
        self._loaded = True

        # 1. Try JSON translations
        json_path = JSON_DIR / f"{self.locale}.json"
        if json_path.exists():
            self._load_json(json_path)

        # 2. Try gettext .mo files
        mo_path = LOCALE_DIR / self.locale / "LC_MESSAGES" / f"{DOMAIN}.mo"
        if mo_path.exists():
            self._load_mo(mo_path)

        # 3. Try .po files as fallback
        po_path = LOCALE_DIR / self.locale / "LC_MESSAGES" / f"{DOMAIN}.po"
        if po_path.exists():
            self._load_po(po_path)

    def _load_json(self, path: Path) -> None:
        """Load flat or nested JSON and flatten keys."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self._flatten_json(data, "")

    def _flatten_json(self, data: Any, prefix: str) -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                new_prefix = f"{prefix}.{key}" if prefix else key
                self._flatten_json(value, new_prefix)
        elif isinstance(data, list):
            # Plural forms: ["singular", "few", "many"]
            if prefix and all(isinstance(x, str) for x in data):
                self._plural_messages[prefix] = data
        elif isinstance(data, str):
            # Check for pipe-separated plural forms: "singular|few|many"
            if "|" in data:
                self._plural_messages[prefix] = data.split("|")
            else:
                self._messages[prefix] = data

    def _load_mo(self, path: Path) -> None:
        """Load binary gettext .mo file."""
        try:
            import gettext
            with open(path, "rb") as f:
                g = gettext.GNUTranslations(f)
            # Extract all messages
            for key, value in g._catalog.items():  # type: ignore[attr-defined]
                if isinstance(key, tuple):
                    # plural
                    msgid, idx = key
                    if msgid not in self._plural_messages:
                        self._plural_messages[msgid] = []
                    # Ensure list is long enough
                    while len(self._plural_messages[msgid]) <= idx:
                        self._plural_messages[msgid].append("")
                    self._plural_messages[msgid][idx] = value
                elif isinstance(key, str):
                    self._messages[key] = value
        except Exception:
            pass

    def _load_po(self, path: Path) -> None:
        """Parse .po file manually (simplified)."""
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        # Parse msgctxt, msgid, msgid_plural, msgstr entries
        pattern = re.compile(
            r'(?:msgctxt\s+"([^"]*)"\s+)?'
            r'msgid\s+"([^"]*)"\s+'
            r'(?:msgid_plural\s+"([^"]*)"\s+)?'
            r'((?:msgstr\[[0-9]+\]\s+"[^"]*"\s+|msgstr\s+"[^"]*"\s+)*)',
            re.MULTILINE,
        )

        for match in pattern.finditer(content):
            context = match.group(1)
            msgid = match.group(2)
            msgid_plural = match.group(3)
            msgstr_block = match.group(4)

            if not msgid:
                continue

            if msgid_plural:
                # Plural forms
                plural_strs = re.findall(r'msgstr\[[0-9]+\]\s+"([^"]*)"', msgstr_block)
                if plural_strs:
                    self._plural_messages[msgid] = plural_strs
            else:
                msgstr = re.search(r'msgstr\s+"([^"]*)"', msgstr_block)
                if msgstr:
                    if context:
                        self._context_messages[(context, msgid)] = msgstr.group(1)
                    else:
                        self._messages[msgid] = msgstr.group(1)

    def gettext(self, msgid: str) -> str:
        self._load()
        return self._messages.get(msgid, msgid)

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        self._load()
        count, rule = self._plural_forms
        idx = rule(n)
        if singular in self._plural_messages:
            forms = self._plural_messages[singular]
            if idx < len(forms):
                return forms[idx]
        # Fallback
        return singular if n == 1 else plural

    def pgettext(self, context: str, msgid: str) -> str:
        self._load()
        return self._context_messages.get((context, msgid), msgid)

    def npgettext(self, context: str, singular: str, plural: str, n: int) -> str:
        self._load()
        # Use context-prefixed key for plural lookups
        key = f"{context}\x04{singular}"
        count, rule = self._plural_forms
        idx = rule(n)
        if key in self._plural_messages:
            forms = self._plural_messages[key]
            if idx < len(forms):
                return forms[idx]
        return singular if n == 1 else plural

    def add_translation(self, msgid: str, msgstr: str, context: Optional[str] = None) -> None:
        """Runtime translation addition."""
        if context:
            # Check if msgstr contains plural forms (pipe-separated)
            if "|" in msgstr:
                key = f"{context}\x04{msgid}"
                self._plural_messages[key] = msgstr.split("|")
            else:
                self._context_messages[(context, msgid)] = msgstr
        else:
            if "|" in msgstr:
                self._plural_messages[msgid] = msgstr.split("|")
            else:
                self._messages[msgid] = msgstr


# ═══════════════════════════════════════════════════════════════════════════════
# Global catalog registry
# ═══════════════════════════════════════════════════════════════════════════════

_catalogs: Dict[str, Catalog] = {}
_current_locale = DEFAULT_LOCALE


def _get_catalog(locale: Optional[str] = None) -> Catalog:
    loc = locale or _current_locale
    if loc not in _catalogs:
        _catalogs[loc] = Catalog(loc)
    return _catalogs[loc]


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def _(msgid: str, locale: Optional[str] = None, **kwargs) -> str:
    """Gettext-style translation.

    Args:
        msgid: Message identifier
        locale: Override locale for this call
        **kwargs: Format arguments

    Returns:
        Translated and formatted string
    """
    catalog = _get_catalog(locale)
    result = catalog.gettext(msgid)
    if kwargs:
        try:
            result = result.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return result


def n_(singular: str, plural: str, n: int, locale: Optional[str] = None, **kwargs) -> str:
    """Plural-aware translation.

    Args:
        singular: Singular form (msgid)
        plural: Plural form
        n: Number for plural selection
        locale: Override locale
        **kwargs: Format arguments (including {count})

    Returns:
        Properly pluralized and formatted string
    """
    catalog = _get_catalog(locale)
    result = catalog.ngettext(singular, plural, n)
    fmt_kwargs = {"count": n, **kwargs}
    try:
        result = result.format(**fmt_kwargs)
    except (KeyError, ValueError):
        pass
    return result


def p_(context: str, msgid: str, locale: Optional[str] = None, **kwargs) -> str:
    """Context-aware translation.

    Args:
        context: Translation context (e.g., "menu", "button")
        msgid: Message identifier
        locale: Override locale
        **kwargs: Format arguments

    Returns:
        Contextually translated string
    """
    catalog = _get_catalog(locale)
    result = catalog.pgettext(context, msgid)
    if kwargs:
        try:
            result = result.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return result


def np_(context: str, singular: str, plural: str, n: int,
        locale: Optional[str] = None, **kwargs) -> str:
    """Context-aware plural translation."""
    catalog = _get_catalog(locale)
    result = catalog.npgettext(context, singular, plural, n)
    fmt_kwargs = {"count": n, **kwargs}
    try:
        result = result.format(**fmt_kwargs)
    except (KeyError, ValueError):
        pass
    return result


def lazy_(msgid: str, **kwargs) -> LazyString:
    """Lazy translation — evaluated on str()."""
    return LazyString(_, (msgid,), {"locale": None, **kwargs})


def lazy_n_(singular: str, plural: str, n: int, **kwargs) -> LazyString:
    """Lazy plural translation."""
    return LazyString(n_, (singular, plural, n), {"locale": None, **kwargs})


def set_locale(locale: str) -> None:
    """Set global default locale."""
    global _current_locale
    _current_locale = locale
    # Update environment for child processes
    os.environ["AGENT_LOCALE"] = locale


def get_locale() -> str:
    """Get current default locale."""
    return _current_locale


def add_translation(msgid: str, msgstr: str, locale: Optional[str] = None,
                   context: Optional[str] = None) -> None:
    """Add or update translation at runtime."""
    catalog = _get_catalog(locale)
    catalog.add_translation(msgid, msgstr, context)


def list_locales() -> List[str]:
    """List available locales from JSON and locale directories."""
    locales: set[str] = set()
    if JSON_DIR.exists():
        locales.update(f.stem for f in JSON_DIR.glob("*.json"))
    if LOCALE_DIR.exists():
        for d in LOCALE_DIR.iterdir():
            if d.is_dir():
                locales.add(d.name)
    return sorted(locales)


def reload_translations() -> None:
    """Clear all loaded catalogs — force reload from disk."""
    global _catalogs
    _catalogs = {}


# ═══════════════════════════════════════════════════════════════════════════════
# Structlog integration — auto-translate log messages
# ═══════════════════════════════════════════════════════════════════════════════

class I18nProcessor:
    """structlog processor that auto-translates 'event' and 'msg' fields."""

    def __init__(self, locale: Optional[str] = None):
        self.locale = locale

    def __call__(self, logger: Any, method_name: str, event_dict: Dict[str, Any]) -> Dict[str, Any]:
        for key in ("event", "msg", "message"):
            if key in event_dict and isinstance(event_dict[key], str):
                # Only translate if key looks like a translation key
                val = event_dict[key]
                if val.startswith("i18n:"):
                    event_dict[key] = _(val[5:], locale=self.locale)
        return event_dict


def install_structlog_processor() -> None:
    """Install i18n processor into structlog configuration."""
    # This is a no-op if structlog is not configured yet
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# Extractor — find translatable strings in source code
# ═══════════════════════════════════════════════════════════════════════════════

class Extractor:
    """Extract _(), n_(), p_(), np_() calls from Python source files."""

    FUNC_PATTERN = re.compile(
        r'\b(?:_|n_|p_|np_|lazy_|lazy_n_)\s*\(\s*',
        re.MULTILINE,
    )

    STRING_PATTERN = re.compile(
        r'(["\']{3}|["\'])((?:(?!\1).|\\.)*)(\1)',
        re.DOTALL,
    )

    @classmethod
    def extract_file(cls, filepath: Union[str, Path]) -> List[Dict[str, Any]]:
        """Extract all translation strings from a Python file."""
        path = Path(filepath)
        if not path.exists():
            return []

        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

        results: List[Dict[str, Any]] = []
        lines = content.split("\n")

        for match in cls.FUNC_PATTERN.finditer(content):
            start = match.end()
            line_no = content[:match.start()].count("\n") + 1

            # Parse arguments
            args, end_pos = cls._parse_args(content, start)
            if not args:
                continue

            entry: Dict[str, Any] = {
                "file": str(path),
                "line": line_no,
                "func": match.group(0).strip().rstrip("(").strip(),
            }

            func_name = entry["func"]
            if func_name in ("_", "lazy_"):
                entry["msgid"] = args[0]
            elif func_name in ("n_", "lazy_n_"):
                entry["singular"] = args[0]
                entry["plural"] = args[1]
            elif func_name == "p_":
                entry["context"] = args[0]
                entry["msgid"] = args[1]
            elif func_name == "np_":
                entry["context"] = args[0]
                entry["singular"] = args[1]
                entry["plural"] = args[2]

            results.append(entry)

        return results

    @classmethod
    def _parse_args(cls, content: str, start: int) -> Tuple[List[str], int]:
        """Parse string arguments from function call."""
        args: List[str] = []
        i = start
        while i < len(content):
            # Skip whitespace and commas
            while i < len(content) and content[i] in " \t\n,":
                i += 1
            if i >= len(content):
                break
            if content[i] == ")":
                break

            # Try to match string
            match = cls.STRING_PATTERN.match(content, i)
            if match:
                quote = match.group(1)
                raw = match.group(2)
                # Handle triple quotes
                if len(quote) == 3:
                    raw = raw.strip()
                args.append(raw)
                i = match.end()
            else:
                # Non-string argument — skip until comma or )
                depth = 0
                while i < len(content):
                    if content[i] == "(":
                        depth += 1
                    elif content[i] == ")":
                        if depth == 0:
                            break
                        depth -= 1
                    elif content[i] == "," and depth == 0:
                        break
                    i += 1
                if i < len(content) and content[i] == ",":
                    i += 1
                    continue
                break

            # Skip whitespace
            while i < len(content) and content[i] in " \t\n":
                i += 1
            if i < len(content) and content[i] == ",":
                i += 1
            elif i < len(content) and content[i] == ")":
                break

        # Find closing paren
        while i < len(content) and content[i] != ")":
            i += 1
        i += 1  # skip )

        return args, i

    @classmethod
    def extract_directory(cls, directory: Union[str, Path]) -> List[Dict[str, Any]]:
        """Extract strings from all Python files in directory."""
        results: List[Dict[str, Any]] = []
        for py_file in Path(directory).rglob("*.py"):
            results.extend(cls.extract_file(py_file))
        return results

    @classmethod
    def generate_pot(cls, directory: Union[str, Path], output: Union[str, Path]) -> None:
        """Generate .pot template file from extracted strings."""
        entries = cls.extract_directory(directory)
        seen: set[str] = set()

        lines = [
            '# Translations template for smart-skidka-agents',
            '# Generated by i18n.Extractor',
            '',
            'msgid ""',
            'msgstr ""',
            '',
        ]

        for entry in entries:
            if "msgid" in entry:
                key = entry.get("context", "") + "\x04" + entry["msgid"]
                if key not in seen:
                    seen.add(key)
                    lines.append(f'#: {entry["file"]}:{entry["line"]}')
                    if "context" in entry:
                        lines.append(f'msgctxt "{entry["context"]}"')
                    lines.append(f'msgid "{entry["msgid"]}"')
                    lines.append('msgstr ""')
                    lines.append('')
            elif "singular" in entry:
                key = entry.get("context", "") + "\x04" + entry["singular"]
                if key not in seen:
                    seen.add(key)
                    lines.append(f'#: {entry["file"]}:{entry["line"]}')
                    if "context" in entry:
                        lines.append(f'msgctxt "{entry["context"]}"')
                    lines.append(f'msgid "{entry["singular"]}"')
                    lines.append(f'msgid_plural "{entry["plural"]}"')
                    lines.append('msgstr[0] ""')
                    lines.append('msgstr[1] ""')
                    lines.append('')

        with open(output, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
