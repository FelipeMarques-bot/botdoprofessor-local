import os
import json
import base64
import hashlib
from pathlib import Path
from typing import Optional

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None


_crypter = None


def _get_fernet():
    global _crypter
    if _crypter:
        return _crypter

    from config.settings import ENCRYPTION_KEY

    if ENCRYPTION_KEY:
        key = ENCRYPTION_KEY
    else:
        key_file = Path.home() / ".bot_local" / ".encryption_key"
        if key_file.exists():
            key = key_file.read_text().strip()
        else:
            key = base64.urlsafe_b64encode(os.urandom(32)).decode()
            key_file.parent.mkdir(parents=True, exist_ok=True)
            key_file.write_text(key)
            os.chmod(key_file, 0o600)

    if Fernet:
        _crypter = Fernet(key.encode() if isinstance(key, str) else key)
    return _crypter


def encrypt_value(value: str) -> str:
    """Criptografa um valor sensivel."""
    f = _get_fernet()
    if f:
        return f.encrypt(value.encode()).decode()
    return base64.b64encode(value.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    """Descriptografa um valor sensivel."""
    f = _get_fernet()
    if f:
        return f.decrypt(encrypted.encode()).decode()
    return base64.b64decode(encrypted.encode()).decode()


def hash_value(value: str) -> str:
    """Gera hash SHA-256 de um valor."""
    return hashlib.sha256(value.encode()).hexdigest()


def sanitize_log(data: dict) -> dict:
    """Remove ou mascarara dados sensiveis de um dict de log."""
    sensitive_keys = [
        "password", "senha", "token", "secret", "cpf",
        "license_key", "fingerprint", "api_key", "credential",
    ]
    sanitized = {}
    for k, v in data.items():
        k_lower = k.lower()
        if any(s in k_lower for s in sensitive_keys):
            if isinstance(v, str) and len(v) > 4:
                sanitized[k] = v[:2] + "***" + v[-2:]
            else:
                sanitized[k] = "***"
        elif isinstance(v, dict):
            sanitized[k] = sanitize_log(v)
        else:
            sanitized[k] = v
    return sanitized


def mask_cpf(cpf: str) -> str:
    """Mascara CPF para exibicao."""
    cpf_clean = cpf.replace(".", "").replace("-", "")
    if len(cpf_clean) == 11:
        return f"***.***.*{cpf_clean[-2:]}"
    return "***"


def mask_license_key(key: str) -> str:
    """Mascara chave de licenca."""
    if len(key) > 8:
        return key[:4] + "***" + key[-4:]
    return "***"
