"""
Auto-fix module for Bot do Professor.
Uses Ollama (local AI) to analyze runtime errors and suggest safe, automatic fixes.
Fixes are scoped to session_state values only — never modifies source code.
"""

import json
import os
import traceback as tb_mod
from typing import Any, Dict, Optional

import requests

SAFE_FIX_TYPES = {
    "date_format",
    "timeout_increase",
    "url_cleanup",
    "field_trim",
    "retry",
}

OLLAMA_BASE = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("AUTOFIX_MODEL", "qwen2.5-coder:7b")
MAX_AUTOFIX_ATTEMPTS = 3


def _call_ollama(prompt: str, model: str = OLLAMA_MODEL) -> Optional[str]:
    try:
        resp = requests.post(
            f"{OLLAMA_BASE}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data.get("response", "")
    except Exception:
        return None


def _build_prompt(error_msg: str, tb_str: str, context: Dict[str, Any]) -> str:
    ctx_preview = {k: v for k, v in context.items()
                   if isinstance(v, (str, int, float, bool)) and not k.endswith("senha") and not k.endswith("key")}
    return f"""You are a fix assistant for Bot do Professor (a Playwright-based SGE grading tool).
An error occurred during execution. Analyze it and suggest a safe fix.

ERROR: {error_msg}
TRACEBACK (last 20 lines):
{chr(10).join(tb_str.split(chr(10))[-20:])}
SESSION CONTEXT: {json.dumps(ctx_preview, indent=2, default=str)}

Respond ONLY with a JSON object (no markdown, no code fences):

If fixable:
{{"fixable": true, "fix_type": "date_format"|"timeout_increase"|"url_cleanup"|"field_trim"|"retry", "explanation": "short PT-BR explanation", "fix": {{"action": "set_session_value"|"retry", "key": "session_state_key_name", "new_value": "corrected value"}}}}

If NOT fixable:
{{"fixable": false, "explanation": "why this cannot be auto-fixed"}}

Rules:
- date_format: if a date like '03/01/2026' might be ambiguous, normalize to dd/mm/aaaa
- timeout_increase: if Playwright timeout exceeded, suggest {{{{ "action": "retry" }}}}
- url_cleanup: if Google Drive URL is malformed, suggest corrected URL
- field_trim: if a field has leading/trailing whitespace or empty
- retry: generic retry with no session change
- NEVER suggest changing passwords, keys, or business logic
- The fix value must be the corrected string/value for the session_state key"""


def attempt_autofix(
    error_msg: str,
    tb_str: str,
    context: Dict[str, Any],
    logger: Optional[callable] = None,
    attempt: int = 0,
) -> Dict[str, Any]:
    if attempt >= MAX_AUTOFIX_ATTEMPTS:
        return {"fixable": False, "explanation": "Maximo de tentativas de autofix atingido."}

    if logger:
        logger("Autofix: analisando erro com IA local...")

    prompt = _build_prompt(error_msg, tb_str, context)
    raw = _call_ollama(prompt)

    if not raw:
        if logger:
            logger("Autofix: erro ao chamar Ollama.")
        return {"fixable": False, "explanation": "Falha ao contactar Ollama."}

    result = _parse_response(raw)
    if not result:
        if logger:
            logger("Autofix: resposta da IA nao pode ser interpretada.")
        return {"fixable": False, "explanation": "Resposta da IA invalida."}

    if logger and result.get("fixable"):
        logger(f"Autofix sugerido: {result['explanation']}")

    return result


def _parse_response(raw: str) -> Optional[Dict[str, Any]]:
    for prefix in ("```json", "```"):
        if prefix in raw:
            start = raw.index(prefix) + len(prefix)
            end = raw.rindex("```") if "```" in raw[start:] else len(raw)
            raw = raw[start:end].strip()
            break
    raw = raw.strip()
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
            if isinstance(data, dict) and "fixable" in data:
                return data
        except json.JSONDecodeError:
            pass
    return None


def apply_fix(result: Dict[str, Any], session_state: Dict[str, Any]) -> Optional[str]:
    fix_type = result.get("fix_type", "")
    if fix_type not in SAFE_FIX_TYPES:
        return None

    fix_data = result.get("fix", {})
    action = fix_data.get("action", "")

    if action == "set_session_value":
        key = fix_data.get("key", "")
        new_value = fix_data.get("new_value", "")
        if key and key in session_state:
            old = session_state[key]
            if isinstance(old, str):
                session_state[key] = str(new_value)
            else:
                session_state[key] = new_value
            return f"Corrigido '{key}': {old} -> {new_value}"
    elif action == "retry":
        return "Tentando novamente com timeout ajustado..."

    return None
