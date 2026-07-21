"""Encrypted-at-rest storage for sensitive values (PAT, cookies, RTMP key)."""
import json
from pathlib import Path
from cryptography.fernet import Fernet


class SecureStore:
    """Encrypts all values with Fernet before writing to disk."""

    def __init__(self, encryption_key, store_path):
        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode()
        self._fernet = Fernet(encryption_key)
        self._path = Path(store_path)
        self._data = self._load()

    def _load(self):
        if self._path.exists():
            encrypted = self._path.read_bytes()
            if encrypted:
                decrypted = self._fernet.decrypt(encrypted)
                return json.loads(decrypted)
        return {}

    def _save(self):
        plaintext = json.dumps(self._data).encode()
        encrypted = self._fernet.encrypt(plaintext)
        self._path.write_bytes(encrypted)

    def get(self, key, default=''):
        return self._data.get(key, default)

    def set(self, key, value):
        self._data[key] = value
        self._save()

    def delete(self, key):
        self._data.pop(key, None)
        self._save()

    def all(self):
        return dict(self._data)

    def clear(self):
        self._data = {}
        self._save()
