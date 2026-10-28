import os
import base64
import hashlib
from pathlib import Path

try:
    from cryptography.fernet import Fernet
except ImportError:
    Fernet = None


_crypter = None

_DPAPI_PREFIX = "dpapi:v1:"
_FERNET_PREFIX = "fernet:v1:"


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

    if not Fernet:
        raise RuntimeError(
            "A biblioteca 'cryptography' nao esta instalada. "
            "Instale com: pip install cryptography"
        )
    _crypter = Fernet(key.encode() if isinstance(key, str) else key)
    return _crypter


def encrypt_value(value: str) -> str:
    """Criptografa um valor sensivel com Fernet (fallback portavel)."""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt_value(encrypted: str) -> str:
    """Descriptografa um valor sensivel com Fernet (fallback portavel)."""
    return _get_fernet().decrypt(encrypted.encode()).decode()


def _dpapi_protect(data: bytes) -> bytes:
    """Protege dados com DPAPI do Windows (vinculado ao usuario atual)."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    if not data:
        return b""

    buffer_in = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(
        len(data),
        ctypes.cast(buffer_in, ctypes.POINTER(ctypes.c_char)),
    )
    blob_out = DATA_BLOB()

    crypt32 = ctypes.windll.crypt32
    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL

    ok = crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        "BotDoProfessor",
        None,
        None,
        None,
        0x1,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise ctypes.WinError()

    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    """Remove a protecao DPAPI do Windows."""
    import ctypes
    from ctypes import wintypes

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [
            ("cbData", wintypes.DWORD),
            ("pbData", ctypes.POINTER(ctypes.c_char)),
        ]

    if not data:
        return b""

    buffer_in = ctypes.create_string_buffer(data, len(data))
    blob_in = DATA_BLOB(
        len(data),
        ctypes.cast(buffer_in, ctypes.POINTER(ctypes.c_char)),
    )
    blob_out = DATA_BLOB()

    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL

    ok = crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0x1,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise ctypes.WinError()

    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def is_protected_value(value: str) -> bool:
    """True se o valor ja foi gravado no formato protegido."""
    return isinstance(value, str) and value.startswith((_DPAPI_PREFIX, _FERNET_PREFIX))


def protect_value(value: str) -> str:
    """Protege um valor para armazenamento local.

    No Windows usa DPAPI (chave vinculada ao usuario). Em outros sistemas usa
    Fernet com chave local. Nunca retorna o valor em texto puro.
    """
    if not value:
        return value

    if os.name == "nt":
        try:
            encrypted = _dpapi_protect(value.encode("utf-8"))
            return _DPAPI_PREFIX + base64.b64encode(encrypted).decode("ascii")
        except (OSError, AttributeError):
            pass

    encrypted = _get_fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return _FERNET_PREFIX + encrypted


def unprotect_value(value: str) -> str:
    """Reverte `protect_value`.

    Valores antigos em texto puro (sem prefixo) sao devolvidos como estao para
    permitir migracao transparente no proximo salvamento.
    """
    if not value:
        return value
    if value.startswith(_DPAPI_PREFIX):
        if os.name != "nt":
            raise RuntimeError("Credencial DPAPI nao pode ser lida fora do Windows.")
        encrypted = base64.b64decode(value[len(_DPAPI_PREFIX):])
        return _dpapi_unprotect(encrypted).decode("utf-8")
    if value.startswith(_FERNET_PREFIX):
        encrypted = value[len(_FERNET_PREFIX):]
        return _get_fernet().decrypt(encrypted.encode("ascii")).decode("utf-8")
    return value


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
