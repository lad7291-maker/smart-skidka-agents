#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for secrets manager (P3-9)."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# Reset singleton before importing
import secrets_manager as _sm_module

_sm_module._manager = None

from secrets_manager import (
    AuditLog,
    CryptoEngine,
    Role,
    SecretLevel,
    SecretsManager,
    delete_secret,
    get_audit_entries,
    get_secret,
    list_secrets,
    migrate_env_secrets,
    set_secret,
)


class TestCryptoEngine(unittest.TestCase):
    """AES-256-GCM encryption tests."""

    def test_encrypt_decrypt_roundtrip(self):
        """Шифрование и дешифрование."""
        engine = CryptoEngine(b"x" * 32)
        plaintext = "my_secret_api_key_12345"
        salt, nonce, ciphertext = engine.encrypt(plaintext)
        decrypted = engine.decrypt(salt, nonce, ciphertext)
        self.assertEqual(decrypted, plaintext)

    def test_different_encryption_each_time(self):
        """Каждое шифрование даёт разный ciphertext."""
        engine = CryptoEngine(b"x" * 32)
        salt1, nonce1, ct1 = engine.encrypt("secret")
        salt2, nonce2, ct2 = engine.encrypt("secret")
        self.assertNotEqual(ct1, ct2)
        self.assertNotEqual(salt1, salt2)
        self.assertNotEqual(nonce1, nonce2)

    def test_tampered_ciphertext_fails(self):
        """Подмена ciphertext вызывает ошибку."""
        engine = CryptoEngine(b"x" * 32)
        salt, nonce, ciphertext = engine.encrypt("secret")
        # Tamper with ciphertext
        tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 0xFF])
        with self.assertRaises(Exception):
            engine.decrypt(salt, nonce, tampered)

    def test_different_keys_different_results(self):
        """Разные ключи дают разные ciphertext."""
        engine1 = CryptoEngine(b"a" * 32)
        engine2 = CryptoEngine(b"b" * 32)
        salt1, nonce1, ct1 = engine1.encrypt("secret")
        salt2, nonce2, ct2 = engine2.encrypt("secret")
        self.assertNotEqual(ct1, ct2)


class TestAuditLog(unittest.TestCase):
    """Audit logging tests."""

    def test_record_and_retrieve(self):
        """Запись и чтение audit entries."""
        log = AuditLog()
        log.record("read", "API_KEY", "admin", True)
        log.record("write", "API_KEY", "admin", True)
        entries = log.get_entries()
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["action"], "read")
        self.assertEqual(entries[1]["action"], "write")

    def test_filter_by_key(self):
        """Фильтрация audit по ключу."""
        log = AuditLog()
        log.record("read", "KEY_A", "admin", True)
        log.record("read", "KEY_B", "admin", True)
        entries = log.get_entries(key="KEY_A")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["key"], "KEY_A")

    def test_filter_by_action(self):
        """Фильтрация audit по действию."""
        log = AuditLog()
        log.record("read", "KEY", "admin", True)
        log.record("write", "KEY", "admin", True)
        entries = log.get_entries(action="write")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["action"], "write")

    def test_max_entries_limit(self):
        """Превышение лимита entries — старые удаляются."""
        log = AuditLog(max_entries=3)
        log.record("read", "K1", "admin", True)
        log.record("read", "K2", "admin", True)
        log.record("read", "K3", "admin", True)
        log.record("read", "K4", "admin", True)
        entries = log.get_entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["key"], "K2")


class TestSecretsManagerBasics(unittest.TestCase):
    """Basic secrets manager operations."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.secrets_file = Path(self.tmpdir.name) / "secrets.enc.json"
        self.master_key = b"0" * 32  # 32 bytes of '0' — valid UTF-8
        os.environ["SECRETS_PBKDF2_ITERATIONS"] = "1000"
        self.manager = SecretsManager(
            secrets_file=self.secrets_file,
            master_key=self.master_key,
        )

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("SECRETS_PBKDF2_ITERATIONS", None)

    def test_set_and_get(self):
        """Запись и чтение секрета."""
        success = self.manager.set("API_KEY", "secret123", role=Role.ADMIN)
        self.assertTrue(success)
        value = self.manager.get("API_KEY", role=Role.ADMIN)
        self.assertEqual(value, "secret123")

    def test_persistence(self):
        """Секреты сохраняются между сессиями."""
        self.manager.set("KEY1", "value1", role=Role.ADMIN)

        # Create new manager instance with same file
        manager2 = SecretsManager(
            secrets_file=self.secrets_file,
            master_key=self.master_key,
        )
        value = manager2.get("KEY1", role=Role.ADMIN)
        self.assertEqual(value, "value1")

    def test_file_is_encrypted(self):
        """Файл на диске содержит зашифрованные данные."""
        self.manager.set("SECRET", "my_value", role=Role.ADMIN)

        with open(self.secrets_file, "r") as f:
            data = f.read()

        self.assertIn("ciphertext", data)
        self.assertNotIn("my_value", data)

    def test_delete(self):
        """Удаление секрета."""
        self.manager.set("TO_DELETE", "value", role=Role.ADMIN)
        self.assertTrue(self.manager.delete("TO_DELETE", role=Role.ADMIN))
        self.assertIsNone(self.manager.get("TO_DELETE", role=Role.ADMIN))

    def test_delete_nonexistent(self):
        """Удаление несуществующего ключа."""
        self.assertFalse(self.manager.delete("NOPE", role=Role.ADMIN))

    def test_list_keys(self):
        """Список ключей без значений."""
        self.manager.set("KEY_A", "val_a", role=Role.ADMIN, level=SecretLevel.STANDARD)
        self.manager.set("KEY_B", "val_b", role=Role.ADMIN, level=SecretLevel.SENSITIVE)

        # Admin sees all
        keys = self.manager.list_keys(role=Role.ADMIN)
        self.assertEqual(len(keys), 2)

        # Read sees only standard
        keys = self.manager.list_keys(role=Role.READ)
        self.assertEqual(len(keys), 1)
        self.assertEqual(keys[0]["key"], "KEY_A")


class TestRoleBasedAccess(unittest.TestCase):
    """Role-based access control tests."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.secrets_file = Path(self.tmpdir.name) / "secrets.enc.json"
        self.master_key = b"0" * 32  # 32 bytes of '0' — valid UTF-8
        self.manager = SecretsManager(
            secrets_file=self.secrets_file,
            master_key=self.master_key,
        )
        self.manager.set("STANDARD_KEY", "std", role=Role.ADMIN, level=SecretLevel.STANDARD)
        self.manager.set("SENSITIVE_KEY", "sens", role=Role.ADMIN, level=SecretLevel.SENSITIVE)
        self.manager.set("CRITICAL_KEY", "crit", role=Role.ADMIN, level=SecretLevel.CRITICAL)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_read_can_access_standard(self):
        """READ роль видит STANDARD секреты."""
        val = self.manager.get("STANDARD_KEY", role=Role.READ)
        self.assertEqual(val, "std")

    def test_read_cannot_access_sensitive(self):
        """READ роль не видит SENSITIVE секреты."""
        val = self.manager.get("SENSITIVE_KEY", role=Role.READ)
        self.assertIsNone(val)

    def test_write_can_access_sensitive(self):
        """WRITE роль видит SENSITIVE секреты."""
        val = self.manager.get("SENSITIVE_KEY", role=Role.WRITE)
        self.assertEqual(val, "sens")

    def test_write_cannot_access_critical(self):
        """WRITE роль не видит CRITICAL секреты."""
        val = self.manager.get("CRITICAL_KEY", role=Role.WRITE)
        self.assertIsNone(val)

    def test_admin_can_access_all(self):
        """ADMIN роль видит все секреты."""
        self.assertEqual(self.manager.get("STANDARD_KEY", role=Role.ADMIN), "std")
        self.assertEqual(self.manager.get("SENSITIVE_KEY", role=Role.ADMIN), "sens")
        self.assertEqual(self.manager.get("CRITICAL_KEY", role=Role.ADMIN), "crit")

    def test_write_can_set_sensitive(self):
        """WRITE роль может записывать SENSITIVE."""
        success = self.manager.set("NEW_SENS", "val", role=Role.WRITE, level=SecretLevel.SENSITIVE)
        self.assertTrue(success)

    def test_write_cannot_set_critical(self):
        """WRITE роль не может записывать CRITICAL."""
        success = self.manager.set("NEW_CRIT", "val", role=Role.WRITE, level=SecretLevel.CRITICAL)
        self.assertFalse(success)

    def test_delete_requires_admin(self):
        """Удаление требует ADMIN."""
        self.assertFalse(self.manager.delete("STANDARD_KEY", role=Role.READ))
        self.assertFalse(self.manager.delete("STANDARD_KEY", role=Role.WRITE))
        self.assertTrue(self.manager.delete("STANDARD_KEY", role=Role.ADMIN))


class TestKeyRotation(unittest.TestCase):
    """Master key rotation tests."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.secrets_file = Path(self.tmpdir.name) / "secrets.enc.json"
        self.old_key = b"1" * 32  # 32 bytes of '1' — valid UTF-8
        os.environ["SECRETS_PBKDF2_ITERATIONS"] = "1000"
        self.manager = SecretsManager(
            secrets_file=self.secrets_file,
            master_key=self.old_key,
        )
        self.manager.set("KEY1", "value1", role=Role.ADMIN)
        self.manager.set("KEY2", "value2", role=Role.ADMIN)

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("SECRETS_PBKDF2_ITERATIONS", None)

    def test_rotate_key(self):
        """Ротация мастер-ключа."""
        new_key = b"new_master_key_32_bytes_long!"
        success = self.manager.rotate_key(new_key, role=Role.ADMIN)
        self.assertTrue(success)

        # Values still accessible
        self.assertEqual(self.manager.get("KEY1", role=Role.ADMIN), "value1")
        self.assertEqual(self.manager.get("KEY2", role=Role.ADMIN), "value2")

    def test_rotate_requires_admin(self):
        """Ротация требует ADMIN."""
        new_key = b"new_master_key_32_bytes_long!"
        success = self.manager.rotate_key(new_key, role=Role.WRITE)
        self.assertFalse(success)

    def test_old_key_cannot_decrypt_after_rotation(self):
        """Старый ключ не может дешифровать после ротации."""
        new_key = b"new_master_key_32_bytes_long!"
        self.manager.rotate_key(new_key, role=Role.ADMIN)

        # Old manager with old key fails
        with self.assertRaises(Exception):
            old_manager = SecretsManager(
                secrets_file=self.secrets_file,
                master_key=self.old_key,
            )


class TestAuditIntegration(unittest.TestCase):
    """Audit log integration tests."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.secrets_file = Path(self.tmpdir.name) / "secrets.enc.json"
        self.master_key = b"0" * 32  # 32 bytes of '0' — valid UTF-8
        os.environ["SECRETS_PBKDF2_ITERATIONS"] = "1000"
        self.manager = SecretsManager(
            secrets_file=self.secrets_file,
            master_key=self.master_key,
        )

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("SECRETS_PBKDF2_ITERATIONS", None)

    def test_read_logged(self):
        """Чтение логируется."""
        self.manager.set("KEY", "val", role=Role.ADMIN)
        self.manager.get("KEY", role=Role.ADMIN)
        entries = self.manager.get_audit_log(action="read")
        self.assertTrue(any(e["key"] == "KEY" and e["success"] for e in entries))

    def test_write_logged(self):
        """Запись логируется."""
        self.manager.set("KEY", "val", role=Role.ADMIN)
        entries = self.manager.get_audit_log(action="write")
        self.assertTrue(any(e["key"] == "KEY" and e["success"] for e in entries))

    def test_access_denied_logged(self):
        """Отказ доступа логируется."""
        self.manager.set("SENS", "val", role=Role.ADMIN, level=SecretLevel.SENSITIVE)
        self.manager.get("SENS", role=Role.READ)
        entries = self.manager.get_audit_log(action="read")
        self.assertTrue(any(e["key"] == "SENS" and not e["success"] for e in entries))


class TestConvenienceFunctions(unittest.TestCase):
    """Tests for module-level convenience functions."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.secrets_file = Path(self.tmpdir.name) / "secrets.enc.json"
        os.environ["SECRETS_FILE"] = str(self.secrets_file)
        os.environ["SECRETS_MASTER_KEY"] = "aa" * 32  # 64 hex chars = 32 bytes
        os.environ["SECRETS_PBKDF2_ITERATIONS"] = "1000"  # Fast for tests

        # Reset singleton AND remove any existing file from previous tests
        import secrets_manager

        secrets_manager._manager = None
        # Also remove production secrets file to avoid InvalidTag from stale file
        prod_file = Path("configs/secrets.enc.json")
        if prod_file.exists():
            prod_file.rename(prod_file.with_suffix(".json.bak.prod"))

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("SECRETS_FILE", None)
        os.environ.pop("SECRETS_MASTER_KEY", None)
        os.environ.pop("SECRETS_PBKDF2_ITERATIONS", None)
        import secrets_manager

        secrets_manager._manager = None
        # Restore production secrets file if backed up
        prod_bak = Path("configs/secrets.enc.json.bak.prod")
        if prod_bak.exists():
            prod_bak.rename(prod_bak.with_suffix(".json"))

    def test_get_secret_from_manager(self):
        """get_secret читает из encrypted storage."""
        set_secret("MY_KEY", "my_value", role="admin")
        val = get_secret("MY_KEY", role="admin")
        self.assertEqual(val, "my_value")

    def test_get_secret_fallback_to_env(self):
        """get_secret fallback на env если нет в storage и allow_env_fallback=True."""
        os.environ["ENV_ONLY_KEY"] = "env_value"
        val = get_secret("ENV_ONLY_KEY", allow_env_fallback=True)
        self.assertEqual(val, "env_value")
        del os.environ["ENV_ONLY_KEY"]

    def test_get_secret_no_fallback_by_default(self):
        """get_secret НЕ fallback на env по умолчанию."""
        os.environ["ENV_ONLY_KEY2"] = "env_value"
        val = get_secret("ENV_ONLY_KEY2")
        self.assertIsNone(val)
        del os.environ["ENV_ONLY_KEY2"]

    def test_get_secret_with_default(self):
        """get_secret возвращает default если нигде нет."""
        val = get_secret("NONEXISTENT", default="fallback")
        self.assertEqual(val, "fallback")

    def test_set_and_delete_secret(self):
        """set_secret и delete_secret."""
        set_secret("TEMP", "temp_val", role="admin")
        self.assertEqual(get_secret("TEMP", role="admin"), "temp_val")
        delete_secret("TEMP", role="admin")
        self.assertIsNone(get_secret("TEMP", role="admin"))

    def test_list_secrets(self):
        """list_secrets возвращает метаданные."""
        # Use unique keys to avoid conflicts with other tests
        set_secret("LIST_K1", "v1", role="admin", level="standard")
        set_secret("LIST_K2", "v2", role="admin", level="sensitive")
        keys = list_secrets(role="admin")
        # Filter to only our test keys
        our_keys = [k for k in keys if k["key"].startswith("LIST_")]
        self.assertEqual(len(our_keys), 2)
        self.assertTrue(all("key" in k and "level" in k for k in our_keys))

    def test_migrate_env_secrets(self):
        """migrate_env_secrets переносит из env."""
        os.environ["TEST_MIGRATE_KEY"] = "migrate_value"
        # Need to pass explicit keys since TEST_MIGRATE_KEY is not in default list
        from secrets_manager import Role, get_manager

        manager = get_manager()
        results = manager.migrate_from_env(keys=["TEST_MIGRATE_KEY"], role=Role.ADMIN)
        self.assertIn("TEST_MIGRATE_KEY", results)
        self.assertTrue(results["TEST_MIGRATE_KEY"])

        # Verify it's in storage
        val = get_secret("TEST_MIGRATE_KEY", role="admin")
        self.assertEqual(val, "migrate_value")
        del os.environ["TEST_MIGRATE_KEY"]

    def test_audit_entries(self):
        """get_audit_entries возвращает лог."""
        set_secret("AUDIT_KEY", "val", role="admin")
        entries = get_audit_entries(key="AUDIT_KEY", action="write")
        self.assertTrue(len(entries) > 0)


class TestEdgeCases(unittest.TestCase):
    """Edge cases and error handling."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.secrets_file = Path(self.tmpdir.name) / "secrets.enc.json"
        self.master_key = b"0" * 32  # 32 bytes of '0' — valid UTF-8
        os.environ["SECRETS_PBKDF2_ITERATIONS"] = "1000"
        self.manager = SecretsManager(
            secrets_file=self.secrets_file,
            master_key=self.master_key,
        )

    def tearDown(self):
        self.tmpdir.cleanup()
        os.environ.pop("SECRETS_PBKDF2_ITERATIONS", None)

    def test_empty_value(self):
        """Пустое значение."""
        self.manager.set("EMPTY", "", role=Role.ADMIN)
        self.assertEqual(self.manager.get("EMPTY", role=Role.ADMIN), "")

    def test_unicode_value(self):
        """Unicode значение."""
        self.manager.set("UNI", "Привет мир! 🌍", role=Role.ADMIN)
        self.assertEqual(self.manager.get("UNI", role=Role.ADMIN), "Привет мир! 🌍")

    def test_large_value(self):
        """Большое значение."""
        large = "x" * 10000
        self.manager.set("LARGE", large, role=Role.ADMIN)
        self.assertEqual(self.manager.get("LARGE", role=Role.ADMIN), large)

    def test_special_chars_in_key(self):
        """Специальные символы в ключе."""
        self.manager.set("key-with.dots_and_123", "val", role=Role.ADMIN)
        self.assertEqual(self.manager.get("key-with.dots_and_123", role=Role.ADMIN), "val")

    def test_overwrite_existing(self):
        """Перезапись существующего ключа."""
        self.manager.set("KEY", "old", role=Role.ADMIN)
        self.manager.set("KEY", "new", role=Role.ADMIN)
        self.assertEqual(self.manager.get("KEY", role=Role.ADMIN), "new")

    def test_nonexistent_key_returns_none(self):
        """Несуществующий ключ возвращает None."""
        self.assertIsNone(self.manager.get("NO_SUCH_KEY", role=Role.ADMIN))


if __name__ == "__main__":
    unittest.main()
