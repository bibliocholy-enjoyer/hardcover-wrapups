"""Encrypted, expiring cookie values, so the server can stay stateless.

The access token lives only in an encrypted cookie in the user's browser, for a few
minutes. Nothing is stored on the server, so a restart or a suspended machine loses
nothing.
"""
import base64
import hashlib
import json

from cryptography.fernet import Fernet, InvalidToken


class Sealer:
    def __init__(self, secret):
        if len(secret) < 32:
            raise ValueError("SESSION_SECRET must be at least 32 characters")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
        self._fernet = Fernet(key)

    def seal(self, data):
        """Encrypt and sign a JSON-able dict; the result is safe to put in a cookie."""
        return self._fernet.encrypt(json.dumps(data).encode()).decode()

    def unseal(self, value, max_age):
        """The dict sealed into `value`, or None if it's missing, tampered with or too old."""
        if not value:
            return None
        try:
            return json.loads(self._fernet.decrypt(value.encode(), ttl=max_age))
        except (InvalidToken, ValueError):
            return None
