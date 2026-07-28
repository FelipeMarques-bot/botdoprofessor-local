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
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import streamlit as st

# === CONFIGURACAO DA PAGINA ===
st.set_page_config(
    page_title="Bot do Professor - Lancamento de Notas",
    page_icon="",
    layout="wide",
    initial_sidebar_state="expanded",
)

# === ESTILO CSS ===
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1.1rem;
        color: #666;
        margin-bottom: 2rem;
    }
    .card {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1.5rem;
        margin-bottom: 1rem;
        border: 1px solid #e9ecef;
    }
    .stButton button {
        width: 100%;
        border-radius: 8px;
        padding: 0.5rem 1rem;
        font-weight: 600;
    }
    .stTextInput input, .stTextArea textarea {
        border-radius: 8px;
    }
    .stSelectbox div[data-baseweb="select"] {
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)


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


# === BARRA LATERAL ===
with st.sidebar:
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
            options=["notion", "excel", "csv", "google_sheets", "google_drive"],
            format_func=lambda x: {
                "notion": "Notion (bancos de dados)",
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
        elif fonte in ("google_sheets", "google_drive"):
            nome_origem = "Google Sheets" if fonte == "google_sheets" else "Google Drive"
            st.info(
                f"Cole o link compartilhavel do **{nome_origem}** abaixo.\n\n"
                f"Ex: `https://docs.google.com/spreadsheets/d/...`"
            )
            link = st.text_input(
                f"URL compartilhavel do {nome_origem}:",
                key="link_input",
                placeholder="https://docs.google.com/spreadsheets/d/...",
            )
            st.session_state["link_url"] = link

    with st.expander("Filtros"):
        tipo = st.radio("Tipo de lancamento:", options=["notas", "sequencia"], horizontal=True, key="tipo_radio")
        st.session_state.tipo = tipo

        col_f1, col_f2 = st.columns(2)
        with col_f1:
            escola = st.text_input("Escola (vazio = todas)", key="escola_input")
            st.session_state.escola = escola
            turma = st.text_input("Turma (ex: 6o Ano)", key="turma_input")
            st.session_state.turma = turma
        with col_f2:
            turno = st.selectbox("Turno", options=["", "Matutino", "Vespertino", "Noturno"], key="turno_select")
            st.session_state.turno = turno
            trimestre = st.selectbox("Trimestre", options=["", "1o Trimestre", "2o Trimestre", "3o Trimestre"], key="trimestre_select")
            st.session_state.trimestre = trimestre

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
        else:
            st.session_state.pop("imagem_path", None)

        st.markdown("---")
        st.markdown("**Atalho: Lançar apenas 1 avaliação** (reduz tempo drasticamente)")
        col_a1, col_a2 = st.columns(2)
        with col_a1:
            avaliacao_nome = st.text_input(
                "Nome da avaliação (ex: Prova 1, Trabalho 2)",
                key="avaliacao_input",
                help="Se preenchido, o bot ignora as outras avaliações e lança apenas esta."
            )
            st.session_state.avaliacao_nome = avaliacao_nome
        with col_a2:
            avaliacao_data = st.text_input(
                "Data da avaliação (dd/mm/aaaa)",
                key="avaliacao_data_input",
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

    dry_run = st.checkbox("Modo Dry-run (apenas validar)", value=True, key="dry_run_check")
    salvar = st.button("Salvar Configuracao")

    if salvar:
        path = salvar_config()
        st.success(f"Configuracao salva em {path}")

    limpar = st.button("Limpar Logs")
    if limpar:
        st.session_state.logs = []
        st.session_state.resultado = None


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
if executar_btn:
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

    try:
        # Prepara variaveis de ambiente
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
                fonte_path = st.session_state.get("imagem_path", "")

                if fonte_path:
                    log_progress("Extraindo notas da imagem com IA...")
                    try:
                        from ai_assist import _call_ai
                        with open(fonte_path, "rb") as f:
                            image_bytes = f.read()

                        prompt = (
                            "Extraia as notas/alunos desta imagem de diario de classe ou boletim. "
                            "Responda APENAS com um JSON array onde cada item tem: "
                            "aluno (nome completo), nota (valor numerico com virgula ou ponto). "
                            "Exemplo: [{\"aluno\": \"Joao Silva\", \"nota\": \"8,5\"}]. "
                            "Se nao conseguir extrair, retorne []."
                        )
                        resposta = _call_ai(prompt, image_bytes=image_bytes)
                        log_progress(f"Resposta da IA: {resposta[:200]}...")

                        import json as _json
                        extraidas = _json.loads(resposta)
                        if not isinstance(extraidas, list):
                            extraidas = []

                        if not extraidas:
                            log_progress("AVISO: IA nao conseguiu extrair notas da imagem.")
                            st.session_state.resultado = {"notas": 0, "notas_preenchidas": 0, "ausentes": 0, "falhas": 0}
                            st.stop()

                        log_progress(f"Extraidas {len(extraidas)} notas da imagem.")
                        escola = st.session_state.get("escola", "")
                        turno = st.session_state.get("turno", "")
                        turma = st.session_state.get("turma", "")
                        trimestre = st.session_state.get("trimestre", "")

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
                                trimestre=trimestre, aluno=aluno, nota=nota,
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

                            from lancar_notas_sge import _date_diff_days
                            datas_bloco = [r.data_realizacao for r in itens if r.data_realizacao]
                            if datas_bloco:
                                from collections import Counter
                                data_mais_comum = Counter(datas_bloco).most_common(1)[0][0]
                                diff_dias = _date_diff_days(data_mais_comum)
                                if diff_dias is not None and diff_dias > 0:
                                    log_progress(f"[DATA] Atividade com data futura ({data_mais_comum}). Pulando bloco.")
                                    falhas += len(itens)
                                    continue

                            contexto = ContextoTurma(escola=escola, turno=turno, turma=turma, trimestre=trimestre)
                            _select_context(page, contexto, logger=log_progress)
                            _open_assessment_for_context(page, contexto, logger=log_progress)
                            _, data_sge, posicao_grid = _select_activity(page, atividade, logger=log_progress)

                            if not data_sge and posicao_grid == 0:
                                log_progress(f"  [AVISO] Atividade '{atividade}' nao encontrada no SGE. Pulando bloco.")
                                falhas += len(itens)
                                continue

                            from lancar_notas_sge import _COLUNA_POR_POSICAO
                            coluna_sge = _COLUNA_POR_POSICAO.get(posicao_grid, "")

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
                                _confirm_save(page, logger=log_progress)

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

        elif st.session_state.tipo == "sequencia":
            if st.session_state.fonte != "notion":
                log_progress("AVISO: Sequencia didatica requer fonte Notion.")
                st.warning("Sequencia didatica so funciona com dados do Notion.")
            else:
                log_progress("Executando sequencia didatica...")
                from lancar_sequencia_didatica_sge import executar_lancamento_sequencia

                resumo = executar_lancamento_sequencia(
                    escola=st.session_state.escola,
                    turno=st.session_state.turno,
                    turma=st.session_state.turma,
                    trimestre=st.session_state.trimestre or "2o Trimestre",
                    dry_run=dry_run,
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
            log_progress(f"ERRO: {exc}")
            import traceback
            traceback.print_exc()
    except Exception as exc:
        log_progress(f"ERRO: {exc}")
        import traceback
        traceback.print_exc()

    finally:
        st.session_state.executando = False
        try:
            status.update(label="Finalizado", state="complete")
        except RuntimeError:
            pass

# === AREA DE LOGS ===
st.markdown("### Logs da Execucao")
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
