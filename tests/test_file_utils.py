#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тесты для file_utils.py — безопасные операции с файлами.
"""

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, "/opt/smart-skidka-agents")
sys.path.insert(0, "/opt/smart-skidka-agents/scripts")

from scripts.actions.file_utils import (
    PRODUCTS_ALLOWED_FIELDS,
    PRODUCTS_PROTECTED_FIELDS,
    _backup_path,
    _resolve_within_site_root,
    git_commit_file,
    list_items,
    read_products,
    read_site_html,
    safe_read,
    safe_read_json,
    safe_write,
    safe_write_json,
    safe_write_with_git,
    validate_products_update,
    write_products,
    write_site_html,
)


class TestResolveWithinSiteRoot(unittest.TestCase):
    """Тесты защиты от path traversal."""

    @patch("scripts.actions.file_utils.SITE_ROOT", Path("/tmp/test_site"))
    def test_valid_path(self):
        site_root = Path("/tmp/test_site")
        site_root.mkdir(parents=True, exist_ok=True)
        path = site_root / "index.html"
        result = _resolve_within_site_root(path)
        self.assertEqual(result, path.resolve())

    @patch("scripts.actions.file_utils.SITE_ROOT", Path("/tmp/test_site"))
    def test_traversal_blocked(self):
        site_root = Path("/tmp/test_site")
        path = site_root / ".." / "etc" / "passwd"
        with self.assertRaises(ValueError) as ctx:
            _resolve_within_site_root(path)
        self.assertIn("Path traversal", str(ctx.exception))

    @patch("scripts.actions.file_utils.SITE_ROOT", Path("/tmp/test_site"))
    def test_absolute_outside_blocked(self):
        path = Path("/etc/passwd")
        with self.assertRaises(ValueError):
            _resolve_within_site_root(path)


class TestBackupPath(unittest.TestCase):
    """Тесты генерации пути бэкапа."""

    def test_backup_path_format(self):
        target = Path("/tmp/test.txt")
        backup = _backup_path(target)
        self.assertTrue(str(backup).startswith("/tmp/test.txt.bak."))
        self.assertRegex(str(backup), r"\.bak\.\d{8}_\d{6}$")


class TestSafeRead(unittest.TestCase):
    """Тесты safe_read."""

    @patch("scripts.actions.file_utils.SITE_ROOT", Path("/tmp/test_site"))
    def test_read_existing_file(self, tmp_path=None):
        site_root = Path("/tmp/test_site")
        site_root.mkdir(parents=True, exist_ok=True)
        test_file = site_root / "test_read.txt"
        test_file.write_text("Hello World", encoding="utf-8")

        result = safe_read(test_file)
        self.assertEqual(result, "Hello World")

        test_file.unlink(missing_ok=True)

    @patch("scripts.actions.file_utils.SITE_ROOT", Path("/tmp/test_site"))
    def test_read_missing_file(self):
        site_root = Path("/tmp/test_site")
        result = safe_read(site_root / "nonexistent.txt")
        self.assertEqual(result, "")

    @patch("scripts.actions.file_utils.SITE_ROOT", Path("/tmp/test_site"))
    def test_read_traversal_returns_empty(self):
        result = safe_read(Path("/etc/passwd"))
        self.assertEqual(result, "")


class TestSafeWrite(unittest.TestCase):
    """Тесты safe_write."""

    def setUp(self):
        self.site_root = Path("/tmp/test_site")
        self.site_root.mkdir(parents=True, exist_ok=True)
        self.patcher = patch("scripts.actions.file_utils.SITE_ROOT", self.site_root)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        for f in self.site_root.glob("test_*.txt"):
            f.unlink(missing_ok=True)
        for f in self.site_root.glob("test_*.txt.bak.*"):
            f.unlink(missing_ok=True)

    def test_write_new_file(self):
        path = self.site_root / "test_write.txt"
        result = safe_write(path, "Hello World")
        self.assertTrue(result)
        self.assertEqual(path.read_text(encoding="utf-8"), "Hello World")

    def test_write_with_backup(self):
        path = self.site_root / "test_backup.txt"
        path.write_text("Original", encoding="utf-8")

        result = safe_write(path, "Updated", make_backup=True)
        self.assertTrue(result)
        self.assertEqual(path.read_text(encoding="utf-8"), "Updated")

        backups = list(self.site_root.glob("test_backup.txt.bak.*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "Original")

    def test_write_without_backup(self):
        path = self.site_root / "test_no_backup.txt"
        path.write_text("Original", encoding="utf-8")

        result = safe_write(path, "Updated", make_backup=False)
        self.assertTrue(result)
        self.assertEqual(path.read_text(encoding="utf-8"), "Updated")

        backups = list(self.site_root.glob("test_no_backup.txt.bak.*"))
        self.assertEqual(len(backups), 0)

    def test_write_traversal_blocked(self):
        result = safe_write(Path("/etc/passwd"), "evil")
        self.assertFalse(result)


class TestSafeReadJson(unittest.TestCase):
    """Тесты safe_read_json."""

    @patch("scripts.actions.file_utils.SITE_ROOT", Path("/tmp/test_site"))
    def test_read_valid_json(self):
        site_root = Path("/tmp/test_site")
        site_root.mkdir(parents=True, exist_ok=True)
        path = site_root / "test.json"
        path.write_text('{"key": "value"}', encoding="utf-8")

        result = safe_read_json(path)
        self.assertEqual(result, {"key": "value"})
        path.unlink(missing_ok=True)

    @patch("scripts.actions.file_utils.SITE_ROOT", Path("/tmp/test_site"))
    def test_read_invalid_json(self):
        site_root = Path("/tmp/test_site")
        site_root.mkdir(parents=True, exist_ok=True)
        path = site_root / "bad.json"
        path.write_text("not json", encoding="utf-8")

        result = safe_read_json(path)
        self.assertEqual(result, {})
        path.unlink(missing_ok=True)

    @patch("scripts.actions.file_utils.SITE_ROOT", Path("/tmp/test_site"))
    def test_read_missing_file(self):
        site_root = Path("/tmp/test_site")
        result = safe_read_json(site_root / "missing.json")
        self.assertEqual(result, {})


class TestSafeWriteJson(unittest.TestCase):
    """Тесты safe_write_json."""

    def setUp(self):
        self.site_root = Path("/tmp/test_site")
        self.site_root.mkdir(parents=True, exist_ok=True)
        self.patcher = patch("scripts.actions.file_utils.SITE_ROOT", self.site_root)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        for f in self.site_root.glob("test_*.json"):
            f.unlink(missing_ok=True)

    def test_write_json(self):
        path = self.site_root / "test_write.json"
        result = safe_write_json(path, {"key": "value"})
        self.assertTrue(result)

        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data, {"key": "value"})


class TestReadProducts(unittest.TestCase):
    """Тесты read_products."""

    @patch("scripts.actions.file_utils.SITE_ROOT", Path("/tmp/test_site"))
    def test_read_dict(self):
        site_root = Path("/tmp/test_site")
        site_root.mkdir(parents=True, exist_ok=True)

        from scripts.actions.file_utils import PRODUCTS_JSON

        PRODUCTS_JSON.write_text('{"products": [{"id": 1}]}', encoding="utf-8")

        result = read_products()
        self.assertEqual(result, {"products": [{"id": 1}]})

    @patch("scripts.actions.file_utils.SITE_ROOT", Path("/tmp/test_site"))
    def test_read_list(self):
        site_root = Path("/tmp/test_site")
        site_root.mkdir(parents=True, exist_ok=True)

        from scripts.actions.file_utils import PRODUCTS_JSON

        PRODUCTS_JSON.write_text('[{"id": 1}]', encoding="utf-8")

        result = read_products()
        self.assertEqual(result, {"products": [{"id": 1}]})

    @patch("scripts.actions.file_utils.SITE_ROOT", Path("/tmp/test_site"))
    def test_read_invalid(self):
        site_root = Path("/tmp/test_site")
        site_root.mkdir(parents=True, exist_ok=True)

        from scripts.actions.file_utils import PRODUCTS_JSON

        PRODUCTS_JSON.write_text("not json", encoding="utf-8")

        result = read_products()
        self.assertEqual(result, {})


class TestValidateProductsUpdate(unittest.TestCase):
    """Тесты validate_products_update."""

    def test_allow_allowed_field(self):
        allowed, reason = validate_products_update("123", "description", "test")
        self.assertTrue(allowed)
        self.assertEqual(reason, "")

    def test_block_protected_field(self):
        allowed, reason = validate_products_update("123", "price", 999)
        self.assertFalse(allowed)
        self.assertIn("protected", reason)

    def test_block_unknown_field(self):
        allowed, reason = validate_products_update("123", "hacked_field", "evil")
        self.assertFalse(allowed)
        self.assertIn("allowed fields", reason)

    def test_no_overlap(self):
        overlap = PRODUCTS_ALLOWED_FIELDS & PRODUCTS_PROTECTED_FIELDS
        self.assertEqual(overlap, set())


class TestWriteProducts(unittest.TestCase):
    """Тесты write_products."""

    def setUp(self):
        self.site_root = Path("/tmp/test_site")
        self.site_root.mkdir(parents=True, exist_ok=True)
        self.patcher = patch("scripts.actions.file_utils.SITE_ROOT", self.site_root)
        self.patcher2 = patch("scripts.actions.file_utils.PRODUCTS_JSON", self.site_root / "products.json")
        self.patcher.start()
        self.patcher2.start()

    def tearDown(self):
        self.patcher.stop()
        self.patcher2.stop()
        (self.site_root / "products.json").unlink(missing_ok=True)

    def test_write_dict_with_products(self):
        result = write_products({"products": [{"id": 1}]})
        self.assertTrue(result)

        from scripts.actions.file_utils import PRODUCTS_JSON

        data = json.loads(PRODUCTS_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data, [{"id": 1}])  # Written as list

    def test_write_plain_dict(self):
        result = write_products({"key": "value"})
        self.assertTrue(result)

        from scripts.actions.file_utils import PRODUCTS_JSON

        data = json.loads(PRODUCTS_JSON.read_text(encoding="utf-8"))
        self.assertEqual(data, {"key": "value"})


class TestListItems(unittest.TestCase):
    """Тесты list_items."""

    @patch("scripts.actions.file_utils.ITEMS_DIR", Path("/tmp/test_site/item"))
    def test_empty_items_dir(self):
        site_root = Path("/tmp/test_site")
        items_dir = site_root / "item"
        items_dir.mkdir(parents=True, exist_ok=True)

        result = list_items()
        self.assertEqual(result, [])

    @patch("scripts.actions.file_utils.ITEMS_DIR", Path("/tmp/test_site/item"))
    def test_with_items(self):
        site_root = Path("/tmp/test_site")
        items_dir = site_root / "item"
        items_dir.mkdir(parents=True, exist_ok=True)

        (items_dir / "item1.html").write_text("test")
        (items_dir / "item2.html").write_text("test")

        result = list_items()
        self.assertEqual(result, ["item1.html", "item2.html"])

        # Cleanup
        (items_dir / "item1.html").unlink(missing_ok=True)
        (items_dir / "item2.html").unlink(missing_ok=True)


class TestGitCommitFile(unittest.TestCase):
    """Тесты git_commit_file."""

    @patch("subprocess.run")
    def test_git_not_installed(self, mock_run):
        mock_run.side_effect = FileNotFoundError()
        result = git_commit_file(Path("/tmp/test.txt"))
        self.assertTrue(result)  # Returns True when git not installed

    @patch("subprocess.run")
    def test_no_changes(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="")
        result = git_commit_file(Path("/tmp/test.txt"))
        self.assertTrue(result)

    @patch("subprocess.run")
    def test_with_changes(self, mock_run):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="M  test.txt\n"),  # status
            MagicMock(returncode=0),  # add
            MagicMock(returncode=0),  # commit
        ]
        result = git_commit_file(Path("/tmp/test.txt"))
        self.assertTrue(result)

    @patch("subprocess.run")
    def test_git_status_fails(self, mock_run):
        # Use a path inside the git repo
        repo_file = Path("/opt/smart-skidka-agents/test_git_file.txt")
        mock_run.side_effect = [
            MagicMock(returncode=1),  # status fails
        ]
        result = git_commit_file(repo_file)
        self.assertFalse(result)

    @patch("subprocess.run")
    def test_timeout(self, mock_run):
        from subprocess import TimeoutExpired

        repo_file = Path("/opt/smart-skidka-agents/test_git_file.txt")
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="M  test_git_file.txt\n"),  # status
            TimeoutExpired("git", 10),  # add times out
        ]
        result = git_commit_file(repo_file)
        self.assertFalse(result)


class TestSafeWriteWithGit(unittest.TestCase):
    """Тесты safe_write_with_git."""

    def setUp(self):
        self.site_root = Path("/tmp/test_site")
        self.site_root.mkdir(parents=True, exist_ok=True)
        self.patcher = patch("scripts.actions.file_utils.SITE_ROOT", self.site_root)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        for f in self.site_root.glob("test_git_*.txt"):
            f.unlink(missing_ok=True)

    @patch("scripts.actions.file_utils.git_commit_file")
    def test_write_and_git(self, mock_git):
        mock_git.return_value = True
        path = self.site_root / "test_git_write.txt"

        result = safe_write_with_git(path, "content", git_message="test commit")
        self.assertTrue(result)
        self.assertEqual(path.read_text(encoding="utf-8"), "content")
        mock_git.assert_called_once()

    @patch("scripts.actions.file_utils.git_commit_file")
    def test_write_fails_no_git(self, mock_git):
        path = Path("/etc/passwd")  # Will fail due to path traversal
        result = safe_write_with_git(path, "evil")
        self.assertFalse(result)
        mock_git.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
