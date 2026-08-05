"""
Interface grafica amigavel para o Bot do Professor - Lancamento de Notas.
Usa Streamlit para abrir no navegador.
Nao requer conhecimentos tecnicos.

Uso:
    streamlit run painel.py
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
import urllib.error
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st

from autofix import attempt_autofix, apply_fix

LICENSE_SERVER_URL = "https://botdoprofessor.onrender.com"
from leitor_planilhas import (
    gerar_template_notas_xlsx, gerar_template_notas_csv,
    gerar_template_sequencias_xlsx, gerar_template_sequencias_csv,
    ler_sequencias_excel, ler_sequencias_csv,
)

# === CONFIGURACAO DA PAGINA ===
st.set_page_config(
    page_title="Bot do Professor - Lancamento de Notas",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# === ESTILO CSS ===
_BASE_CSS = """
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    * { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }

    .main-header {
        font-size: 2rem; font-weight: 700; margin-bottom: 0.25rem;
        background: linear-gradient(135deg, #2563eb, #7c3aed);
        -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        background-clip: text;
    }
    .sub-header { font-size: 1rem; color: #666; margin-bottom: 1.5rem; }

    .card {
        background: #f8f9fa; border-radius: 12px; padding: 1.5rem;
        margin-bottom: 1rem; border: 1px solid #e9ecef;
        transition: box-shadow 0.2s ease, transform 0.2s ease;
    }
    .card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.08); transform: translateY(-1px); }

    .stButton button {
        width: 100%; border-radius: 8px; padding: 0.5rem 1rem; font-weight: 600;
        transition: all 0.2s ease; position: relative; overflow: hidden;
    }
    .stButton button:hover {
        transform: translateY(-1px); box-shadow: 0 4px 12px rgba(37,99,235,0.3);
    }
    .stButton button:active { transform: translateY(0); }
    .stButton button[kind="primary"] {
        background: linear-gradient(135deg, #2563eb, #7c3aed);
        border: none; color: white;
    }
    .stButton button[kind="primary"]:hover {
        background: linear-gradient(135deg, #1d4ed8, #6d28d9);
        box-shadow: 0 4px 16px rgba(37,99,235,0.4);
    }

    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] {
        border-radius: 8px; transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.15);
    }

    .st-bb, .st-bc, .st-bd, .st-be, .st-bf, .st-bg, .st-bh { border-radius: 8px; }

    div[data-testid="stMetric"] {
        background: #f8f9fa; border-radius: 10px; padding: 1rem;
        border: 1px solid #e9ecef; transition: all 0.2s ease;
    }
    div[data-testid="stMetric"]:hover {
        box-shadow: 0 4px 12px rgba(0,0,0,0.06); transform: translateY(-1px);
    }

    section[data-testid="stSidebar"] .stMarkdown h3 { font-size: 0.9rem; text-transform: uppercase; letter-spacing: 0.05em; color: #888; }

    .stAlert { border-radius: 10px; border: none; }
    .st-bw { border-radius: 8px; }

    @media (max-width: 768px) {
        .main-header { font-size: 1.5rem; }
        .row-widget.stColumns { flex-direction: column; }
    }

    @keyframes pulse-glow {
        0%, 100% { box-shadow: 0 0 0 0 rgba(37,99,235,0.4); }
        50% { box-shadow: 0 0 0 8px rgba(37,99,235,0); }
    }
    .stButton button[kind="primary"]:not(:disabled) {
        animation: pulse-glow 2s infinite;
    }

    .link-entry {
        background: #f0f4ff; border-radius: 8px; padding: 0.75rem;
        margin-bottom: 0.5rem; border-left: 3px solid #2563eb;
    }
    .link-entry-remove { color: #ef4444; cursor: pointer; font-size: 0.8rem; }
</style>
"""

_LIGHT_CSS = """
<style>
    .stApp { background: #fafbfc; color: #1a1a2e; }
    div[data-testid="stMetric"] { background: #ffffff; }
    .link-entry { background: #f0f4ff; }
</style>
"""

_DARK_THEME_CSS = """
<style>
    .stApp { background: #0e1117; color: #e0e0e0; }
    div[data-testid="stMetric"] { background: #1e2130; border-color: #2d3040; }
    div[data-testid="stMetric"]:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
    .main-header { background: linear-gradient(135deg, #60a5fa, #a78bfa); -webkit-background-clip: text; background-clip: text; }
    .sub-header { color: #888; }
    .card { background: #1e2130; border-color: #2d3040; }
    .card:hover { box-shadow: 0 4px 12px rgba(0,0,0,0.3); }
    .stTextInput input, .stTextArea textarea, .stSelectbox div[data-baseweb="select"] { background-color: #262a3a; color: #e0e0e0; border-color: #3a3d50; }
    .st-bd, .st-cf, .st-cg, .st-ch, .st-ci, .st-cj { background-color: #1e2130; color: #e0e0e0; }
    .st-dg, .st-dh, .st-di, .st-dj, .st-dk, .st-dl { background-color: #262a3a; color: #e0e0e0; }
    .stMarkdown, .stText, p, span, label { color: #c0c0d0; }
    h1, h2, h3, h4, h5, h6 { color: #e8e8f0; }
    .st-bb, .st-bc, .st-bd, .st-be, .st-bf, .st-bg, .st-bh { background-color: #262a3a; }
    .st-cx, .st-cy, .st-cz, .st-d0, .st-d1, .st-d2 { border-color: #3a3d50; }
    .stAlert { background-color: #1e2130; color: #e0e0e0; }
    section[data-testid="stSidebar"] { background-color: #12151f; }
    section[data-testid="stSidebar"] .stMarkdown, section[data-testid="stSidebar"] p { color: #b0b0c0; }
    .link-entry { background: #1a1f35; border-left-color: #3b82f6; }
</style>
"""

st.markdown(_BASE_CSS, unsafe_allow_html=True)


# === SESSAO DE ESTADO ===
if "logs" not in st.session_state:
    st.session_state.logs = []
if "executando" not in st.session_state:
    st.session_state.executando = False
if "resultado" not in st.session_state:
    st.session_state.resultado = None
if "config_path" not in st.session_state:
    st.session_state.config_path = ""
if "notion_dbs" not in st.session_state:
    st.session_state.notion_dbs = []


def log(msg: str):
    try:
        timestamp = datetime.now().strftime("%H:%M:%S")
        st.session_state.logs.append(f"[{timestamp}] {msg}")
    except Exception:
        pass


def _validar_template(fonte: str, caminho: str, tipo: str) -> tuple:
    try:
        if tipo == "notas":
            if fonte == "excel":
                import openpyxl
                wb = openpyxl.load_workbook(caminho, data_only=True)
                headers = [str(h or "") for h in next(wb.active.iter_rows(values_only=True))]
                wb.close()
            else:
                with open(caminho, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    headers = reader.fieldnames or []
            req = ["nome", "aluno"]
            found = any(any(r in h.lower() for r in req) for h in headers)
            if not found:
                return False, ["Coluna 'Nome' ou 'Aluno' nao encontrada no cabecalho"]
            return True, []
        else:
            if fonte == "excel":
                import openpyxl
                wb = openpyxl.load_workbook(caminho, data_only=True)
                headers = [str(h or "") for h in next(wb.active.iter_rows(values_only=True))]
                wb.close()
            else:
                with open(caminho, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    headers = reader.fieldnames or []
            h_lower = [h.lower() for h in headers]
            avisos = []
            if not any("ano" in h for h in h_lower):
                avisos.append("Coluna 'Ano' nao encontrada. O ano sera extraido da Turma.")
            if not any("escola" in h for h in h_lower):
                avisos.append("Coluna 'Escola' nao encontrada.")
            if not any("nome" in h or "name" in h for h in h_lower):
                avisos.append("Coluna 'Name'/'Nome' nao encontrada.")
            return len(avisos) < 3, avisos
    except Exception as exc:
        return False, [f"Erro ao ler arquivo: {exc}"]


def salvar_config():
    config = {
        "sge_url": st.session_state.get("sge_url", ""),
        "sge_cpf": st.session_state.get("sge_cpf", ""),
        "sge_senha": st.session_state.get("sge_senha", ""),
        "notion_token": st.session_state.get("notion_token", ""),
        "root_page_id": st.session_state.get("root_page_id", ""),
        "gemini_key": st.session_state.get("gemini_key", ""),
        "gemini_model": st.session_state.get("gemini_model", "gemini-2.5-flash"),
        "openai_key": st.session_state.get("openai_key", ""),
        "openai_model": st.session_state.get("openai_model", "gpt-4o"),
        "anthropic_key": st.session_state.get("anthropic_key", ""),
        "anthropic_model": st.session_state.get("anthropic_model", "claude-sonnet-4-20250514"),
        "ai_provider": st.session_state.get("ai_provider", "local"),
        "ollama_model": st.session_state.get("ollama_model", "llama3.2-vision"),
        "fonte": st.session_state.get("fonte", "notion"),
        "escola": st.session_state.get("escola", ""),
        "turno": st.session_state.get("turno", ""),
        "turma": st.session_state.get("turma", ""),
        "trimestre": st.session_state.get("trimestre", ""),
        "avaliacao_nome": st.session_state.get("avaliacao_nome", ""),
        "avaliacao_data": st.session_state.get("avaliacao_data", ""),
        "tipo": st.session_state.get("tipo", "notas"),
        "seq_titulo_documento": st.session_state.get("seq_titulo_documento", ""),
        "seq_periodo_inicio": st.session_state.get("seq_periodo_inicio", ""),
        "seq_periodo_fim": st.session_state.get("seq_periodo_fim", ""),
        "seq_n_aulas": st.session_state.get("seq_n_aulas", 4),
        "seq_drive_links": st.session_state.get("seq_drive_links", []),
    }
    config_dir = Path.home() / ".sge_bot"
    config_dir.mkdir(exist_ok=True)
    config_path = config_dir / "config.json"
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
    st.session_state.config_path = str(config_path)
    return str(config_path)


def carregar_config():
    config_paths = [
        Path.home() / ".sge_bot" / "config.json",
        Path(".env"),
        Path(".env.local"),
    ]
    for path in config_paths:
        if path.exists():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                try:
                    from dotenv import load_dotenv
                    load_dotenv(path)
                except ImportError:
                    pass
    return {}


def carregar_env():
    for env_file in [".env", ".env.local", Path.home() / ".sge_bot" / ".env"]:
        if os.path.exists(str(env_file)):
            try:
                from dotenv import load_dotenv
                load_dotenv(str(env_file))
            except ImportError:
                pass

    for key in ["SGE_LOGIN_URL", "SGE_CPF", "SGE_SENHA", "NOTION_TOKEN", "ROOT_PAGE_ID", "GEMINI_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "AI_PROVIDER", "OLLAMA_HOST"]:
        val = os.environ.get(key, "")
        if val:
            return val
    return ""


# Carrega config salva para preencher campos automaticamente
config_salva = carregar_config()
for k, v in config_salva.items():
    if v and k not in st.session_state:
        st.session_state[k] = v
# Default para ai_provider se nao veio da config
if "ai_provider" not in st.session_state:
    st.session_state.ai_provider = "local"

# Defaults para campos de sequencia (Google Drive)
for _k, _v in [("seq_titulo_documento", ""), ("seq_periodo_inicio", ""), ("seq_periodo_fim", ""), ("seq_n_aulas", 4)]:
    if _k not in st.session_state:
        st.session_state[_k] = _v

# Defaults para preferencias de exibicao
if "dark_mode" not in st.session_state:
    st.session_state.dark_mode = False
if "headless_mode" not in st.session_state:
    st.session_state.headless_mode = True

# === VALIDACAO DE LICENCA ===
BOT_LOCAL_CONFIG = Path.home() / ".bot_local" / "config.json"

def _load_license_cache():
    if not BOT_LOCAL_CONFIG.exists():
        return {}
    try:
        with open(BOT_LOCAL_CONFIG, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        key = cfg.get("license_key", "")
        validated = cfg.get("license_validated_at", "")
        plan = cfg.get("license_plan", "")
        expires = cfg.get("license_expires_at", "")
        if key and validated:
            try:
                dt = datetime.fromisoformat(validated)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if (datetime.now(timezone.utc) - dt).days < 7:
                    return {"key": key, "plan": plan, "expires": expires}
            except (ValueError, TypeError):
                pass
    except Exception:
        pass
    return {}

def _save_license_cache(key, plan, expires_at):
    try:
        BOT_LOCAL_CONFIG.parent.mkdir(parents=True, exist_ok=True)
        cfg = {}
        if BOT_LOCAL_CONFIG.exists():
            with open(BOT_LOCAL_CONFIG, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        cfg["license_key"] = key.strip().upper()
        cfg["license_plan"] = plan or ""
        cfg["license_expires_at"] = expires_at or ""
        cfg["license_validated_at"] = datetime.now(timezone.utc).isoformat()
        with open(BOT_LOCAL_CONFIG, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
    except Exception:
        pass

def _validate_license_online(key):
    data = json.dumps({"license_key": key.strip().upper()}).encode("utf-8")
    req = urllib.request.Request(
        f"{LICENSE_SERVER_URL}/api/license/public-validate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        result = json.loads(resp.read().decode("utf-8"))
        return result.get("valid", False), result
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as e:
        return False, {"error": str(e)}

def _is_network_error(data):
    """True se a falha for de rede/servidor (nao uma revogacao real de licenca)."""
    err = (data or {}).get("error", "") or ""
    lowered = err.lower()
    markers = ("servidor", "indisponivel", "timed out", "connection",
               "resolve", "network", "errno", "http error")
    return (not err) or any(m in lowered for m in markers)

if "license_valid" not in st.session_state:
    cached = _load_license_cache()
    if cached:
        valid, data = _validate_license_online(cached["key"])
        if valid:
            st.session_state.license_valid = True
            st.session_state.license_key = cached["key"]
            st.session_state.license_plan = data.get("plan", cached.get("plan", ""))
        elif _is_network_error(data):
            st.session_state.license_valid = True
            st.session_state.license_key = cached["key"]
            st.session_state.license_plan = cached.get("plan", "")
        else:
            st.session_state.license_valid = False
            st.session_state.license_key = ""
            st.session_state.license_plan = ""
            st.session_state.license_error = data.get("error", "Assinatura finalizada ou cancelada")
            st.session_state.license_resubscribe_url = data.get("resubscribe_url", "")
    else:
        st.session_state.license_valid = False
        st.session_state.license_key = ""
        st.session_state.license_plan = ""

if not st.session_state.license_valid:
    st.markdown("""
    <style>
        .blocker-bg {
            position: fixed; top: 0; left: 0; width: 100%; height: 100%;
            background: linear-gradient(135deg, #0a0e27, #1a1f3a);
            z-index: -1;
        }
        .blocker-card {
            background: #12162e; border-radius: 16px; padding: 32px;
            max-width: 440px; margin: 0 auto; text-align: center;
            box-shadow: 0 8px 32px rgba(0,0,0,0.5);
        }
        .blocker-card h1 {
            font-size: 1.8rem; font-weight: 700; margin-bottom: 4px;
            background: linear-gradient(135deg, #2563eb, #7c3aed);
            -webkit-background-clip: text; -webkit-text-fill-color: transparent;
        }
        .blocker-card p { color: #94a3b8; font-size: 0.95rem; }
    </style>
    <div class="blocker-bg"></div>
    <div style="height:64px"></div>
    <div class="blocker-card">
        <h1>BotDoProfessor</h1>
        <p>Ative sua licenca para acessar o painel</p>
    </div>
    """, unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br>", unsafe_allow_html=True)
        err_msg = st.session_state.get("license_error", "")
        if err_msg:
            st.error(err_msg)
        lic_key = st.text_input("Chave de licenca", key="lic_input",
                                placeholder="Cole sua chave aqui")
        if st.button("Validar", type="primary", use_container_width=True):
            if not lic_key.strip():
                st.error("Digite a chave de licenca")
            else:
                with st.spinner("Validando..."):
                    valid, data = _validate_license_online(lic_key)
                    if valid:
                        _save_license_cache(lic_key, data.get("plan", ""), data.get("expires_at", ""))
                        st.session_state.license_valid = True
                        st.session_state.license_key = lic_key.upper()
                        st.session_state.license_plan = data.get("plan", "")
                        st.rerun()
                    else:
                        st.error(data.get("error", "Chave invalida ou expirada"))
                        url = data.get("resubscribe_url")
                        if url:
                            st.markdown(
                                f'<a href="{url}" target="_blank" '
                                'style="display:inline-block;margin-top:6px;">'
                                '<button style="background:#e94560;color:white;border:none;'
                                'padding:10px 18px;border-radius:8px;font-weight:bold;'
                                'cursor:pointer;width:100%;">'
                                'Corrigir pagamento / Assinar / Reassinar</button></a>',
                                unsafe_allow_html=True,
                            )
        resub = st.session_state.get("license_resubscribe_url") or "https://botdoprofessor.onrender.com/checkout"
        st.markdown(
            f'<a href="{resub}" target="_blank">'
            'Nao tem chave? Compre ou reassine aqui</a>',
            unsafe_allow_html=True,
        )
    st.stop()


# === BARRA LATERAL ===
with st.sidebar:
    plan_label = st.session_state.get("license_plan", "").capitalize() if st.session_state.get("license_plan") else ""
    if plan_label:
        st.markdown(
            f"<div style='background:#1a2a1a;border:1px solid #2a5a2a;border-radius:8px;padding:6px 12px;margin-bottom:12px;font-size:0.85rem;color:#5ae05a;text-align:center;'>"
            f"Licenca {plan_label}</div>",
            unsafe_allow_html=True,
        )
    st.markdown("### Configuracoes")

    with st.expander("Portal do Professor", expanded=True):
        sge_url = st.text_input(
            "URL do Portal do Professor",
            value=st.session_state.get("sge_url", carregar_env() or "https://www.sge8147.com.br/hportalprofessor.aspx"),
            key="sge_url_input",
            placeholder="https://...",
        )
        st.session_state.sge_url = sge_url

        col1, col2 = st.columns(2)
        with col1:
            cpf = st.text_input("CPF", value=st.session_state.get("sge_cpf", ""), key="sge_cpf_input", type="password")
            st.session_state.sge_cpf = cpf
        with col2:
            senha = st.text_input("Senha", value=st.session_state.get("sge_senha", ""), key="sge_senha_input", type="password")
            st.session_state.sge_senha = senha

    with st.expander("API Keys", expanded=True):
        notion_token = st.text_input(
            "Notion Token (secret_...)",
            value=st.session_state.get("notion_token", ""),
            key="notion_token_input",
            type="password",
        )
        st.session_state.notion_token = notion_token

        root_page_id = st.text_input(
            "Root Page ID",
            value=st.session_state.get("root_page_id", ""),
            key="root_page_id_input",
        )
        st.session_state.root_page_id = root_page_id

    st.markdown("---")
    ai_provider_options = ["local", "gemini", "openai", "anthropic"]
    ai_provider_index = 0
    saved_provider = st.session_state.get("ai_provider", "")
    if saved_provider in ai_provider_options:
        ai_provider_index = ai_provider_options.index(saved_provider)
    ai_provider = st.selectbox(
        "Provedor IA",
        options=ai_provider_options,
        format_func=lambda x: {
            "local": "Local (Ollama - minicpm-v4.6) [RECOMENDADO]",
            "gemini": "Google Gemini (API Key)",
            "openai": "OpenAI GPT-4o (API Key)",
            "anthropic": "Anthropic Claude (API Key)",
        }.get(x, x),
        index=ai_provider_index,
        key="ai_provider_select",
    )
    st.session_state.ai_provider = ai_provider

    # Campo de API key dinamico conforme provider
    if ai_provider == "local":
        st.info(
            "**IA Local (Recomendada)** - Nao precisa de API key!\n\n"
            "O modelo `minicpm-v4.6` e baixado automaticamente na primeira execucao (~1.6GB).\n\n"
            "**O que faz:**\n"
            "- Analisa screenshots quando o bot falha\n"
            "- Sugere seletores CSS alternativos\n"
            "- Redescobre portais automaticamente\n"
            "- Aprende com cada execucao\n\n"
            "**Requisitos:** RAM minima 4GB, processador com 4+ cores"
        )
        ollama_model = st.selectbox(
            "Modelo Ollama",
            options=["openbmb/minicpm-v4.6", "llava:7b", "llava:13b", "bakllava"],
            index=0,
            key="ollama_model_select",
        )
        st.session_state.ollama_model = ollama_model
    elif ai_provider == "gemini":
        st.markdown(
            "**Como obter a API Key do Google Gemini:**\n\n"
            "1. Acesse https://aistudio.google.com/apikey\n"
            "2. Clique em **Create API Key**\n"
            "3. Copie a chave (comeca com `AIza...`)\n"
            "4. Cole abaixo\n\n"
            "**Gratuito:** 15 requests/min, 1500 requests/dia"
        )
        gemini_key = st.text_input(
            "Gemini API Key (obrigatoria)",
            value=st.session_state.get("gemini_key", ""),
            key="gemini_key_input",
            type="password",
        )
        st.session_state.gemini_key = gemini_key
        gemini_model = st.text_input(
            "Modelo Gemini",
            value=st.session_state.get("gemini_model", "gemini-2.5-flash"),
            key="gemini_model_input",
        )
        st.session_state.gemini_model = gemini_model
    elif ai_provider == "openai":
        st.markdown(
            "**Como obter a API Key da OpenAI:**\n\n"
            "1. Acesse https://platform.openai.com/api-keys\n"
            "2. Clique em **Create new secret key**\n"
            "3. Copie a chave (comeca com `sk-...`)\n"
            "4. Cole abaixo\n\n"
            "**Pago:** $2.50 por 1M tokens de input (GPT-4o-mini)"
        )
        openai_key = st.text_input(
            "OpenAI API Key (obrigatoria)",
            value=st.session_state.get("openai_key", ""),
            key="openai_key_input",
            type="password",
        )
        st.session_state.openai_key = openai_key
        openai_model = st.text_input(
            "Modelo OpenAI",
            value=st.session_state.get("openai_model", "gpt-4o"),
            key="openai_model_input",
        )
        st.session_state.openai_model = openai_model
    elif ai_provider == "anthropic":
        st.markdown(
            "**Como obter a API Key da Anthropic:**\n\n"
            "1. Acesse https://console.anthropic.com/settings/keys\n"
            "2. Clique em **Create Key**\n"
            "3. Copie a chave (comeca com `sk-ant-...`)\n"
            "4. Cole abaixo\n\n"
            "**Pago:** $3 por 1M tokens de input (Claude Sonnet)"
        )
        anthropic_key = st.text_input(
            "Anthropic API Key (obrigatoria)",
            value=st.session_state.get("anthropic_key", ""),
            key="anthropic_key_input",
            type="password",
        )
        st.session_state.anthropic_key = anthropic_key
        anthropic_model = st.text_input(
            "Modelo Anthropic",
            value=st.session_state.get("anthropic_model", "claude-sonnet-4-20250514"),
            key="anthropic_model_input",
        )
        st.session_state.anthropic_model = anthropic_model

    with st.expander("Origem dos Dados", expanded=True):
        st.markdown("**De onde vao os dados das notas?**")
        fonte = st.selectbox(
            "Selecione a origem",
            options=["notion", "imagem", "excel", "csv", "google_sheets", "google_drive"],
            format_func=lambda x: {
                "notion": "Notion (bancos de dados)",
                "imagem": "Imagem / Foto (extrair notas com IA)",
                "excel": "Arquivo Excel (.xlsx)",
                "csv": "Arquivo CSV",
                "google_sheets": "Google Sheets (planilha online)",
                "google_drive": "Google Drive (arquivo compartilhado)",
            }.get(x, x),
            index=0,
            key="fonte_select",
        )
        st.session_state.fonte = fonte

        if fonte == "notion":
            st.info(
                "Os dados serao buscados automaticamente das databases do Notion "
                "configuradas nas API Keys acima."
            )
        elif fonte == "imagem":
            st.info(
                "Envie uma foto ou print na seção 'Filtros' abaixo. "
                "A IA extrairá as notas automaticamente."
            )
        elif fonte in ("excel", "csv"):
            ext = "XLSX / XLS" if fonte == "excel" else "CSV"
            st.info(f"Selecione o arquivo **{ext}** do seu computador.")
            arquivo = st.file_uploader(
                f"Clique aqui para selecionar o arquivo {fonte.upper()}",
                type=["xlsx", "xls"] if fonte == "excel" else ["csv"],
            )
            if arquivo:
                tmp_dir = Path(tempfile.gettempdir()) / "sge_bot_uploads"
                tmp_dir.mkdir(exist_ok=True)
                tmp_path = tmp_dir / arquivo.name
                with open(tmp_path, "wb") as f:
                    f.write(arquivo.getbuffer())
                st.session_state["arquivo_path"] = str(tmp_path)
                st.success(f"Arquivo salvo: {arquivo.name}")
                valido, avisos = _validar_template(fonte, tmp_path, st.session_state.get("tipo", "notas"))
                if valido:
                    st.success("Template valido! Pronto para executar.")
                for aviso in avisos:
                    st.warning(aviso)
        elif fonte == "google_sheets":
            st.info(
                "Cole o link compartilhavel do **Google Sheets** abaixo.\n\n"
                "Ex: `https://docs.google.com/spreadsheets/d/...`"
            )
            link = st.text_input(
                "URL compartilhavel do Google Sheets:",
                key="link_input",
                placeholder="https://docs.google.com/spreadsheets/d/...",
            )
            st.session_state["link_url"] = link
        elif fonte == "google_drive":
            st.info(
                "Cole os links dos arquivos do Drive na seção **'Filtros'** abaixo, "
                "um para cada ano."
            )

    with st.expander("Download de Templates", expanded=False):
        st.markdown("**Baixe o modelo, preencha, e use no bot:**")
        col_t1, col_t2 = st.columns(2)
        with col_t1:
            st.markdown("**Notas (alunos)**")
            st.download_button(
                "📥 .xlsx",
                data=gerar_template_notas_xlsx(),
                file_name="template_notas.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            st.download_button(
                "📥 .csv",
                data=gerar_template_notas_csv(),
                file_name="template_notas.csv",
                mime="text/csv",
                use_container_width=True,
            )
        with col_t2:
            st.markdown("**Sequência Didática**")
            st.download_button(
                "📥 .xlsx",
                data=gerar_template_sequencias_xlsx(),
                file_name="template_sequencia_didatica.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )
            st.download_button(
                "📥 .csv",
                data=gerar_template_sequencias_csv(),
                file_name="template_sequencia_didatica.csv",
                mime="text/csv",
                use_container_width=True,
            )

    with st.expander("Filtros"):
        tipo = st.radio(
            "Tipo de lancamento:",
            options=["notas", "chamada", "sequencia"],
            format_func=lambda x: {
                "notas": "Notas",
                "chamada": "Chamada (foto do diario)",
                "sequencia": "Sequência Didática",
            }.get(x, x),
            horizontal=True,
            key="tipo_radio",
        )
        st.session_state.tipo = tipo

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            escola = st.text_input(
                "Escola",
                key="escola_input",
                placeholder="vazio = todas as escolas",
            )
            st.session_state.escola = escola
            turma = st.text_input(
                "Turma (ex: 6o Ano)",
                key="turma_input",
                placeholder="vazio = todas as turmas",
            )
            st.session_state.turma = turma
        with col_f2:
            turno = st.selectbox("Turno", options=["", "Matutino", "Vespertino", "Noturno"], key="turno_select")
            st.session_state.turno = turno
            trimestre = st.selectbox("Trimestre", options=["", "1o Trimestre", "2o Trimestre", "3o Trimestre"], key="trimestre_select")
            st.session_state.trimestre = trimestre

        if st.session_state.get("fonte", "") == "google_drive" and tipo == "notas":
            st.markdown("**Arquivo no Google Drive**")
            st.caption("Cole o link do arquivo usado como origem das notas.")
            link_drive_notas = st.text_input(
                "Link do arquivo no Drive:",
                key="link_input_drive_notas",
                placeholder="https://drive.google.com/file/d/...",
            )
            st.session_state["link_url"] = link_drive_notas

        if tipo == "sequencia":
            filtros_ativos = [k for k in ["escola", "turno", "turma"] if st.session_state.get(k, "")]
            if not filtros_ativos:
                st.info("Publicara em **todas as escolas, turnos e turmas** disponiveis.")
            else:
                st.caption(f"Filtros ativos: {', '.join(filtros_ativos)}")

            if st.session_state.get("fonte", "") == "google_drive":
                st.markdown("**Links do Google Drive por Ano**")
                st.caption("Cole os links dos PDFs para cada ano. Deixe vazio o que nao for lancar.")

                if "seq_drive_links" not in st.session_state:
                    st.session_state.seq_drive_links = [
                        {"ano": "6º Ano", "link": ""},
                        {"ano": "7º Ano", "link": ""},
                        {"ano": "8º Ano", "link": ""},
                        {"ano": "9º Ano", "link": ""},
                    ]

                for i, entry in enumerate(st.session_state.seq_drive_links):
                    cols = st.columns([1.2, 4, 0.5])
                    with cols[0]:
                        entry["ano"] = st.selectbox(
                            "Ano",
                            ["6º Ano", "7º Ano", "8º Ano", "9º Ano"],
                            index=["6º Ano", "7º Ano", "8º Ano", "9º Ano"].index(entry["ano"]),
                            key=f"seq_drive_ano_{i}",
                            label_visibility="collapsed",
                        )
                    with cols[1]:
                        entry["link"] = st.text_input(
                            "Link do Drive",
                            value=entry["link"],
                            key=f"seq_drive_link_{i}",
                            placeholder="https://drive.google.com/file/d/...",
                            label_visibility="collapsed",
                        )
                    with cols[2]:
                        if len(st.session_state.seq_drive_links) > 1:
                            if st.button("✕", key=f"seq_drive_rm_{i}", help="Remover"):
                                st.session_state.seq_drive_links.pop(i)
                                st.rerun()

                if st.button("+ Adicionar ano", key="add_drive_link", use_container_width=True):
                    st.session_state.seq_drive_links.append({"ano": "6º Ano", "link": ""})
                    st.rerun()

                st.markdown("**Campos comuns a todos os anos:**")
                col_g1, col_g2 = st.columns(2)
                with col_g1:
                    st.text_input(
                        "Título do Documento",
                        key="seq_titulo_documento",
                        placeholder="Sequência - Matemática",
                    )
                    st.text_input(
                        "Período início (dd/mm/aaaa)",
                        key="seq_periodo_inicio",
                        placeholder="01/03/2026",
                    )
                with col_g2:
                    st.number_input(
                        "Nº de aulas",
                        min_value=1, max_value=40, value=4,
                        key="seq_n_aulas",
                    )
                    st.text_input(
                        "Período fim (dd/mm/aaaa)",
                        key="seq_periodo_fim",
                        placeholder="31/03/2026",
                    )

        if tipo == "chamada":
            st.markdown("---")
            st.markdown("**Chamada diaria por foto do diario de classe**")
            st.caption(
                "Envie a foto da chamada do dia. A IA le a grade (aluno x dia), o bot "
                "compara com o que ja esta lancado no SGE e NAO repreenche dias/duplicados."
            )
            foto_chamada = st.file_uploader(
                "Foto do diario de classe (chamada do dia)",
                type=["jpg", "jpeg", "png", "webp"],
                key="chamada_foto_upload",
            )
            if foto_chamada:
                tmp_dir = Path(tempfile.gettempdir()) / "sge_bot_uploads"
                tmp_dir.mkdir(exist_ok=True)
                tmp_path = tmp_dir / foto_chamada.name
                with open(tmp_path, "wb") as f:
                    f.write(foto_chamada.getbuffer())
                st.session_state["chamada_foto_path"] = str(tmp_path)
                st.success(f"Foto salva: {foto_chamada.name}")
            else:
                st.session_state.pop("chamada_foto_path", None)

            col_c1, col_c2 = st.columns(2)
            with col_c1:
                chamada_dia = st.text_input(
                    "Dia da chamada (dd/mm/aaaa)",
                    key="chamada_dia_input",
                    placeholder="05/08/2026",
                    help="Data do dia da chamada no diario. Usada para abrir o dia no SGE.",
                )
                st.session_state.chamada_dia = chamada_dia
            with col_c2:
                chamada_disciplina = st.text_input(
                    "Disciplina (opcional, ex: ENSINO RELIGIOSO)",
                    key="chamada_disciplina_input",
                    help="Se deixar vazio, o bot usa a disciplina da pagina aberta no SGE.",
                )
                st.session_state.chamada_disciplina = chamada_disciplina

        if tipo == "notas":
            st.markdown("---")
            st.markdown("**Imagem / Foto (extrair notas com IA)**")
            img = st.file_uploader(
                "Envie foto ou print com notas dos alunos",
                type=["jpg", "jpeg", "png", "webp"],
                key="imagem_upload",
            )
            if img:
                tmp_dir = Path(tempfile.gettempdir()) / "sge_bot_uploads"
                tmp_dir.mkdir(exist_ok=True)
                tmp_path = tmp_dir / img.name
                with open(tmp_path, "wb") as f:
                    f.write(img.getbuffer())
                st.session_state["imagem_path"] = str(tmp_path)
                st.success(f"Imagem salva: {img.name}")
                st.caption("Informe abaixo o **nome da atividade** e a **data** para o bot localizar no portal:")
                col_ia1, col_ia2 = st.columns(2)
                with col_ia1:
                    avaliacao_nome = st.text_input(
                        "Nome da atividade (ex: Prova 1, Trabalho 2)",
                        key="avaliacao_input",
                        help="Nome da atividade que aparece no portal. O bot identifica por este nome."
                    )
                    st.session_state.avaliacao_nome = avaliacao_nome
                with col_ia2:
                    avaliacao_data = st.text_input(
                        "Data da atividade (dd/mm/aaaa)",
                        key="avaliacao_data_input",
                        help="Data de realização para o bot localizar/validar no portal."
                    )
                    st.session_state.avaliacao_data = avaliacao_data
            else:
                st.session_state.pop("imagem_path", None)
                st.session_state.pop("avaliacao_nome", None)
                st.session_state.pop("avaliacao_data", None)

            if st.session_state.get("fonte", "notion") != "imagem":
                st.markdown("---")
                st.markdown("**Atalho: Lançar apenas 1 avaliação** (reduz tempo drasticamente)")
                col_a1, col_a2 = st.columns(2)
                with col_a1:
                    avaliacao_nome = st.text_input(
                        "Nome da avaliação (ex: Prova 1, Trabalho 2)",
                        key="avaliacao_atalho_input",
                        help="Se preenchido, o bot ignora as outras avaliações e lança apenas esta."
                    )
                    st.session_state.avaliacao_nome = avaliacao_nome
                with col_a2:
                    avaliacao_data = st.text_input(
                        "Data da avaliação (dd/mm/aaaa)",
                        key="avaliacao_data_atalho_input",
                        help="Data de realização para validação. Se vazio, usa a data do Notion."
                    )
                    st.session_state.avaliacao_data = avaliacao_data

            lote = st.checkbox(
                "Modo Lote: processar todas as escolas, turmas e trimestres",
                value=False,
                key="lote_check",
                help="Quando ativo, ignora os filtros acima e processa tudo que estiver no Notion (6o ao 9o ano)."
            )
            st.session_state.lote = lote

    ia_opcao = st.radio(
        "Assistencia IA:",
        options=["nenhuma", "assistida", "aprendizado"],
        format_func=lambda x: {"nenhuma": "Nao usar", "assistida": "Sim - Assistida", "aprendizado": "Sim - Aprendizado"}.get(x, x),
        horizontal=True,
        key="ia_radio",
    )

    st.markdown("---")
    st.markdown("**Opcoes de execucao**")

    with st.expander("Modo headless (navegador invisivel)"):
        st.markdown(
            "Quando ativado, o navegador roda em **segundo plano** sem mostrar nada na tela. "
            "Deixe marcado para uso normal.\n\n"
            "**Desmarque** apenas se quiser **ver** o navegador sendo controlado passo a passo "
            "(para entender o que o programa faz ou para tirar duvidas)."
        )
        headless_mode = st.checkbox("Rodar em segundo plano (recomendado)", value=st.session_state.headless_mode, key="headless_check")
        st.session_state.headless_mode = headless_mode

    with st.expander("Modo Dry-run (apenas simular)"):
        st.markdown(
            "Quando ativado, o programa **apenas simula** o lancamento — ele mostra o que "
            "seria feito, mas **nao envia nada** para o portal.\n\n"
            "Use sempre marcado na primeira vez para conferir se os dados estao corretos.\n"
            "**Desmarque** quando quiser realmente enviar as notas para o portal."
        )
        dry_run = st.checkbox("Simular sem enviar (recomendado)", value=True, key="dry_run_check")

    with st.expander("Auto-fix IA (correcao automatica)"):
        st.markdown(
            "Quando ativado, se acontecer algum erro (ex: data no formato errado, link invalido, "
            "demora para carregar), o programa **tenta corrigir sozinho** usando inteligencia "
            "artificial local.\n\n"
            "Se conseguir corrigir, uma mensagem explica o que foi ajustado e voce pode clicar "
            "em **Tentar novamente**.\n\n"
            "Requer o Ollama instalado (ja configurado neste computador)."
        )
        autofix_enabled = st.checkbox("Corrigir erros automaticamente", value=st.session_state.get("autofix_enabled", False), key="autofix_check")
        st.session_state.autofix_enabled = autofix_enabled

    with st.expander("Modo escuro"):
        st.markdown("Alterna entre tema claro e escuro da interface.")
        dark_mode = st.checkbox("Usar tema escuro", value=st.session_state.dark_mode, key="dark_check")
        st.session_state.dark_mode = dark_mode
    salvar = st.button("Salvar Configuracao")

    if salvar:
        path = salvar_config()
        st.success(f"Configuracao salva em {path}")

    limpar = st.button("Limpar Logs")
    if limpar:
        st.session_state.logs = []
        st.session_state.resultado = None


# === TEMA DINAMICO ===
if st.session_state.get("dark_mode", False):
    st.markdown(_DARK_THEME_CSS, unsafe_allow_html=True)

# === AREA PRINCIPAL ===
st.markdown('<div class="main-header">Bot do Professor - Automacao de Notas</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">Lance notas do Notion/planilhas no portal do professor sem precisar de terminal</div>',
    unsafe_allow_html=True,
)

# === BOTAO PRINCIPAL ===
col_btn1, col_btn2, col_btn3 = st.columns([2, 1, 1])

with col_btn1:
    pode_executar = (
        st.session_state.get("sge_cpf", "")
        and st.session_state.get("sge_senha", "")
    )
    if not pode_executar:
        st.warning("Preencha CPF e Senha do portal na barra lateral")

    executar_btn = st.button(
        "EXECUTAR LANCAMENTO",
        type="primary",
        disabled=(not pode_executar or st.session_state.executando),
        use_container_width=True,
    )

with col_btn2:
    abrir_terminal = st.button("Abrir Terminal")
    if abrir_terminal:
        st.info("Para usar via terminal: python app.py")

with col_btn3:
    ajuda_btn = st.button("Ajuda / Tutorial", use_container_width=True)

if ajuda_btn:
    st.markdown("### Como usar")
    st.markdown("""
    1. **Portal do Professor**: Informe a URL, CPF e senha
    2. **API Keys**: Cole o token do Notion e o ID da pagina raiz
    3. **Origem**: Escolha de onde ler os dados (Notion, Excel, CSV, Google)
    4. **Filtros**: Opcionais - para filtrar por escola/turma
    5. **Modo Lote**: Marque para processar todas as escolas, turmas e trimestres automaticamente
    6. **Dry-run**: Recomendado para testar antes do envio real
    7. **Executar**: Clique no botao verde e acompanhe os logs
    """)

# === EXECUCAO ===
if executar_btn or st.session_state.pop("autofix_trigger", False):
    st.session_state.executando = True
    st.session_state.logs = []
    st.session_state.resultado = None

    log("Iniciando execucao...")

    # === BARRA DE PROGRESSO ===
    status = st.status("Iniciando...", expanded=True)
    progress_bar = st.progress(0, text="Aguardando...")
    status_text = st.empty()

    def log_progress(msg):
        log(msg)
        try:
            m = re.search(r'\[(\d+)/(\d+)\]', msg)
            if m:
                cur, tot = int(m.group(1)), int(m.group(2))
                pct = cur / tot
                progress_bar.progress(pct, text=f"{cur}/{tot} blocos")
                status.update(label=f"Processando bloco {cur}/{tot}")
            elif "Concluido" in msg or "concluido" in msg.lower():
                progress_bar.progress(1.0, text="Concluido!")
                status.update(label="Concluido!", state="complete")
            elif "ERRO" in msg or "erro" in msg.lower():
                status.update(label=msg[:80], state="error")
            elif "Iniciando" in msg or "Carregando" in msg or "Login" in msg or "login" in msg:
                progress_bar.progress(0.05, text=msg[:80])
            status_text.text(msg)
        except Exception:
            pass

    def _handle_exec_error(exc: Exception, lp: callable):
        import traceback as _tb
        tb_str = "".join(_tb.format_exception(type(exc), exc, exc.__traceback__))
        lp(f"ERRO: {exc}")
        print(tb_str)

        autofix_on = st.session_state.get("autofix_enabled", False)
        attempts = st.session_state.get("autofix_attempts", 0)
        if autofix_on and attempts < 3 and not str(exc).startswith("st."):
            ctx = {
                "escola": st.session_state.get("escola", ""),
                "turno": st.session_state.get("turno", ""),
                "turma": st.session_state.get("turma", ""),
                "trimestre": st.session_state.get("trimestre", ""),
                "tipo": st.session_state.get("tipo", ""),
                "fonte": st.session_state.get("fonte", ""),
                "seq_titulo_documento": st.session_state.get("seq_titulo_documento", ""),
                "seq_periodo_inicio": st.session_state.get("seq_periodo_inicio", ""),
                "seq_periodo_fim": st.session_state.get("seq_periodo_fim", ""),
                "seq_n_aulas": st.session_state.get("seq_n_aulas", 4),
                "link_url": st.session_state.get("link_url", ""),
                "headless_mode": st.session_state.get("headless_mode", True),
                "dry_run": st.session_state.get("dry_run", True),
            }
            result = attempt_autofix(str(exc), tb_str, ctx, logger=lp, attempt=attempts)
            if result and result.get("fixable"):
                applied = apply_fix(result, st.session_state)
                if applied:
                    lp(f"Autofix aplicado: {applied}")
                    st.session_state.autofix_message = result.get("explanation", "Erro corrigido automaticamente.")
                    st.session_state.autofix_attempts = attempts + 1
                    st.session_state.autofix_trigger = True
                    st.rerun()
                else:
                    lp("Autofix: correcao sugerida nao pode ser aplicada.")
            else:
                motivo = result.get("explanation", "Erro nao corrigivel automaticamente.") if result else "Sem resposta da IA."
                lp(f"Autofix: {motivo}")

    try:
        # Prepara variaveis de ambiente
        os.environ["HEADLESS"] = "1" if st.session_state.get("headless_mode", True) else "0"
        os.environ["SGE_LOGIN_URL"] = st.session_state.sge_url
        os.environ["SGE_CPF"] = st.session_state.sge_cpf
        os.environ["SGE_SENHA"] = st.session_state.sge_senha

        if st.session_state.notion_token:
            os.environ["NOTION_TOKEN"] = st.session_state.notion_token
        if st.session_state.root_page_id:
            os.environ["ROOT_PAGE_ID"] = st.session_state.root_page_id
        if st.session_state.gemini_key:
            os.environ["GEMINI_API_KEY"] = st.session_state.gemini_key

        ai_provider = st.session_state.get("ai_provider", "local")
        os.environ["AI_PROVIDER"] = ai_provider

        # Configura API key e modelo conforme provider escolhido
        if ai_provider == "gemini":
            gemini_key = st.session_state.get("gemini_key", "")
            if gemini_key:
                os.environ["GEMINI_API_KEY"] = gemini_key
            gemini_model = st.session_state.get("gemini_model", "gemini-2.5-flash")
            os.environ["AI_MODEL"] = gemini_model
        elif ai_provider == "openai":
            openai_key = st.session_state.get("openai_key", "")
            if openai_key:
                os.environ["OPENAI_API_KEY"] = openai_key
            openai_model = st.session_state.get("openai_model", "gpt-4o")
            os.environ["OPENAI_MODEL"] = openai_model
        elif ai_provider == "anthropic":
            anthropic_key = st.session_state.get("anthropic_key", "")
            if anthropic_key:
                os.environ["ANTHROPIC_API_KEY"] = anthropic_key
            anthropic_model = st.session_state.get("anthropic_model", "claude-sonnet-4-20250514")
            os.environ["ANTHROPIC_MODEL"] = anthropic_model
        elif ai_provider == "local":
            ollama_model = st.session_state.get("ollama_model", "llama3.2-vision")
            os.environ["OLLAMA_MODEL"] = ollama_model

        if ia_opcao != "nenhuma":
            os.environ["AI_ASSIST"] = "1"
            if ia_opcao == "aprendizado":
                os.environ["AI_LEARN_MODE"] = "1"

        # Verifica IA local (Ollama) antes de iniciar o navegador
        if ai_provider == "local" and ia_opcao not in ("nenhuma", ""):
            log_progress("Verificando Ollama (IA local)...")
            log_progress("Nota: download pode levar varios minutos na primeira execucao.")
            try:
                from ai_assist import ensure_ollama
                if not ensure_ollama(logger=log_progress):
                    log_progress("Aviso: Ollama nao disponivel. IA assistida sera limitada.")
            except Exception as exc:
                log_progress(f"Aviso: falha ao configurar Ollama: {exc}")
        elif ai_provider in ("gemini", "openai", "anthropic") and ia_opcao not in ("nenhuma", ""):
            # Verificar se a API key foi fornecida
            key_available = False
            if ai_provider == "gemini" and st.session_state.get("gemini_key"):
                key_available = True
            elif ai_provider == "openai" and st.session_state.get("openai_key"):
                key_available = True
            elif ai_provider == "anthropic" and st.session_state.get("anthropic_key"):
                key_available = True
            if not key_available:
                log_progress(f"Aviso: API key para {ai_provider.upper()} nao fornecida. IA sera desabilitada.")

        # Determina tipo de execucao
        if st.session_state.tipo == "notas":
            if st.session_state.fonte == "notion":
                log_progress("Carregando dados do Notion...")
                from lancar_notas_sge import executar_lancamento

                # Modo lote: ignora filtros, processa tudo
                if st.session_state.get("lote", False):
                    log_progress("[LOTE] Modo lote ativo: processando todas as escolas, turmas e trimestres...")
                    filtro = None
                else:
                    filtro = {}
                    if st.session_state.escola:
                        filtro["escola"] = st.session_state.escola
                    if st.session_state.turno:
                        filtro["turno"] = st.session_state.turno
                    if st.session_state.turma:
                        filtro["turma"] = st.session_state.turma
                    if st.session_state.trimestre:
                        filtro["trimestre"] = st.session_state.trimestre
                    # Atalho: filtrar por avaliacao especifica
                    avaliacao_nome = st.session_state.get("avaliacao_nome", "").strip()
                    avaliacao_data = st.session_state.get("avaliacao_data", "").strip()
                    if avaliacao_nome:
                        filtro["atividade"] = avaliacao_nome
                        log_progress(f"[ATALHO] Filtrando apenas avaliacao: '{avaliacao_nome}'")
                    if avaliacao_data:
                        filtro["data_realizacao"] = avaliacao_data
                        log_progress(f"[ATALHO] Data da avaliacao: {avaliacao_data}")
                    if not filtro:
                        filtro = None

                resultado = executar_lancamento(
                    filtro=filtro,
                    logger=log_progress,
                    dry_run=dry_run,
                )
                st.session_state.resultado = resultado
                log_progress(f"Concluido! Notas: {resultado['notas']}, Preenchidas: {resultado['notas_preenchidas']}, Ausentes: {resultado.get('ausentes', 0)}, Falhas: {resultado['falhas']}")

            else:
                registros = []
                fonte = st.session_state.fonte
                fonte_path = ""

                if fonte == "imagem":
                    fonte_path = st.session_state.get("imagem_path", "")
                    if not fonte_path:
                        log_progress("ERRO: Nenhuma imagem selecionada.")
                        log_progress("Selecione uma imagem na seção 'Filtros' antes de executar.")
                        st.session_state.resultado = {"blocos": 0, "notas": 0, "notas_preenchidas": 0, "ausentes": 0, "falhas": 0}
                        st.stop()

                    log_progress("Extraindo notas da imagem com IA (reforcada)...")
                    try:
                        from ai_assist import extrair_notas_imagem
                        with open(fonte_path, "rb") as f:
                            image_bytes = f.read()

                        extraidas = extrair_notas_imagem(
                            image_bytes,
                            logger=log_progress,
                        )

                        if not extraidas:
                            log_progress("AVISO: IA nao conseguiu extrair notas da imagem.")
                            st.session_state.resultado = {"notas": 0, "notas_preenchidas": 0, "ausentes": 0, "falhas": 0}
                            st.stop()

                        log_progress(f"Extraidas {len(extraidas)} notas da imagem.")
                        escola = st.session_state.get("escola", "")
                        turno = st.session_state.get("turno", "")
                        turma = st.session_state.get("turma", "")
                        trimestre = st.session_state.get("trimestre", "")
                        atividade = st.session_state.get("avaliacao_nome", "").strip()
                        data_realizacao = st.session_state.get("avaliacao_data", "").strip()
                        if not atividade:
                            log_progress("ERRO: Informe o nome da atividade (abaixo da imagem) para o bot identificar no portal.")
                            st.error("Informe o **nome da atividade** abaixo da imagem antes de executar.")
                            st.session_state.resultado = {"notas": 0, "notas_preenchidas": 0, "ausentes": 0, "falhas": 1}
                            st.stop()
                        log_progress(f"[IMAGEM] Atividade: '{atividade}' | Data: {data_realizacao or 'nao informada'}")

                        from leitor_planilhas import RegistroNota
                        for item in extraidas:
                            aluno = item.get("aluno", "").strip()
                            nota = str(item.get("nota", "")).strip().replace(",", ".")
                            if not aluno or not nota:
                                continue
                            try:
                                float(nota)
                            except ValueError:
                                continue
                            registros.append(RegistroNota(
                                escola=escola, turno=turno, turma=turma,
                                trimestre=trimestre, aluno=aluno,
                                atividade=atividade, nota=nota,
                                data_realizacao=data_realizacao,
                            ))

                    except Exception as exc:
                        log_progress(f"ERRO ao processar imagem com IA: {exc}")
                        import traceback
                        traceback.print_exc()
                        st.session_state.resultado = {"notas": 0, "notas_preenchidas": 0, "ausentes": 0, "falhas": 1}
                        st.stop()

                else:
                    log_progress(f"Carregando dados de {fonte}...")
                    from leitor_planilhas import carregar_notas

                    if fonte in ("excel", "csv"):
                        fonte_path = st.session_state.get("arquivo_path", "")
                        if not fonte_path:
                            log_progress("ERRO: Nenhum arquivo selecionado.")
                            st.error("Selecione um arquivo primeiro.")
                            st.session_state.executando = False
                            st.stop()
                    elif fonte in ("google_sheets", "google_drive"):
                        fonte_path = st.session_state.get("link_url", "")
                        if not fonte_path:
                            log_progress("ERRO: Nenhum link informado.")
                            st.error("Informe o link do Google Sheets/Drive.")
                            st.session_state.executando = False
                            st.stop()

                    registros = carregar_notas(fonte, fonte_path, logger=log_progress)
                    log_progress(f"{len(registros)} notas carregadas.")

                if not registros:
                    log_progress("ERRO: Nenhum registro carregado.")
                    st.session_state.resultado = {"blocos": 0, "notas": 0, "notas_preenchidas": 0, "ausentes": 0, "falhas": 0}
                    st.stop()

                if dry_run:
                    log_progress("[DRY-RUN] Nenhum dado sera enviado ao SGE.")
                    from collections import Counter
                    contextos = set((r.escola, r.turno, r.turma, r.trimestre) for r in registros)
                    st.session_state.resultado = {
                        "blocos": len(contextos),
                        "notas": len(registros),
                        "notas_preenchidas": 0,
                        "falhas": 0,
                    }
                else:
                    log_progress("Iniciando navegador e login no portal...")
                    from lancar_notas_sge import (
                        ContextoTurma,
                        _group_for_launch,
                        _login_sge,
                        _select_context,
                        _open_assessment_for_context,
                        _select_activity,
                        _fill_grade_for_student,
                        _read_existing_grade_for_student,
                        _grade_value_matches_target,
                        _confirm_save,
                        ACTION_TIMEOUT_MS,
                        HEADLESS,
                    )
                    from playwright.sync_api import sync_playwright
                    from status_store import StatusStore

                    status_store = StatusStore(fonte_path, logger=log_progress)
                    ja_lancadas = 0
                    ja_no_sge = 0
                    ausentes_count = 0

                    from lancar_notas_sge import RegistroNota as SGEReg
                    registros_sge = [
                        SGEReg(
                            escola=r.escola, turno=r.turno, turma=r.turma,
                            trimestre=r.trimestre, aluno=r.aluno,
                            atividade=r.atividade, nota=r.nota,
                            data_realizacao=r.data_realizacao,
                        )
                        for r in registros
                    ]

                    grouped = _group_for_launch(registros_sge)
                    log_progress(f"Blocos para lancamento: {len(grouped)}")

                    notas_ok = 0
                    falhas = 0

                    with sync_playwright() as p:
                        browser = p.chromium.launch(headless=HEADLESS)
                        ctx = browser.new_context()
                        page = ctx.new_page()
                        page.set_default_timeout(ACTION_TIMEOUT_MS)

                        _login_sge(page, cpf=st.session_state.sge_cpf, senha=st.session_state.sge_senha, logger=log_progress)

                        for idx, (key, itens) in enumerate(grouped.items(), start=1):
                            escola, turno, turma, trimestre, atividade = key
                            log_progress(f"[{idx}/{len(grouped)}] {escola} | {turno} | {turma} | {trimestre} | {atividade}")

                            from lancar_notas_sge import _date_diff_days, _dates_match
                            datas_bloco = [r.data_realizacao for r in itens if r.data_realizacao]
                            data_mais_comum = ""
                            if datas_bloco:
                                from collections import Counter
                                data_mais_comum = Counter(datas_bloco).most_common(1)[0][0]
                                diff_dias = _date_diff_days(data_mais_comum)
                                if diff_dias is not None and diff_dias > 0:
                                    log_progress(f"[DATA] Atividade com data futura ({data_mais_comum}). Pulando bloco.")
                                    falhas += len(itens)
                                    continue
                                elif diff_dias is not None and diff_dias < -90:
                                    log_progress(f"[DATA] Atencao: atividade com data antiga ({data_mais_comum}). Prosseguindo...")
                                elif diff_dias is not None:
                                    log_progress(f"[DATA] Data da atividade: {data_mais_comum} ({abs(diff_dias)} dia(s) atras)")
                            else:
                                log_progress("[DATA] Nenhuma data de realizacao definida na planilha para esta atividade.")

                            contexto = ContextoTurma(escola=escola, turno=turno, turma=turma, trimestre=trimestre)
                            _select_context(page, contexto, logger=log_progress)
                            _open_assessment_for_context(page, contexto, logger=log_progress)
                            atividade_encontrada, data_sge, posicao_grid = _select_activity(page, atividade, logger=log_progress)

                            if not atividade_encontrada:
                                log_progress(f"  [AVISO] Atividade '{atividade}' nao encontrada no SGE. Pulando bloco.")
                                falhas += len(itens)
                                continue

                            if data_sge and data_mais_comum and not _dates_match(data_sge, data_mais_comum):
                                log_progress(f"  [DATA] Validacao falhou: SGE {data_sge} ≠ planilha {data_mais_comum}. Pulando bloco.")
                                falhas += len(itens)
                                continue
                            if data_sge and data_mais_comum:
                                log_progress(f"  [DATA] Datas conferem: SGE {data_sge} = planilha {data_mais_comum}")
                            elif not data_sge and data_mais_comum:
                                log_progress(f"  [DATA] Data da atividade nao encontrada no SGE. Prosseguindo sem validacao de data.")

                            from lancar_notas_sge import _detect_coluna_from_page
                            coluna_sge = _detect_coluna_from_page(page, posicao_grid, logger=log_progress, atividade=atividade)

                            novos = 0
                            for reg in itens:
                                if status_store.esta_lancada(reg.escola, reg.turno, reg.turma, reg.trimestre, reg.aluno, reg.atividade):
                                    ja_lancadas += 1
                                    continue

                                existing = _read_existing_grade_for_student(page, reg.aluno, logger=log_progress, coluna_sge=coluna_sge)
                                if existing is not None:
                                    nota_texto = str(reg.nota).replace(".", ",")
                                    if _grade_value_matches_target(existing, nota_texto):
                                        ja_no_sge += 1
                                        status_store.marcar_lancada(reg.escola, reg.turno, reg.turma, reg.trimestre, reg.aluno, reg.atividade, reg.nota)
                                        notas_ok += 1
                                        continue
                                    log_progress(f"  Nota existente '{existing}' difere da esperada '{nota_texto}' para '{reg.aluno}'. Atualizando...")

                                filled_suffix = _fill_grade_for_student(page, reg.aluno, reg.nota, logger=log_progress, coluna_sge=coluna_sge)
                                if filled_suffix:
                                    notas_ok += 1
                                    novos += 1
                                    status_store.marcar_lancada(reg.escola, reg.turno, reg.turma, reg.trimestre, reg.aluno, reg.atividade, reg.nota)
                                else:
                                    log_progress(f"  [AUSENTE] Aluno '{reg.aluno}' nao localizado na grade. Pulando...")
                                    ausentes_count += 1

                            if novos > 0:
                                _confirm_save(page, logger=log_progress, data_realizacao=data_mais_comum)

                        ctx.close()
                        browser.close()

                    log_progress(f"Status local: {ja_lancadas} ja lancadas, {ja_no_sge} ja no SGE, {notas_ok} preenchidas, {ausentes_count} ausentes, {falhas} falhas")

                    st.session_state.resultado = {
                        "blocos": len(grouped),
                        "notas": len(registros_sge),
                        "notas_preenchidas": notas_ok,
                        "ausentes": ausentes_count,
                        "falhas": falhas,
                    }
                    log_progress(f"Concluido! Preenchidas: {notas_ok}, Ausentes: {ausentes_count}, Falhas: {falhas}")

        elif st.session_state.tipo == "chamada":
            from lancar_chamada_sge import executar_chamada as executar_chamada_sge

            foto_path = st.session_state.get("chamada_foto_path", "")
            if not foto_path:
                log_progress("ERRO: Nenhuma foto do diario selecionada.")
                st.error("Envie a foto da chamada do dia na seção 'Filtros' antes de executar.")
                st.session_state.resultado = {"success": False, "mensagem": "Sem foto", "plano": [], "resumo": {}, "nao_encontrados": []}
                st.stop()

            dia_input = st.session_state.get("chamada_dia", "").strip()
            if not dia_input:
                log_progress("ERRO: Informe o dia da chamada (dd/mm/aaaa).")
                st.error("Informe o **dia da chamada** no formato dd/mm/aaaa antes de executar.")
                st.session_state.resultado = {"success": False, "mensagem": "Sem dia", "plano": [], "resumo": {}, "nao_encontrados": []}
                st.stop()

            m_data = re.search(r"(\d{2})[/\-](\d{2})[/\-](\d{4})", dia_input)
            if not m_data:
                log_progress(f"ERRO: Dia '{dia_input}' em formato invalido. Use dd/mm/aaaa.")
                st.error(f"Dia '{dia_input}' em formato invalido. Use dd/mm/aaaa (ex.: 05/08/2026).")
                st.session_state.resultado = {"success": False, "mensagem": "Data invalida", "plano": [], "resumo": {}, "nao_encontrados": []}
                st.stop()
            dia_sge = f"{m_data.group(3)}/{m_data.group(2)}/{m_data.group(1)}"

            log_progress(f"[CHAMADA] Dia: {dia_sge} | Escola: {st.session_state.get('escola', '') or 'todas'}")
            try:
                resultado = executar_chamada_sge(
                    filtro={
                        "escola": st.session_state.get("escola", ""),
                        "turno": st.session_state.get("turno", ""),
                        "turma": st.session_state.get("turma", ""),
                        "disciplina": st.session_state.get("chamada_disciplina", ""),
                        "dia": dia_sge,
                    },
                    foto_path=foto_path,
                    logger=log_progress,
                    dry_run=dry_run,
                )
            except Exception as exc:  # noqa: BLE001
                log_progress(f"[CHAMADA] ERRO: {exc}")
                st.error(f"Falha no lancamento da chamada: {exc}")
                st.session_state.resultado = {"success": False, "mensagem": str(exc), "plano": [], "resumo": {}, "nao_encontrados": []}
                st.stop()

            st.session_state.resultado = resultado
            resumo = resultado.get("resumo", {})
            log_progress(
                f"[CHAMADA] Concluido! {resumo.get('presentes', 0)} presentes, "
                f"{resumo.get('faltas', 0)} falta(s), {resumo.get('ja_lancados', 0)} ja lancado(s)."
            )
            if resultado.get("nao_encontrados"):
                log_progress(f"[CHAMADA] Sem match na grade: {', '.join(resultado['nao_encontrados'])}")
            if dry_run:
                log_progress("[CHAMADA] Dry-run: nada foi enviado ao SGE. Confira o plano antes de desmarcar.")

        elif st.session_state.tipo == "sequencia":
            from lancar_sequencia_didatica_sge import executar_lancamento_sequencia, SequenciaRegistro

            registros = None
            fonte = st.session_state.fonte

            if fonte == "notion":
                log_progress("Carregando dados do Notion...")

            elif fonte in ("excel", "csv"):
                log_progress("Carregando sequencias do arquivo...")
                file_path = st.session_state.get("arquivo_path", "")
                if not file_path:
                    log_progress("ERRO: Nenhum arquivo selecionado para Sequencia Didatica.")
                    st.session_state.executando = False
                    st.stop()
                raw = (
                    ler_sequencias_excel(file_path, logger=log_progress)
                    if fonte == "excel"
                    else ler_sequencias_csv(file_path, logger=log_progress)
                )
                if not raw:
                    log_progress("ERRO: Nenhuma sequencia valida encontrada no arquivo.")
                    st.session_state.executando = False
                    st.stop()
                registros = [SequenciaRegistro(**r) for r in raw]
                log_progress(f"{len(registros)} sequencia(s) carregada(s) do arquivo.")

            elif fonte == "google_drive":
                log_progress("Preparando lancamento via Google Drive...")
                drive_links = st.session_state.get("seq_drive_links", [])
                links_preenchidos = [e for e in drive_links if e.get("link", "").strip()]
                if not links_preenchidos:
                    log_progress("ERRO: Nenhum link preenchido. Adicione links na seção 'Filtros'.")
                    st.session_state.executando = False
                    st.stop()

                periodo_inicio = st.session_state.get("seq_periodo_inicio", "").strip()
                periodo_fim = st.session_state.get("seq_periodo_fim", "").strip()
                titulo_base = st.session_state.get("seq_titulo_documento", "").strip() or "Sequencia Didatica"
                n_aulas = int(st.session_state.get("seq_n_aulas", 4) or 4)

                registros = []
                for entry in links_preenchidos:
                    ano = entry["ano"]
                    link = entry["link"].strip()
                    titulo_doc = f"{titulo_base} - {ano}"
                    registros.append(SequenciaRegistro(
                        page_id="",
                        ano=ano,
                        escola=st.session_state.get("escola", ""),
                        turno=st.session_state.get("turno", ""),
                        turma="",
                        titulo_documento=titulo_doc,
                        arquivo_nome=f"{ano}.pdf",
                        arquivo_url=link,
                        link_arquivo=link,
                        periodo_inicio=periodo_inicio,
                        periodo_fim=periodo_fim,
                        n_aulas=n_aulas,
                        status="",
                    ))
                log_progress(f"{len(registros)} registro(s) preparado(s) via Google Drive.")

            else:
                log_progress(f"AVISO: Fonte '{fonte}' nao suportada para sequencia didatica.")
                st.warning("Use Notion, Excel, CSV ou Google Drive para sequencia didatica.")

            if registros is not None or fonte == "notion":
                log_progress("Executando sequencia didatica no SGE...")
                resumo = executar_lancamento_sequencia(
                    escola=st.session_state.escola,
                    turno=st.session_state.turno,
                    turma=st.session_state.turma,
                    trimestre=st.session_state.trimestre or "2o Trimestre",
                    dry_run=dry_run,
                    registros=registros,
                    logger=log_progress,
                )
                st.session_state.resultado = {
                    "contextos": resumo.contextos_total,
                    "planejamentos": resumo.planejamentos_criados,
                    "anexos": resumo.anexos_enviados,
                    "situacoes": resumo.situacoes_ativadas,
                    "falhas": resumo.falhas,
                }
                log_progress(f"Concluido! Planejamentos: {resumo.planejamentos_criados}, Falhas: {resumo.falhas}")

    except RuntimeError as exc:
        if "Event loop is closed" in str(exc):
            log_progress("Execucao finalizada (limpeza async concluida).")
        else:
            _handle_exec_error(exc, log_progress)
    except Exception as exc:
        _handle_exec_error(exc, log_progress)

    finally:
        st.session_state.executando = False
        try:
            status.update(label="Finalizado", state="complete")
        except RuntimeError:
            pass

# === MENSAGEM DE AUTOFIX ===
autofix_msg = st.session_state.pop("autofix_message", None)
if autofix_msg:
    st.success(f"**Autofix:** {autofix_msg}")
    col_retry1, col_retry2 = st.columns([1, 3])
    with col_retry1:
        if st.button("Tentar novamente", type="primary", key="autofix_retry_btn"):
            st.session_state.autofix_trigger = True
            st.session_state.autofix_attempts = st.session_state.get("autofix_attempts", 0)
            st.rerun()
    with col_retry2:
        if st.button("Ignorar", key="autofix_ignore_btn"):
            st.session_state.autofix_attempts = 0
            st.rerun()

# === AREA DE LOGS ===
col_log_header, col_log_export = st.columns([3, 1])
with col_log_header:
    st.markdown("### Logs da Execucao")
with col_log_export:
    if st.session_state.logs:
        log_text = "\n".join(st.session_state.logs)
        st.download_button(
            "📥 Exportar logs",
            data=log_text,
            file_name=f"logs_bot_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
            mime="text/plain",
            use_container_width=True,
        )

log_container = st.container()

with log_container:
    for msg in st.session_state.logs[-50:]:
        if "ERRO" in msg or "erro" in msg.lower():
            st.markdown(f":red[{msg}]")
        elif "OK" in msg or "sucesso" in msg.lower() or "concluido" in msg.lower():
            st.markdown(f":green[{msg}]")
        elif "AVISO" in msg or "aviso" in msg.lower():
            st.markdown(f":orange[{msg}]")
        else:
            st.text(msg)

# === RESULTADO ===
if st.session_state.resultado:
    st.markdown("### Resultado")
    res = st.session_state.resultado

    cols = st.columns(5)
    with cols[0]:
        st.metric("Blocos/Contextos", res.get("blocos") or res.get("contextos", 0))
    with cols[1]:
        st.metric("Notas", res.get("notas", 0))
    with cols[2]:
        preenchidas = res.get("notas_preenchidas") or res.get("planejamentos", 0)
        st.metric("Sucesso", preenchidas)
    with cols[3]:
        ausentes = res.get("ausentes", 0)
        st.metric("Ausentes", ausentes)
    with cols[4]:
        falhas = res.get("falhas", 0)
        st.metric("Falhas", falhas, delta_color="inverse")

    if falhas > 0:
        st.warning(f"Houve {falhas} falha(s). Verifique os logs acima.")
    elif preenchidas > 0:
        st.success("Tudo concluido com sucesso!")

# === RODAPE ===
st.markdown("---")
st.markdown(
    "<small>Bot do Professor v1.0 - Automacao de lancamento de notas. "
    "Use com responsabilidade. Verifique os dados antes de lancar.</small>",
    unsafe_allow_html=True,
)
