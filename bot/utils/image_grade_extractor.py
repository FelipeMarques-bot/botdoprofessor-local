"""Extract grades from a photo/image using AI vision models.

Usage:
    from bot.utils.image_grade_extractor import extract_grades_from_image
    grades = extract_grades_from_image(image_bytes)
"""

import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

LogFn = Callable[[str], None]

EXTRACT_GRADES_PROMPT = """\
Tarefa: Extrair nomes de alunos e notas desta imagem.

Retorne SOMENTE o JSON abaixo, preenchido com os dados da imagem. Nao explique nada.

{"alunos":[{"aluno":"Nome Completo","nota":"valor"}],"total_encontrados":0,"confianca":"alta","observacoes":"breve"}

Exemplo de saida:
{"alunos":[{"aluno":"Maria Silva","nota":"8.5"},{"aluno":"Joao Santos","nota":"7.0"}],"total_encontrados":2,"confianca":"alta","observacoes":"imagem clara"}

IMPORTANTE: Retorne APENAS o JSON, sem texto antes ou depois.
"""


def _call_ai_with_image(prompt: str, image_bytes: bytes) -> str:
    """Call AI vision model with an image. Uses the same providers as ai_assist.py."""
    provider = os.environ.get("AI_PROVIDER", "local").strip().lower()

    if provider in ("local", "ollama"):
        return _call_ollama(prompt, image_bytes)
    elif provider == "openai":
        return _call_openai(prompt, image_bytes)
    elif provider == "anthropic":
        return _call_anthropic(prompt, image_bytes)
    else:
        return _call_gemini(prompt, image_bytes)


def _call_gemini(prompt: str, image_bytes: bytes) -> str:
    try:
        import google.genai as genai
        from google.genai import types
    except ImportError:
        raise RuntimeError("google-genai nao instalado. Rode: pip install google-genai")

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY nao configurada")

    client = genai.Client(api_key=api_key)
    model = os.environ.get("AI_MODEL", "gemini-2.5-flash")

    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            prompt,
        ],
    )
    return response.text or ""


def _call_openai(prompt: str, image_bytes: bytes) -> str:
    try:
        import base64
        import urllib.request
    except ImportError:
        raise RuntimeError("urllib nao disponivel")

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY nao configurada")

    model = os.environ.get("AI_MODEL", "gpt-4o")
    b64 = base64.b64encode(image_bytes).decode()

    payload = json.dumps({
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                ],
            }
        ],
        "max_tokens": 4096,
    }).encode()

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    return data["choices"][0]["message"]["content"]


def _call_anthropic(prompt: str, image_bytes: bytes) -> str:
    try:
        import base64
        import urllib.request
    except ImportError:
        raise RuntimeError("urllib nao disponivel")

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY nao configurada")

    model = os.environ.get("AI_MODEL", "claude-sonnet-4-20250514")
    b64 = base64.b64encode(image_bytes).decode()

    payload = json.dumps({
        "model": model,
        "max_tokens": 4096,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/jpeg",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode())
    return data["content"][0]["text"]


def _call_ollama(prompt: str, image_bytes: bytes) -> str:
    try:
        import base64
        import urllib.request
    except ImportError:
        raise RuntimeError("urllib nao disponivel")

    host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip().rstrip("/")
    model = os.environ.get("OLLAMA_MODEL", "openbmb/minicpm-v4.6")
    b64 = base64.b64encode(image_bytes).decode()

    payload = json.dumps({
        "model": model,
        "prompt": prompt,
        "images": [b64],
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 4096},
    }).encode()

    req = urllib.request.Request(
        f"{host}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
    return data.get("response", "")


def _safe_json_parse(text: str, fallback: Any = None) -> Any:
    """Try to extract JSON from AI response text.

    The model often returns explanatory text before/after the JSON.
    Strategy: find the LAST complete JSON object in the text.
    """
    text = (text or "").strip()

    # Try the whole text first
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    # Find all '{' positions and try parsing from each one
    # Start from the LAST '{' to skip explanatory JSON examples
    last_brace = text.rfind("}")
    if last_brace < 0:
        return fallback if fallback is not None else {}

    # Walk backwards to find the matching opening brace
    depth = 0
    for i in range(last_brace, -1, -1):
        if text[i] == "}":
            depth += 1
        elif text[i] == "{":
            depth -= 1
            if depth == 0:
                candidate = text[i:last_brace + 1]
                try:
                    return json.loads(candidate)
                except json.JSONDecodeError:
                    continue

    return fallback if fallback is not None else {}


def extract_grades_from_image(
    image_bytes: bytes,
    logger: Optional[LogFn] = None,
) -> Dict[str, Any]:
    """Extract student grades from a photo/image using AI vision.

    Args:
        image_bytes: Raw bytes of the image (JPEG, PNG, etc.)
        logger: Optional logging function

    Returns:
        Dict with keys: alunos, total_encontrados, confianca, observacoes, error
    """
    if not image_bytes:
        return {"alunos": [], "total_encontrados": 0, "error": "Imagem vazia"}

    def _log(msg: str):
        if logger:
            logger(msg)
        log.info(msg)

    _log("[ImageExtractor] Enviando imagem para analise de IA...")
    _log(f"[ImageExtractor] Tamanho da imagem: {len(image_bytes)} bytes")

    try:
        raw_response = _call_ai_with_image(EXTRACT_GRADES_PROMPT, image_bytes)
        _log(f"[ImageExtractor] Resposta recebida ({len(raw_response)} chars)")
    except Exception as e:
        _log(f"[ImageExtractor] ERRO ao chamar IA: {e}")
        return {"alunos": [], "total_encontrados": 0, "error": str(e)}

    result = _safe_json_parse(raw_response, {
        "alunos": [],
        "total_encontrados": 0,
        "confianca": "baixa",
        "observacoes": "Falha ao processar resposta da IA",
    })

    if "alunos" not in result:
        result["alunos"] = []
    if "total_encontrados" not in result:
        result["total_encontrados"] = len(result["alunos"])

    _log(f"[ImageExtractor] {result['total_encontrados']} alunos encontrados (confianca: {result.get('confianca', '?')})")

    if result.get("observacoes"):
        _log(f"[ImageExtractor] Observacoes: {result['observacoes']}")

    return result


def is_available() -> bool:
    """Check if AI vision is available for image extraction."""
    provider = os.environ.get("AI_PROVIDER", "local").strip().lower()
    if provider in ("local", "ollama"):
        try:
            import urllib.request
            host = os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip().rstrip("/")
            req = urllib.request.Request(f"{host}/api/tags")
            with urllib.request.urlopen(req, timeout=2) as resp:
                return resp.status == 200
        except Exception:
            return False
    elif provider == "openai":
        return bool(os.environ.get("OPENAI_API_KEY"))
    elif provider == "anthropic":
        return bool(os.environ.get("ANTHROPIC_API_KEY"))
    else:
        return bool(os.environ.get("GEMINI_API_KEY"))
