"""Transparently-encrypted model fields (Fernet, at rest).

``EncryptedTextField`` stores its value encrypted in the DB and returns the
plaintext when read. The Fernet key is ``settings.FIELD_ENCRYPTION_KEY`` if set
(a urlsafe-base64 32-byte key), else one derived from ``settings.SECRET_KEY`` —
so rotating SECRET_KEY without setting an explicit key makes existing ciphertext
undecryptable (re-enter those secrets). Values written before encryption was
introduced are read back verbatim (legacy-plaintext fallback), so migrating an
existing plaintext column is non-destructive.

Note: encryption is randomized (IV + timestamp), so exact-match DB lookups on an
encrypted column won't work — don't ``.filter()`` on these fields.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.db import models

# Marks a value as ciphertext we wrote, so legacy plaintext is distinguishable.
_PREFIX = "fernet:"


def _fernet() -> Fernet:
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "") or settings.SECRET_KEY
    # Accept a ready Fernet key as-is; otherwise derive a 32-byte key from it.
    raw = key.encode()
    try:
        if len(raw) == 44:  # a urlsafe-b64 32-byte Fernet key
            return Fernet(raw)
    except (ValueError, TypeError):
        pass
    digest = hashlib.sha256(raw).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


class EncryptedTextField(models.TextField):
    """A TextField encrypted at rest with Fernet (legacy plaintext tolerated)."""

    def from_db_value(self, value, expression, connection):
        if value is None or value == "":
            return value
        if value.startswith(_PREFIX):
            try:
                return _fernet().decrypt(value[len(_PREFIX):].encode()).decode()
            except InvalidToken:
                return value  # wrong key — surface ciphertext rather than crash
        return value  # legacy plaintext, written before encryption was added

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value is None or value == "":
            return value
        if value.startswith(_PREFIX):
            return value  # already encrypted (e.g. re-save of a loaded ciphertext)
        return _PREFIX + _fernet().encrypt(str(value).encode()).decode()
