"""Redacao central de dados sensiveis para logs e mensagens de erro.

Nao tenta ser um DLP completo: cobre os formatos que o projeto manipula
(senhas, tokens, chaves de API, CPF, Authorization/Bearer). O objetivo e
evitar que credenciais vazem para logs, telas de erro e relatorios de suporte.
"""
from __future__ import annotations

import re
from typing import Any, Mapping

_MASK = "***"

_SENSITIVE_KEY_RE = re.compile(
    r"(?i)(password|passwd|senha|token|secret|api[_-]?key|authorization|"
    r"credential|cpf|license[_-]?key|fingerprint)"
)

_PATTERNS = (
    (
        re.compile(
            r"(?i)\b(password|passwd|senha|token|secret|api[_-]?key|authorization)"
            r"\b\s*[:=]\s*([^\s,;]+)"
        ),
        r"\1=***",
    ),
    (re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"), "Bearer ***"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "sk-***"),
    (re.compile(r"\bAIza[0-9A-Za-z_-]{20,}\b"), "AIza***"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "ghp_***"),
    (re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b"), "***.***.***-**"),
)


def redact_text(value: Any) -> str:
    """Retorna o texto com credenciais e CPF mascarados."""
    if value is None:
        return ""
    text = str(value)
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact_mapping(data: Mapping[str, Any]) -> dict:
    """Copia um dicionario mascarando chaves e valores sensiveis."""
    result: dict = {}
    for key, value in data.items():
        if _SENSITIVE_KEY_RE.search(str(key)):
            result[key] = _MASK
        elif isinstance(value, Mapping):
            result[key] = redact_mapping(value)
        elif isinstance(value, list):
            result[key] = [
                redact_mapping(item) if isinstance(item, Mapping) else redact_text(item)
                for item in value
            ]
        else:
            result[key] = redact_text(value)
    return result
