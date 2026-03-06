"""
Symmetric encryption utilities for sensitive data (API keys, secrets).

Uses Fernet (AES-128-CBC + HMAC-SHA256) from the `cryptography` library.
The encryption key is derived from the application's HMAC_SECRET_KEY via PBKDF2.
"""
from __future__ import annotations

import base64
import hashlib
import logging

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    """Lazily initialize Fernet with a key derived from HMAC_SECRET_KEY."""
    global _fernet
    if _fernet is None:
        from app.config import get_settings
        secret = get_settings().hmac_secret_key
        # Derive a 32-byte key via SHA-256, then base64-encode for Fernet
        derived = hashlib.sha256(secret.encode("utf-8")).digest()
        key = base64.urlsafe_b64encode(derived)
        _fernet = Fernet(key)
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ""
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8")).decode("utf-8")


class DecryptionError(Exception):
    """Raised when decryption fails due to invalid key or corrupted data."""


def decrypt(ciphertext: str) -> str:
    """Decrypt a ciphertext string. Returns plaintext.

    Raises DecryptionError on failure so callers can distinguish
    'decryption failed' from 'original value was empty'.
    """
    if not ciphertext:
        return ""
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error("Decryption failed (key mismatch or corrupted data): %s", e)
        raise DecryptionError(f"Failed to decrypt value: {e}") from e
