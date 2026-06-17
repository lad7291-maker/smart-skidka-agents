#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════╗
║                    SECRETS MANAGER (P3-9)                            ║
║                    smart-skidka.ru                                   ║
╠══════════════════════════════════════════════════════════════════════╣
║  Управление секретами: шифрование, ротация, доступ по ролям.         ║
║                                                                      ║
║  Возможности:                                                        ║
║  • AES-256-GCM шифрование секретов в файле                           ║
║  • Master key из env / файла / prompt (fallback)                     ║
║  • Автодешифровка при чтении, шифрование при записи                  ║
║  • Ротация ключей (re-encrypt all secrets)                           ║
║  • Ролевая модель: read/write/admin                                  ║
║  • Интеграция с os.getenv() — drop-in replacement                     ║
║  • Audit log: кто, когда, какой ключ читал/писал                     ║
║                                                                      ║
║  Использование:                                                      ║
║    from secrets_manager import get_secret, set_secret                ║
║    api_key = get_secret("LLM_API_KEY")                               ║
║    set_secret("NEW_KEY", "value", role="admin")                      ║
╚══════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import structlog
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False

logger = structlog.get_logger("secrets_manager")


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

SECRETS_FILE = Path(os.getenv("SECRETS_FILE", "configs/secrets.enc.json"))
MASTER_KEY_ENV = "SECRETS_MASTER_KEY"
MASTER_KEY_FILE = Path(os.getenv("SECRETS_MASTER_KEY_FILE", "configs/.master.key"))
SALT_LENGTH = 32
NONCE_LENGTH = 12
ITERATIONS = int(os.getenv("SECRETS_PBKDF2_ITERATIONS", "480000"))  # OWASP recommendation for PBKDF2
KEY_LENGTH = 32  # 256 bits


# ═══════════════════════════════════════════════════════════════════════════════
# Role-based access control
# ═══════════════════════════════════════════════════════════════════════════════

class Role(str, Enum):
    READ = "read"       # Can read non-sensitive secrets
    WRITE = "write"     # Can read/write secrets
    ADMIN = "admin"     # Full access including master key ops


class SecretLevel(str, Enum):
    STANDARD = "standard"   # Regular config values
    SENSITIVE = "sensitive" # API keys, tokens
    CRITICAL = "critical"   # Master key, DB credentials


ROLE_ACCESS: Dict[Role, Set[SecretLevel]] = {
    Role.READ: {SecretLevel.STANDARD},
    Role.WRITE: {SecretLevel.STANDARD, SecretLevel.SENSITIVE},
    Role.ADMIN: {SecretLevel.STANDARD, SecretLevel.SENSITIVE, SecretLevel.CRITICAL},
}


# ═══════════════════════════════════════════════════════════════════════════════
# Audit logging
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class AuditEntry:
    timestamp: str
    action: str  # "read", "write", "rotate", "delete"
    key: str
    role: str
    success: bool
    error: Optional[str] = None


class AuditLog:
    """In-memory audit log with file persistence."""

    def __init__(self, max_entries: int = 1000,
                 audit_file: Optional[Path] = None):
        self._entries: List[AuditEntry] = []
        self._max_entries = max_entries
        # P1-17: Персистентный audit log
        self._audit_file = audit_file or Path(
            os.getenv("AUDIT_LOG_FILE", "logs/audit.log")
        )
        self._lock = asyncio.Lock()
        self._load_from_file()

    def _load_from_file(self) -> None:
        """P1-17: Загружает audit entries из файла при инициализации."""
        if not self._audit_file.exists():
            return
        try:
            with open(self._audit_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        self._entries.append(AuditEntry(
                            timestamp=data.get("timestamp", ""),
                            action=data.get("action", ""),
                            key=data.get("key", ""),
                            role=data.get("role", ""),
                            success=data.get("success", False),
                            error=data.get("error"),
                        ))
                    except (json.JSONDecodeError, KeyError):
                        continue
            # Ограничиваем размер
            if len(self._entries) > self._max_entries:
                self._entries = self._entries[-self._max_entries:]
        except Exception as e:
            logger.warning("Failed to load audit log", error=str(e))

    async def _append_to_file(self, entry: AuditEntry) -> None:
        """P1-17: Дописывает entry в audit log файл."""
        try:
            self._audit_file.parent.mkdir(parents=True, exist_ok=True)
            line = json.dumps({
                "timestamp": entry.timestamp,
                "action": entry.action,
                "key": entry.key,
                "role": entry.role,
                "success": entry.success,
                "error": entry.error,
            }, ensure_ascii=False)
            with open(self._audit_file, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception as e:
            logger.warning("Failed to write audit log", error=str(e))

    def record(self, action: str, key: str, role: str, success: bool,
               error: Optional[str] = None) -> None:
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            action=action,
            key=key,
            role=role,
            success=success,
            error=error,
        )
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]
        # P1-17: Асинхронно пишем в файл
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self._append_to_file(entry))
        except RuntimeError:
            # Нет running loop — пропускаем async запись
            pass

    def get_entries(self, key: Optional[str] = None, action: Optional[str] = None,
                    limit: int = 100) -> List[Dict[str, Any]]:
        entries = self._entries
        if key:
            entries = [e for e in entries if e.key == key]
        if action:
            entries = [e for e in entries if e.action == action]
        return [
            {
                "timestamp": e.timestamp,
                "action": e.action,
                "key": e.key,
                "role": e.role,
                "success": e.success,
                "error": e.error,
            }
            for e in entries[-limit:]
        ]


# ═══════════════════════════════════════════════════════════════════════════════
# Crypto engine
# ═══════════════════════════════════════════════════════════════════════════════

class CryptoEngine:
    """AES-256-GCM encryption with PBKDF2 key derivation."""

    def __init__(self, master_key: bytes):
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography library not installed")
        if len(master_key) < 16:
            raise ValueError("Master key must be at least 16 bytes")
        self._master_key = master_key

    @classmethod
    def derive_key(cls, password: bytes, salt: bytes) -> bytes:
        """Derive AES key from password bytes using PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=KEY_LENGTH,
            salt=salt,
            iterations=ITERATIONS,
        )
        return kdf.derive(password)

    def encrypt(self, plaintext: str) -> Tuple[bytes, bytes, bytes]:
        """Encrypt plaintext. Returns (salt, nonce, ciphertext)."""
        salt = secrets.token_bytes(SALT_LENGTH)
        key = self.derive_key(self._master_key, salt)
        nonce = secrets.token_bytes(NONCE_LENGTH)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        return salt, nonce, ciphertext

    def decrypt(self, salt: bytes, nonce: bytes, ciphertext: bytes) -> str:
        """Decrypt ciphertext."""
        key = self.derive_key(self._master_key, salt)
        aesgcm = AESGCM(key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
# Secrets storage
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SecretEntry:
    value: str
    level: SecretLevel
    created_at: str
    updated_at: str
    description: str = ""
    tags: List[str] = field(default_factory=list)


class SecretsManager:
    """Encrypted secrets storage with role-based access."""

    def __init__(self, secrets_file: Optional[Path] = None,
                 master_key: Optional[bytes] = None):
        self._file = secrets_file or SECRETS_FILE
        self._audit = AuditLog()
        self._secrets: Dict[str, SecretEntry] = {}
        self._dirty = False

        # Initialize crypto
        if master_key:
            self._crypto = CryptoEngine(master_key)
        else:
            self._crypto = self._init_crypto()

        # Load existing secrets
        self._load()

    def _init_crypto(self) -> CryptoEngine:
        """Initialize crypto engine from env or file."""
        if not CRYPTO_AVAILABLE:
            raise RuntimeError(
                "cryptography library required. Install: pip install cryptography"
            )

        # Try env first
        key_hex = os.getenv(MASTER_KEY_ENV)
        if key_hex:
            return CryptoEngine(bytes.fromhex(key_hex))

        # Try file
        if MASTER_KEY_FILE.exists():
            key_hex = MASTER_KEY_FILE.read_text().strip()
            return CryptoEngine(bytes.fromhex(key_hex))

        # Generate new master key
        logger.warning("No master key found — generating new one")
        new_key = secrets.token_bytes(KEY_LENGTH)
        key_hex = new_key.hex()

        # Save to file with restricted permissions
        MASTER_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        MASTER_KEY_FILE.write_text(key_hex)
        os.chmod(MASTER_KEY_FILE, 0o600)

        logger.info("New master key saved", path=str(MASTER_KEY_FILE))
        return CryptoEngine(new_key)

    def _load(self) -> None:
        """Load encrypted secrets from file."""
        if not self._file.exists():
            return

        try:
            with open(self._file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for key, entry_data in data.items():
                if key.startswith("_"):
                    continue  # Skip metadata

                salt = base64.b64decode(entry_data["salt"])
                nonce = base64.b64decode(entry_data["nonce"])
                ciphertext = base64.b64decode(entry_data["ciphertext"])

                plaintext = self._crypto.decrypt(salt, nonce, ciphertext)

                self._secrets[key] = SecretEntry(
                    value=plaintext,
                    level=SecretLevel(entry_data.get("level", "sensitive")),
                    created_at=entry_data.get("created_at", datetime.now(timezone.utc).isoformat()),
                    updated_at=entry_data.get("updated_at", datetime.now(timezone.utc).isoformat()),
                    description=entry_data.get("description", ""),
                    tags=entry_data.get("tags", []),
                )
        except Exception as e:
            logger.error("Failed to load secrets", error=str(e))
            raise

    def _save(self) -> None:
        """Save encrypted secrets to file."""
        data: Dict[str, Any] = {
            "_meta": {
                "version": "1.0",
                "created": datetime.now(timezone.utc).isoformat(),
                "count": len(self._secrets),
            }
        }

        for key, entry in self._secrets.items():
            salt, nonce, ciphertext = self._crypto.encrypt(entry.value)
            data[key] = {
                "salt": base64.b64encode(salt).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "level": entry.level.value,
                "created_at": entry.created_at,
                "updated_at": entry.updated_at,
                "description": entry.description,
                "tags": entry.tags,
            }

        self._file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        os.chmod(self._file, 0o600)
        self._dirty = False
        logger.info("Secrets saved", count=len(self._secrets), path=str(self._file))

    def get(self, key: str, role: Role = Role.READ,
            default: Optional[str] = None) -> Optional[str]:
        """Get secret value with role check."""
        entry = self._secrets.get(key)
        if not entry:
            self._audit.record("read", key, role.value, False, "Key not found")
            return default

        # Check role access
        allowed_levels = ROLE_ACCESS.get(role, set())
        if entry.level not in allowed_levels:
            self._audit.record("read", key, role.value, False, "Insufficient role")
            logger.warning("Access denied", key=key, role=role.value,
                          level=entry.level.value)
            return default

        self._audit.record("read", key, role.value, True)
        return entry.value

    def set(self, key: str, value: str, role: Role = Role.WRITE,
            level: SecretLevel = SecretLevel.SENSITIVE,
            description: str = "", tags: Optional[List[str]] = None) -> bool:
        """Set secret value with role check."""
        # Check role can write this level
        allowed_levels = ROLE_ACCESS.get(role, set())
        if level not in allowed_levels:
            self._audit.record("write", key, role.value, False, "Insufficient role for level")
            logger.warning("Write denied", key=key, role=role.value, level=level.value)
            return False

        now = datetime.now(timezone.utc).isoformat()
        existing = self._secrets.get(key)

        self._secrets[key] = SecretEntry(
            value=value,
            level=level,
            created_at=existing.created_at if existing else now,
            updated_at=now,
            description=description,
            tags=tags or [],
        )
        self._dirty = True
        self._audit.record("write", key, role.value, True)

        # Auto-save
        self._save()
        return True

    def delete(self, key: str, role: Role = Role.ADMIN) -> bool:
        """Delete secret (admin only)."""
        if role != Role.ADMIN:
            self._audit.record("delete", key, role.value, False, "Admin required")
            return False

        if key not in self._secrets:
            return False

        del self._secrets[key]
        self._dirty = True
        self._audit.record("delete", key, role.value, True)
        self._save()
        return True

    def rotate_key(self, new_master_key: bytes, role: Role = Role.ADMIN) -> bool:
        """Re-encrypt all secrets with new master key."""
        if role != Role.ADMIN:
            self._audit.record("rotate", "*", role.value, False, "Admin required")
            return False

        try:
            # Decrypt all with old key
            plaintexts = {k: v.value for k, v in self._secrets.items()}

            # Switch crypto engine
            self._crypto = CryptoEngine(new_master_key)

            # Re-encrypt
            for key, value in plaintexts.items():
                entry = self._secrets[key]
                self._secrets[key] = SecretEntry(
                    value=value,
                    level=entry.level,
                    created_at=entry.created_at,
                    updated_at=datetime.now(timezone.utc).isoformat(),
                    description=entry.description,
                    tags=entry.tags,
                )

            self._dirty = True
            self._save()
            self._audit.record("rotate", "*", role.value, True)
            logger.info("Key rotation complete", count=len(self._secrets))
            return True
        except Exception as e:
            self._audit.record("rotate", "*", role.value, False, str(e))
            logger.error("Key rotation failed", error=str(e))
            return False

    def list_keys(self, role: Role = Role.READ) -> List[Dict[str, Any]]:
        """List available secrets (without values)."""
        allowed_levels = ROLE_ACCESS.get(role, set())
        return [
            {
                "key": k,
                "level": v.level.value,
                "created_at": v.created_at,
                "updated_at": v.updated_at,
                "description": v.description,
                "tags": v.tags,
            }
            for k, v in self._secrets.items()
            if v.level in allowed_levels
        ]

    def get_audit_log(self, key: Optional[str] = None,
                      action: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Get audit log entries."""
        return self._audit.get_entries(key, action, limit)

    def migrate_from_env(self, keys: Optional[List[str]] = None,
                         role: Role = Role.ADMIN) -> Dict[str, bool]:
        """Migrate secrets from environment variables to encrypted storage."""
        if role != Role.ADMIN:
            return {}

        if keys is None:
            keys = [
                "LLM_API_KEY", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID",
                "TELEGRAM_CHANNEL_ID", "DATABASE_URL", "REDIS_URL",
                "YANDEX_METRIKA_TOKEN", "DASHBOARD_API_KEY",
            ]

        results = {}
        for key in keys:
            value = os.getenv(key)
            if value:
                level = SecretLevel.CRITICAL if "URL" in key or "DB" in key else SecretLevel.SENSITIVE
                success = self.set(key, value, role=Role.ADMIN, level=level,
                                  description=f"Migrated from env on {datetime.now(timezone.utc).isoformat()}")
                results[key] = success
                if success:
                    logger.info("Migrated secret from env", key=key)

        return results


# ═══════════════════════════════════════════════════════════════════════════════
# Singleton + convenience functions
# ═══════════════════════════════════════════════════════════════════════════════

_manager: Optional[SecretsManager] = None


def get_manager() -> SecretsManager:
    """Get singleton SecretsManager."""
    global _manager
    if _manager is None:
        _manager = SecretsManager()
    return _manager


def get_secret(key: str, default: Optional[str] = None,
               role: str = "read",
               allow_env_fallback: bool = False) -> Optional[str]:
    """
    Drop-in replacement for os.getenv() with encryption.

    Args:
        key: Secret key name
        default: Default value if not found
        role: Access role (read/write/admin)
        allow_env_fallback: Если True — fallback на os.getenv при отсутствии в хранилище

    Returns:
        Decrypted secret value or default
    """
    # First try encrypted storage
    try:
        manager = get_manager()
        value = manager.get(key, Role(role), default=None)
        if value is not None:
            return value
    except Exception as e:
        logger.debug("Secrets manager not available, falling back to env", error=str(e))

    # Fallback to environment variable only if explicitly allowed
    if allow_env_fallback:
        return os.getenv(key, default)
    return default


def set_secret(key: str, value: str, role: str = "admin",
               level: str = "sensitive", description: str = "") -> bool:
    """Set secret in encrypted storage."""
    manager = get_manager()
    return manager.set(
        key, value,
        role=Role(role),
        level=SecretLevel(level),
        description=description,
    )


def delete_secret(key: str, role: str = "admin") -> bool:
    """Delete secret (admin only)."""
    manager = get_manager()
    return manager.delete(key, Role(role))


def list_secrets(role: str = "read") -> List[Dict[str, Any]]:
    """List secrets metadata."""
    manager = get_manager()
    return manager.list_keys(Role(role))


def rotate_master_key(new_key_hex: str, role: str = "admin") -> bool:
    """Rotate master encryption key."""
    manager = get_manager()
    return manager.rotate_key(bytes.fromhex(new_key_hex), Role(role))


def migrate_env_secrets(role: str = "admin") -> Dict[str, bool]:
    """Migrate secrets from .env to encrypted storage."""
    manager = get_manager()
    return manager.migrate_from_env(role=Role(role))


def get_audit_entries(key: Optional[str] = None, action: Optional[str] = None,
                      limit: int = 100) -> List[Dict[str, Any]]:
    """Get audit log."""
    manager = get_manager()
    return manager.get_audit_log(key, action, limit)
