import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import google.genai as genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

try:
    import requests as http_requests
except ImportError:
    http_requests = None

LogFn = Callable[[str], None]

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
AI_ASSIST = os.environ.get("AI_ASSIST", "0") == "1"
AI_LEARN_MODE = os.environ.get("AI_LEARN_MODE", "0") == "1"
AI_RECORDING_DIR = os.environ.get("AI_RECORDING_DIR", "artifacts/ai-recordings")
AI_PROVIDER = os.environ.get("AI_PROVIDER", "local").strip().lower()
AI_MODEL = os.environ.get("AI_MODEL", "gemini-2.5-flash")
AI_TEMPERATURE = float(os.environ.get("AI_TEMPERATURE", "0.2"))
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip().rstrip("/")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2-vision")
OLLAMA_FALLBACK_MODEL = os.environ.get("OLLAMA_FALLBACK_MODEL", "openbmb/minicpm-v4.6")
OLLAMA_AUTO_SETUP = os.environ.get("OLLAMA_AUTO_SETUP", "1") == "1"
OLLAMA_PULL_TIMEOUT = int(os.environ.get("OLLAMA_PULL_TIMEOUT", "1800"))
_ollama_active_model: Optional[str] = None
_ollama_consecutive_errors: int = 0
_ollama_disabled_until: float = 0.0


@dataclass
class ScreenshotAction:
    step: int
    prompt: str
    raw_response: str
    parsed_action: Optional[Dict[str, Any]]
    timestamp: float


class AIAssistError(RuntimeError):
    pass


def _log(logger: Optional[LogFn], msg: str) -> None:
    if logger:
        logger(msg)


def _get_provider() -> str:
    return os.environ.get("AI_PROVIDER", "local").strip().lower()


def _ollama_primary_model() -> str:
    """Modelo principal do Ollama, respeitando OLLAMA_MODEL definido em runtime."""
    return os.environ.get("OLLAMA_MODEL", "").strip() or "llama3.2-vision"


def _ai_assist_enabled() -> bool:
    return os.environ.get("AI_ASSIST", "0") == "1"


def is_available() -> bool:
    provider = _get_provider()
    if provider in ("local", "ollama"):
        return _is_ollama_running()
    elif provider == "openai":
        return bool(OPENAI_API_KEY)
    elif provider == "anthropic":
        return bool(ANTHROPIC_API_KEY)
    elif provider == "gemini":
        return bool(GEMINI_API_KEY) and genai is not None
    return False


def is_enabled() -> bool:
    return is_available() and _ai_assist_enabled()


def _is_ollama_running() -> bool:
    if http_requests is None:
        return False
    try:
        r = http_requests.get(f"{OLLAMA_HOST}/api/tags", timeout=2)
        return r.status_code == 200
    except Exception:
        return False


def _find_ollama_exe() -> Optional[str]:
    """Procura o executavel do Ollama em locais comuns."""
    candidates = [
        "ollama",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"),
        str(Path(os.environ.get("PROGRAMFILES", "")) / "Ollama" / "ollama.exe"),
        str(Path(os.environ.get("PROGRAMFILES(X86)", "")) / "Ollama" / "ollama.exe"),
    ]
    for c in candidates:
        try:
            subprocess.run([c, "--version"], capture_output=True, timeout=5)
            return c
        except (FileNotFoundError, subprocess.TimeoutError):
            continue
    return None


def _is_ollama_installed() -> bool:
    return _find_ollama_exe() is not None


def setup_ollama(logger: Optional[LogFn] = None) -> bool:
    """Baixa e instala Ollama + modelo de visao automaticamente."""
    _log(logger, "[Ollama] Verificando instalacao do Ollama...")

    if _is_ollama_running():
        _log(logger, "[Ollama] Ollama ja esta rodando.")
        _ensure_fallback_model(logger=logger)
        return True

    if not _is_ollama_installed():
        _log(logger, "[Ollama] Ollama nao encontrado. Baixando instalador...")
        installer_url = "https://ollama.com/download/OllamaSetup.exe"
        installer_path = os.path.join(tempfile.gettempdir(), "OllamaSetup.exe")
        try:
            urllib.request.urlretrieve(installer_url, installer_path)
            _log(logger, "[Ollama] Instalador baixado. Instalando (pode pedir permissao de admin)...")
            subprocess.run([installer_path, "/SILENT"], check=True, timeout=120)
            _log(logger, "[Ollama] Instalacao concluida. Aguardando inicio...")
            time.sleep(5)
        except Exception as exc:
            _log(logger, f"[Ollama] ERRO ao baixar/instalar Ollama: {exc}")
            return False

    exe = _find_ollama_exe()
    if not exe:
        _log(logger, "[Ollama] ERRO: Ollama instalado mas executavel nao encontrado.")
        return False

    if not _is_ollama_running():
        _log(logger, "[Ollama] Iniciando servico do Ollama...")
        try:
            subprocess.Popen([exe, "serve"], creationflags=subprocess.DETACHED_PROCESS)
            time.sleep(3)
            for _ in range(15):
                if _is_ollama_running():
                    break
                time.sleep(2)
        except Exception:
            pass

    if not _is_ollama_running():
        _log(logger, "[Ollama] ERRO: Servico do Ollama nao iniciou. Inicie manualmente.")
        return False

    avail_ram = _get_available_ram_gb()
    _log(logger, f"[Ollama] RAM disponivel: {avail_ram:.1f} GB")

    primary_model = _ollama_primary_model()
    primary_ok = _is_model_available(primary_model, logger)

    if not primary_ok:
        _log(logger, f"[Ollama] Baixando modelo {primary_model}...")
        _log(logger, f"[Ollama] Timeout configurado: {OLLAMA_PULL_TIMEOUT}s")
        try:
            result = subprocess.run([exe, "pull", primary_model], timeout=OLLAMA_PULL_TIMEOUT)
            if result.returncode == 0:
                _log(logger, f"[Ollama] Modelo {primary_model} baixado com sucesso!")
            else:
                _log(logger, f"[Ollama] Erro ao baixar modelo (codigo {result.returncode}).")
        except subprocess.TimeoutExpired:
            _log(logger, f"[Ollama] Timeout baixando {primary_model} apos {OLLAMA_PULL_TIMEOUT}s.")
        except Exception as exc:
            _log(logger, f"[Ollama] ERRO: {exc}")

    _ensure_fallback_model(logger=logger)
    return True


def _ensure_fallback_model(logger: Optional[LogFn] = None) -> None:
    """Baixa o modelo leve de fallback se nao estiver disponivel."""
    if _is_model_available(OLLAMA_FALLBACK_MODEL, logger):
        return
    exe = _find_ollama_exe()
    if not exe:
        return
    _log(logger, f"[Ollama] Baixando modelo leve de fallback: {OLLAMA_FALLBACK_MODEL} (~1.3GB)...")
    try:
        result = subprocess.run([exe, "pull", OLLAMA_FALLBACK_MODEL], timeout=600)
        if result.returncode == 0:
            _log(logger, f"[Ollama] Modelo {OLLAMA_FALLBACK_MODEL} baixado!")
        else:
            _log(logger, f"[Ollama] Aviso: nao foi possivel baixar {OLLAMA_FALLBACK_MODEL}.")
    except Exception:
        _log(logger, "[Ollama] Aviso: falha ao baixar modelo de fallback.")


def ensure_ollama(logger: Optional[LogFn] = None) -> bool:
    """Garante que Ollama esteja instalado e rodando com modelo de visao."""
    if not OLLAMA_AUTO_SETUP:
        return _is_ollama_running()
    return setup_ollama(logger=logger)


def _get_client() -> Any:
    if _get_provider() == "ollama":
        raise AIAssistError("Ollama nao usa client; use _call_ollama diretamente.")
    if not GEMINI_API_KEY:
        raise AIAssistError("GEMINI_API_KEY nao definida nas variaveis de ambiente.")
    if genai is None:
        raise AIAssistError("google.genai nao instalado. Rode: pip install google-genai")
    return genai.Client(api_key=GEMINI_API_KEY)


def _call_gemini(prompt: str, image_bytes: Optional[bytes] = None, images: Optional[List[bytes]] = None) -> str:
    client = _get_client()
    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=AI_TEMPERATURE,
    )

    all_images = images or ([image_bytes] if image_bytes else [])
    if all_images:
        contents = [prompt] + [
            types.Part(inline_data=types.Blob(mime_type="image/png", data=img))
            for img in all_images
        ]
    else:
        contents = prompt

    response = client.models.generate_content(
        model=AI_MODEL,
        contents=contents,
        config=config,
    )
    text = response.text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text


def _call_openai(prompt: str, image_bytes: Optional[bytes] = None, images: Optional[List[bytes]] = None) -> str:
    """Chama a API da OpenAI (GPT-4o, GPT-4o-mini, etc)."""
    if http_requests is None:
        raise AIAssistError("requests nao instalado. Rode: pip install requests")

    all_images = images or ([image_bytes] if image_bytes else [])
    messages = [{"role": "user", "content": []}]

    # Texto do prompt
    messages[0]["content"].append({"type": "text", "text": prompt})

    # Imagens (base64)
    for img in all_images:
        img_b64 = base64.b64encode(img).decode("utf-8")
        messages[0]["content"].append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}",
                "detail": "high",
            },
        })

    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": AI_TEMPERATURE,
        "max_tokens": 4096,
    }

    resp = http_requests.post(
        "https://api.openai.com/v1/chat/completions",
        json=payload,
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    text = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "")
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text


def _call_anthropic(prompt: str, image_bytes: Optional[bytes] = None, images: Optional[List[bytes]] = None) -> str:
    """Chama a API da Anthropic (Claude)."""
    if http_requests is None:
        raise AIAssistError("requests nao instalado. Rode: pip install requests")

    all_images = images or ([image_bytes] if image_bytes else [])
    content = []

    # Texto do prompt
    content.append({"type": "text", "text": prompt})

    # Imagens (base64)
    for img in all_images:
        img_b64 = base64.b64encode(img).decode("utf-8")
        content.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": img_b64,
            },
        })

    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
    payload = {
        "model": model,
        "max_tokens": 4096,
        "messages": [{"role": "user", "content": content}],
        "temperature": AI_TEMPERATURE,
    }

    resp = http_requests.post(
        "https://api.anthropic.com/v1/messages",
        json=payload,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    blocks = data.get("content", [])
    text = ""
    for block in blocks:
        if block.get("type") == "text":
            text += block.get("text", "")
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text


def _get_available_ram_gb() -> float:
    """Retorna a RAM livre em GB."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        c_ulonglong = ctypes.c_ulonglong
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", c_ulonglong),
                ("ullAvailPhys", c_ulonglong),
                ("ullTotalPageFile", c_ulonglong),
                ("ullAvailPageFile", c_ulonglong),
                ("ullTotalVirtual", c_ulonglong),
                ("ullAvailVirtual", c_ulonglong),
                ("ullAvailExtendedVirtual", c_ulonglong),
            ]
        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
        return mem.ullAvailPhys / (1024 ** 3)
    except Exception:
        try:
            import psutil
            return psutil.virtual_memory().available / (1024 ** 3)
        except Exception:
            return 8.0


def _pick_ollama_model(logger: Optional[LogFn] = None) -> str:
    """Escolhe o melhor modelo do Ollama baseado na RAM disponivel."""
    global _ollama_active_model

    if _ollama_active_model:
        return _ollama_active_model

    avail_ram = _get_available_ram_gb()
    _log(logger, f"[Ollama] RAM disponivel: {avail_ram:.1f} GB")

    if avail_ram < 4.0:
        _log(logger, f"[Ollama] RAM insuficiente para modelo de visao ({avail_ram:.1f}GB < 4GB). Desabilitando IA.")
        return ""

    primary_model = _ollama_primary_model()
    primary_ok = _is_model_available(primary_model, logger)
    fallback_ok = _is_model_available(OLLAMA_FALLBACK_MODEL, logger)

    if primary_ok and avail_ram >= 10.0:
        _ollama_active_model = primary_model
        _log(logger, f"[Ollama] Usando modelo principal: {primary_model} ({avail_ram:.1f}GB disponiveis)")
    elif fallback_ok:
        _ollama_active_model = OLLAMA_FALLBACK_MODEL
        _log(logger, f"[Ollama] Usando modelo leve: {OLLAMA_FALLBACK_MODEL} (RAM: {avail_ram:.1f}GB)")
    elif primary_ok:
        _ollama_active_model = primary_model
        _log(logger, f"[Ollama] Tentando modelo principal: {primary_model} (pode falhar por memoria)")
    else:
        _log(logger, f"[Ollama] Nenhum modelo de visao disponivel. Rode: ollama pull {OLLAMA_FALLBACK_MODEL}")
        return ""

    return _ollama_active_model


def _is_model_available(model_name: str, logger: Optional[LogFn] = None) -> bool:
    """Verifica se o modelo ja esta baixado no Ollama."""
    if http_requests is None:
        return False
    try:
        r = http_requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        if r.status_code != 200:
            return False
        tags = r.json().get("models", [])
        for m in tags:
            name = m.get("name", "")
            if name == model_name or name.startswith(model_name + ":"):
                return True
        return False
    except Exception:
        return False


def _call_ollama(prompt: str, image_bytes: Optional[bytes] = None, images: Optional[List[bytes]] = None, logger: Optional[LogFn] = None) -> str:
    global _ollama_consecutive_errors, _ollama_disabled_until, _ollama_active_model

    if http_requests is None:
        raise AIAssistError("requests nao instalado. Rode: pip install requests")
    if not _is_ollama_running():
        raise AIAssistError(f"Ollama nao esta rodando em {OLLAMA_HOST}")

    import time as _time
    if _ollama_disabled_until and _time.time() < _ollama_disabled_until:
        raise AIAssistError("[Ollama] Temporariamente desabilitado por erros repetidos.")

    model = _pick_ollama_model(logger=logger)
    if not model:
        raise AIAssistError("[Ollama] Nenhum modelo de visao disponivel.")

    all_images = images or ([image_bytes] if image_bytes else [])
    if all_images:
        img_b64s = [base64.b64encode(img).decode("utf-8") for img in all_images]
        payload = {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": img_b64s,
                }
            ],
            "stream": False,
            "options": {"temperature": AI_TEMPERATURE},
        }
        endpoint = f"{OLLAMA_HOST}/api/chat"
    else:
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": AI_TEMPERATURE},
        }
        endpoint = f"{OLLAMA_HOST}/api/generate"

    last_error = None
    models_to_try = [model]
    if model != OLLAMA_FALLBACK_MODEL and _is_model_available(OLLAMA_FALLBACK_MODEL, logger):
        models_to_try.append(OLLAMA_FALLBACK_MODEL)
    # Timeout reduzido: 60s para imagens, 30s para texto puro
    ollama_timeout = 60 if all_images else 30

    for attempt_model in models_to_try:
        payload["model"] = attempt_model
        for attempt in range(2):
            try:
                resp = http_requests.post(endpoint, json=payload, timeout=ollama_timeout)
                resp.raise_for_status()
                data = resp.json()
                if all_images:
                    text = (data.get("message", {}) or {}).get("content", "")
                else:
                    text = data.get("response", "")
                text = text.strip()
                text = re.sub(r"^```(?:json)?\s*", "", text)
                text = re.sub(r"\s*```$", "", text)
                _ollama_consecutive_errors = 0
                _ollama_disabled_until = 0.0
                if attempt_model != model:
                    _log(logger, f"[Ollama] Fallback para modelo leve bem-sucedido: {attempt_model}")
                    _ollama_active_model = attempt_model
                return text
            except Exception as exc:
                last_error = exc
                _ollama_consecutive_errors += 1
                _log(logger, f"[Ollama] Erro tentativa {attempt+1} com {attempt_model}: {exc}")
                if attempt == 0:
                    _time.sleep(1)

    if _ollama_consecutive_errors >= 4:
        _ollama_disabled_until = _time.time() + 300
        _log(logger, "[Ollama] Desabilitado por 5 min (erros repetidos). O bot continua sem IA.")
    elif _ollama_consecutive_errors >= 2 and model == _ollama_primary_model():
        _ollama_active_model = OLLAMA_FALLBACK_MODEL if _is_model_available(OLLAMA_FALLBACK_MODEL, logger) else ""
        if _ollama_active_model:
            _log(logger, f"[Ollama] Alternando permanentemente para modelo leve: {_ollama_active_model}")

    raise AIAssistError(f"[Ollama] Falha apos {len(models_to_try)*2} tentativas: {last_error}")


def _call_ai(prompt: str, image_bytes: Optional[bytes] = None, images: Optional[List[bytes]] = None) -> str:
    provider = _get_provider()
    if provider in ("local", "ollama"):
        return _call_ollama(prompt, image_bytes, images)
    elif provider == "openai":
        return _call_openai(prompt, image_bytes, images)
    elif provider == "anthropic":
        return _call_anthropic(prompt, image_bytes, images)
    else:
        # Default: Gemini
        return _call_gemini(prompt, image_bytes, images)


_ANALYZE_LOGIN_SCREEN_PROMPT = """
Voce e um assistente de automacao de navegador web. Analise a imagem da tela de login do portal do professor.

Identifique EXATAMENTE onde estao os seguintes elementos nesta tela:
1. Campo de CPF ou usuario (input para digitar o CPF)
2. Campo de senha (input para digitar a senha)
3. Botao de login/entrar/acessar

Para cada elemento, forneca:
- "type": "cpf_input", "password_input", "login_button"
- "selector": o seletor CSS mais especifico possivel (use name, id, class)
- "label": o texto visivel proximo ao campo (se houver)
- "coordinates": [x, y] aproximados do centro do elemento na imagem
- "confidence": "high", "medium", "low"

Retorne APENAS um JSON valido no formato:
{
  "elements": [
    {"type": "cpf_input", "selector": "input[name='_USUCOD']", "label": "CPF", "coordinates": [400, 300], "confidence": "high"},
    ...
  ],
  "description": "Descricao breve da tela",
  "has_login_form": true
}
"""

_ANALYZE_SCREEN_PROMPT_TEMPLATE = """
Voce e um assistente de automacao de navegador web. Analise a imagem da tela do portal do professor.

Objetivo: {objective}

Identifique os elementos relevantes na tela:
- Botoes, links, selects, inputs
- Textos visiveis que indicam o estado atual
- Menus e opcoes disponiveis

Para cada elemento relevante, forneca:
- "type": o tipo do elemento (button, link, select, input, text, label)
- "selector": seletor CSS especifico (use name, id, class, text content)
- "text": o texto visivel no elemento
- "action": que acao este elemento representa

Responda com:
{{
  "elements": [
    {{"type": "button", "selector": "button:has-text('Lancar Notas')", "text": "Lancar Notas", "action": "navegar para lancamento de notas"}},
    ...
  ],
  "current_screen": "nome da tela atual",
  "description": "descricao do que esta visivel",
  "next_step": "qual deveria ser o proximo passo para {objective}",
  "suggested_selector": "seletor do elemento mais provavel para o proximo clique",
  "is_expected_screen": true/false (se a tela atual corresponde ao esperado para {objective})
}}
"""


def analyze_login_screen(screenshot_bytes: bytes, logger: Optional[LogFn] = None) -> Dict[str, Any]:
    if not is_available():
        return {"elements": [], "has_login_form": False, "error": "IA nao configurada (sem API key ou Ollama offline)"}
    try:
        text = _call_ai(_ANALYZE_LOGIN_SCREEN_PROMPT, screenshot_bytes)
        result = _safe_json_parse(text, {"elements": [], "has_login_form": False, "error": "Resposta nao-JSON"})
        if "error" in result:
            _log(logger, f"[AI] Aviso tela login: {result['error']}")
        else:
            _log(logger, f"[AI] Tela de login analisada: {result.get('description', '')}")
        return result
    except Exception as exc:
        _log(logger, f"[AI] Erro ao analisar tela de login: {exc}")
        return {"elements": [], "has_login_form": False, "error": str(exc)}


def analyze_screen(
    screenshot_bytes: bytes,
    objective: str = "",
    logger: Optional[LogFn] = None,
) -> Dict[str, Any]:
    if not is_available():
        return {"elements": [], "error": "IA nao configurada"}
    prompt = _ANALYZE_SCREEN_PROMPT_TEMPLATE.format(objective=objective or "entender a tela atual")
    try:
        text = _call_ai(prompt, screenshot_bytes)
        result = _safe_json_parse(text, {"elements": [], "error": "Resposta nao-JSON"})
        if "error" in result:
            _log(logger, f"[AI] Aviso analise: {result['error']}")
        else:
            _log(logger, f"[AI] Tela analisada: {result.get('description', '')[:100]}")
        return result
    except Exception as exc:
        _log(logger, f"[AI] Erro ao analisar tela: {exc}")
        return {"elements": [], "error": str(exc)}


def find_element_on_screen(
    screenshot_bytes: bytes,
    target_description: str,
    logger: Optional[LogFn] = None,
) -> Dict[str, Any]:
    if not is_available():
        return {"found": False, "error": "IA nao configurada"}

    prompt = f"""
Analise a imagem da tela do portal do professor.

Preciso encontrar: {target_description}

Retorne APENAS JSON:
{{
  "found": true/false,
  "selector": "seletor CSS do elemento encontrado",
  "text": "texto visivel no elemento",
  "coordinates": [x, y],
  "confidence": "high/medium/low",
  "explanation": "porque este elemento corresponde a descricao"
}}
"""
    try:
        text = _call_ai(prompt, screenshot_bytes)
        return _safe_json_parse(text, {"found": False, "error": "Resposta nao-JSON da IA"})
    except Exception as exc:
        return {"found": False, "error": str(exc)}


def compare_student_names(
    name_from_notion: str,
    name_from_sge: str,
    logger: Optional[LogFn] = None,
) -> Dict[str, Any]:
    if not is_available():
        return {"match": False, "method": "unavailable"}

    prompt = f"""
Compare estes dois nomes de alunos e determine se sao a mesma pessoa.
Considere variacoes de acentos, espacos, abreviacoes e ordem dos sobrenomes.

Nome do Notion: "{name_from_notion}"
Nome no SGE: "{name_from_sge}"

Responda APENAS JSON:
{{
  "match": true/false,
  "confidence": 0.0 a 1.0,
  "reason": "explicacao curta"
}}
"""
    try:
        text = _call_ai(prompt)
        return _safe_json_parse(text, {"match": False, "error": "Resposta nao-JSON da IA"})
    except Exception as exc:
        return {"match": False, "error": str(exc)}


def suggest_next_action(
    screenshot_bytes: bytes,
    history: List[Dict[str, Any]],
    objective: str,
    logger: Optional[LogFn] = None,
) -> Dict[str, Any]:
    if not is_available():
        return {"action": None, "error": "IA nao configurada"}

    history_str = json.dumps(history[-5:], indent=2, default=str) if history else "nenhuma"
    prompt = f"""
Voce esta automatizando um portal do professor.

Objetivo atual: {objective}

Historico de acoes recentes:
{history_str}

Analise a imagem da tela atual e determine qual deve ser a PROXIMA acao.
Considere o objetivo e o historico para decidir.

Retorne APENAS JSON:
{{
  "action": "click" / "fill" / "select" / "wait" / "done" / "error",
  "selector": "seletor CSS do elemento alvo",
  "value": "valor a preencher (se action=fill ou select)",
  "description": "descricao da acao em portugues",
  "reason": "porque esta acao faz sentido agora",
  "confidence": "high/medium/low"
}}
"""
    try:
        text = _call_ai(prompt, screenshot_bytes)
        return _safe_json_parse(text, {"action": None, "error": "Resposta nao-JSON da IA"})
    except Exception as exc:
        return {"action": None, "error": str(exc)}


def _ensure_recording_dir():
    os.makedirs(AI_RECORDING_DIR, exist_ok=True)


def _safe_json_parse(text: str, fallback: Optional[Dict] = None) -> Dict[str, Any]:
    """Parse JSON de forma segura, com fallback para respostas invalidas do Ollama/Gemini."""
    if not text or not text.strip():
        return fallback if fallback is not None else {"error": "Resposta vazia da IA"}
    text = text.strip()
    # Remover markdown code fence
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    text = text.strip()
    if not text:
        return fallback if fallback is not None else {"error": "Resposta vazia apos limpeza"}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Tentar encontrar JSON na resposta (as vezes vem com texto antes/depois)
        import re as _re
        json_match = _re.search(r'\{[\s\S]*\}', text)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass
        return fallback if fallback is not None else {"error": f"JSON invalido: {text[:200]}"}


def record_demonstration_step(
    step: int,
    page: Any,
    action_performed: str,
    user_description: str = "",
    logger: Optional[LogFn] = None,
) -> Optional[str]:
    if not AI_LEARN_MODE and not _ai_assist_enabled():
        return None

    _ensure_recording_dir()
    screenshot_path = os.path.join(AI_RECORDING_DIR, f"step_{step:03d}_screen.png")
    metadata_path = os.path.join(AI_RECORDING_DIR, f"step_{step:03d}_meta.json")

    try:
        page.screenshot(path=screenshot_path, full_page=True)
        url = page.url

        metadata = {
            "step": step,
            "timestamp": time.time(),
            "url": url,
            "action": action_performed,
            "user_description": user_description,
        }
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        _log(logger, f"[AI] Passo {step} registrado: {action_performed}")
        return screenshot_path
    except Exception as exc:
        _log(logger, f"[AI] Erro ao registrar passo {step}: {exc}")
        return None


def learn_from_recording(logger: Optional[LogFn] = None) -> Optional[Dict[str, Any]]:
    if not AI_LEARN_MODE:
        return None
    if not is_available():
        _log(logger, "[AI] IA nao configurada para aprendizado.")
        return None

    _ensure_recording_dir()
    steps = sorted([
        f for f in os.listdir(AI_RECORDING_DIR)
        if f.endswith("_screen.png")
    ])

    if not steps:
        _log(logger, "[AI] Nenhum passo gravado para aprender.")
        return None

    screenshots_data = []

    for step_file in steps:
        step_num = re.search(r"(\d+)", step_file)
        step_num = int(step_num.group(1)) if step_num else 0
        meta_file = step_file.replace("_screen.png", "_meta.json")
        meta_path = os.path.join(AI_RECORDING_DIR, meta_file)

        metadata = {}
        if os.path.exists(meta_path):
            with open(meta_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

        img_path = os.path.join(AI_RECORDING_DIR, step_file)
        with open(img_path, "rb") as f:
            img_bytes = f.read()

        screenshots_data.append({
            "step": step_num,
            "metadata": metadata,
            "image_b64": base64.b64encode(img_bytes).decode("utf-8"),
        })

    prompt = f"""
Voce esta analisando uma gravacao de {len(screenshots_data)} passos de um usuario
navegando no portal do professor para lancar notas/alunos.

Cada passo contem um screenshot da tela e metadados (URL, acao realizada,
descricao do usuario).

Sua tarefa e:
1. Entender o fluxo completo que o usuario executou
2. Identificar padroes (em que tela ele clicou, o que preencheu, etc.)
3. Gerar um plano de automacao que possa replicar este fluxo

O plano deve conter, para cada passo:
- "screen_match": como identificar a tela (url, texto visivel, elemento especifico)
- "action": "click", "fill", "select", "wait"
- "target": seletor ou descricao do elemento alvo
- "value": valor a preencher (se aplicavel)
- "fallback": seletor alternativo caso o principal falhe

Responda APENAS JSON:
{{
  "workflow_name": "nome do fluxo",
  "total_steps": {len(screenshots_data)},
  "steps": [
    {{
      "step": 1,
      "screen_match": {{"url_contains": "", "text_must_be_visible": "", "key_elements": []}},
      "action": "click",
      "target": "seletor CSS",
      "value": "",
      "fallback": "seletor alternativo",
      "description": "descricao do que fazer"
    }}
  ],
  "observations": ["observacoes importantes sobre o fluxo"]
}}
"""
    try:
        images = [base64.b64decode(sd["image_b64"]) for sd in screenshots_data]
        text = _call_ai(prompt, images=images)

        plan = json.loads(text)

        plan_path = os.path.join(AI_RECORDING_DIR, "learned_plan.json")
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)

        _log(logger, f"[AI] Plano de automacao gerado com {len(plan.get('steps', []))} passos.")
        _log(logger, f"[AI] Plano salvo em: {plan_path}")
        return plan
    except Exception as exc:
        _log(logger, f"[AI] Erro ao gerar plano de automacao: {exc}")
        return None


def load_learned_plan(plan_name: str = "learned_plan.json") -> Optional[Dict[str, Any]]:
    plan_path = os.path.join(AI_RECORDING_DIR, plan_name)
    if not os.path.exists(plan_path):
        return None
    with open(plan_path, "r", encoding="utf-8") as f:
        return json.load(f)


def execute_learned_step(
    page: Any,
    step: Dict[str, Any],
    screenshot_bytes: Optional[bytes] = None,
    logger: Optional[LogFn] = None,
) -> bool:
    action = step.get("action", "")
    target = step.get("target", "")
    value = step.get("value", "")
    fallback = step.get("fallback", "")
    description = step.get("description", "")

    _log(logger, f"[AI] Executando: {description}")

    try:
        if action == "click":
            selectors = [t for t in [target, fallback] if t]
            for sel in selectors:
                loc = page.locator(sel)
                if loc.count() > 0:
                    try:
                        if loc.first.is_visible():
                            loc.first.click()
                            page.wait_for_timeout(500)
                            _log(logger, f"[AI] Clique executado: {sel}")
                            return True
                    except Exception:
                        continue

            if screenshot_bytes:
                ai_result = find_element_on_screen(screenshot_bytes, description, logger=logger)
                raw_selector = ai_result.get("selector", "")
                # Sanitiza seletor: remove { } e caracteres invalidos
                selector = (raw_selector or "").replace("{", "").replace("}", "").strip().strip("'\"")
                if ai_result.get("found") and selector:
                    try:
                        page.locator(selector).first.click(timeout=5000)
                        page.wait_for_timeout(500)
                        _log(logger, f"[AI] Clique via IA: {selector}")
                        return True
                    except Exception:
                        pass

            _log(logger, f"[AI] Nao foi possivel clicar em: {target}")
            return False

        elif action == "fill":
            loc = page.locator(target)
            if loc.count() > 0:
                loc.first.fill(value)
                _log(logger, f"[AI] Preenchido {target} com {value}")
                return True
            return False

        elif action == "select":
            loc = page.locator(target)
            if loc.count() > 0:
                loc.first.select_option(value)
                return True
            return False

        elif action == "wait":
            page.wait_for_timeout(int(value or "1000"))
            return True

        return False
    except Exception as exc:
        _log(logger, f"[AI] Erro executando passo: {exc}")
        return False


# =====================================================================
#  REFORCO IA — Analise de Falhas e Descoberta Automatica de Portais
# =====================================================================

_PORTAL_FAILURE_ANALYSIS_PROMPT = """
Voce e um especialista em automacao de navegadores web para portais escolares brasileiros.

O bot falhou ao executar uma operacao neste portal. Analise o screenshot e o erro.reportado.

Erro: {error}
Operacao: {operation}
Contexto: {context}

Analise a tela e retorne APENAS um JSON valido:
{{
  "diagnosis": "descricao curta do que parece estar errado",
  "current_screen": "o que esta visivel na tela agora",
  "suggested_fixes": [
    {{
      "action": "click/fill/select/navigate",
      "selector": "novo seletor CSS sugerido",
      "description": "o que este seletor faz",
      "confidence": 0.8
    }}
  ],
  "alternative_selectors": ["sel1", "sel2", "sel3"],
  "needs_rediscovery": true/false (se o fluxo inteiro parece ter mudado),
  "screenshot_analysis": "descricao detalhada dos elementos visiveis na tela"
}}

Seja especifico nos seletores CSS. Use name, id, class, text content.
Se a tela nao corresponde ao esperado, indique qual tela esta sendo mostrada.
"""


def analyze_portal_failure(
    screenshot_bytes: bytes,
    error: str,
    operation: str = "",
    context: str = "",
    logger: Optional[LogFn] = None,
) -> Dict[str, Any]:
    """Analisa uma falha do bot usando IA e sugere correcoes.

    Chamado quando o bot falha em clicar, preencher ou navegar.
    A IA analisa o screenshot e sugere novos seletores ou acoes.
    """
    if not is_available():
        return {"diagnosis": "IA nao disponivel", "suggested_fixes": [], "needs_rediscovery": False}

    prompt = _PORTAL_FAILURE_ANALYSIS_PROMPT.format(
        error=error,
        operation=operation or "desconhecida",
        context=context or "nenhum",
    )

    try:
        text = _call_ai(prompt, screenshot_bytes)
        result = _safe_json_parse(text, {
            "diagnosis": "Resposta nao-JSON",
            "suggested_fixes": [],
            "needs_rediscovery": False,
        })
        _log(logger, f"[AI-Falha] Diagnostico: {result.get('diagnosis', '')[:100]}")
        if result.get("needs_rediscovery"):
            _log(logger, "[AI-Falha] IA sugere redescoberta completa do portal")
        return result
    except Exception as exc:
        _log(logger, f"[AI-Falha] Erro ao analisar falha: {exc}")
        return {"diagnosis": str(exc), "suggested_fixes": [], "needs_rediscovery": False}


_PORTAL_DISCOVERY_PROMPT = """
Voce e um especialista em automacao de portais escolares brasileiros.

Analise este screenshot de um portal de professores e retorne um JSON com a estrutura completa
necessaria para automatizar o lancamento de notas.

Retorne APENAS o JSON, sem markdown, sem explicacao:
{{
  "portal_name": "nome do portal",
  "url": "url base se visivel",
  "auth_flow": {{
    "username_field": "CSS selector do campo de usuario/CPF",
    "password_field": "CSS selector do campo de senha",
    "submit": {{"selector": "CSS selector do botao de login"}}
  }},
  "navigation": {{
    "steps": [
      {{"action": "select", "selector": "CSS do select", "field": "escola"}},
      {{"action": "select", "selector": "CSS do select", "field": "turma"}},
      {{"action": "select", "selector": "CSS do select", "field": "trimestre"}}
    ]
  }},
  "grade_flow": {{
    "student_name_selector": "CSS dos nomes dos alunos",
    "grade_input_selector": "CSS dos inputs de nota",
    "assessment_selector": "CSS para selecionar avaliacao",
    "save_selector": "CSS do botao salvar",
    "pagination_selector": "CSS da paginacao"
  }},
  "columns": {{
    "1": "nome da coluna posicao 1",
    "2": "nome da coluna posicao 2"
  }},
  "confidence": 0.8,
  "notes": "observacoes sobre o portal"
}}

Se nao conseguir identificar algo, use string vazia "".
Se nao houver paginacao, deixe pagination_selector vazio.
O campo confidence deve ser entre 0 e 1.
"""


def discover_portal_from_screenshot(
    screenshot_bytes: bytes,
    logger: Optional[LogFn] = None,
) -> Optional[Dict[str, Any]]:
    """Analisa screenshot de um portal e descobre a estrutura automaticamente.

    Retorna dict com selectors, fluxo de navegacao, etc.
    Usado quando o portal e novo e nao tem adapter known.
    """
    if not is_available():
        _log(logger, "[AI-Descoberta] IA nao disponivel para descoberta")
        return None

    try:
        text = _call_ai(_PORTAL_DISCOVERY_PROMPT, screenshot_bytes)
        config = _safe_json_parse(text, None)
        if config:
            _log(logger, f"[AI-Descoberta] Portal descoberto: {config.get('portal_name', 'desconhecido')}")
            _log(logger, f"[AI-Descoberta] Confianca: {config.get('confidence', 0)}")
        return config
    except Exception as exc:
        _log(logger, f"[AI-Descoberta] Erro: {exc}")
        return None


_ADAPT_SELECTOR_PROMPT = """
O seletor CSS "{original_selector}" parou de funcionar nesta pagina web.

Acao que estava sendo tentada: {action}
Erro obtido: {error}

Analise a tela (screenshot) e sugira 3 seletores CSS alternativos que poderiam funcionar.
Retorne APENAS um JSON valido:
{{
  "alternatives": [
    {{"selector": "novo_selector_1", "reason": "motivo"},
    {{"selector": "novo_selector_2", "reason": "motivo"},
    {{"selector": "novo_selector_2", "reason": "motivo"}
  ],
  "page_changed": true/false (se a pagina parece ter mudado completamente)
}}
"""


def adapt_selector(
    original_selector: str,
    action: str,
    error: str,
    screenshot_bytes: bytes,
    logger: Optional[LogFn] = None,
) -> Dict[str, Any]:
    """Quando um selector falha, a IA sugere alternativas baseado no screenshot.

    Usado pelo custom_adapter e sge_adapter como fallback automatico.
    """
    if not is_available():
        return {"alternatives": [], "page_changed": False}

    prompt = _ADAPT_SELECTOR_PROMPT.format(
        original_selector=original_selector,
        action=action,
        error=error,
    )

    try:
        text = _call_ai(prompt, screenshot_bytes)
        result = _safe_json_parse(text, {"alternatives": [], "page_changed": False})
        alts = result.get("alternatives", [])
        if alts:
            _log(logger, f"[AI-Adapt] {len(alts)} seletores alternativos encontrados")
        return result
    except Exception as exc:
        _log(logger, f"[AI-Adapt] Erro: {exc}")
        return {"alternatives": [], "page_changed": False}
