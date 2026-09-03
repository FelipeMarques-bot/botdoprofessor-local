#!/usr/bin/env python3
"""BotDoProfessor-Local — Painel de controle web."""

import os
import sys
import json
import streamlit as st
import requests
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

API_URL = os.environ.get("API_URL", "http://localhost:5000")

st.set_page_config(
    page_title="BotDoProfessor-Local",
    page_icon="🤖",
    layout="wide",
)

if "token" not in st.session_state:
    st.session_state.token = None
    st.session_state.user = None


def api(method, path, data=None, auth=True):
    headers = {}
    if auth and st.session_state.token:
        headers["Authorization"] = f"Bearer {st.session_state.token}"
    try:
        resp = requests.request(method, f"{API_URL}{path}", json=data, headers=headers, timeout=10)
        status = resp.status_code
        try:
            body = resp.json()
        except Exception:
            body = {"error": "Resposta invalida da API"}
        if status == 401 and auth:
            st.session_state.token = None
            st.session_state.user = None
            st.rerun()
        return status, body
    except requests.ConnectionError:
        return 0, {"error": "API nao esta rodando. Execute: python cli.py serve"}
    except Exception as e:
        return 0, {"error": str(e)}


def login_page():
    st.title("BotDoProfessor-Local")
    st.subheader("Login")

    col1, col2 = st.columns(2)
    with col1:
        username = st.text_input("Usuario", value="admin")
    with col2:
        password = st.text_input("Senha", type="password", value="admin123")

    if st.button("Entrar", type="primary"):
        status, data = api("POST", "/api/auth/login", {"username": username, "password": password}, auth=False)
        if status == 200 and "token" in data:
            st.session_state.token = data["token"]
            st.session_state.user = data["user"]
            st.rerun()
        else:
            st.error(data.get("error", "Falha no login"))


def dashboard_page():
    st.title("Dashboard")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Status", "Online")
    with col2:
        st.metric("Usuario", st.session_state.user.get("username", "?"))
    with col3:
        st.metric("Perfil", st.session_state.user.get("profile", "?"))

    st.divider()

    tab1, tab2, tab3, tab4, tab5 = st.tabs(["Sistema", "Licenca", "Portais", "Backup", "Como Usar"])

    with tab1:
        st.subheader("Saude do Sistema")
        if st.button("Verificar Health"):
            status, data = api("GET", "/api/health")
            if status == 200:
                for key, val in data.items():
                    if isinstance(val, dict):
                        s = val.get("status", "?")
                        icon = "✅" if s == "ok" else "⚠️" if s == "warning" else "❌"
                        st.write(f"{icon} **{key}**: {val.get('message', val)}")
                    else:
                        st.write(f"ℹ️ **{key}**: {val}")
            else:
                st.error(data.get("error", "Erro ao verificar health"))

    with tab2:
        st.subheader("Licenca")
        status, data = api("GET", "/api/license/validate")
        if status == 200:
            if data.get("valid"):
                st.success(f"Licenca valida — plano: {data.get('plan')} — {data.get('days_remaining')} dias restantes")
            else:
                st.warning(f"Licenca invalida: {data.get('error')}")
                st.subheader("Ativar Licenca")
                with st.form("activate"):
                    key = st.text_input("Chave da licenca")
                    plan = st.selectbox("Plano", ["mensal", "1ano", "2anos"])
                    if st.form_submit_button("Ativar"):
                        s, d = api("POST", "/api/license/activate", {"license_key": key, "plan": plan})
                        if s == 200:
                            st.success("Licenca ativada!")
                            st.rerun()
                        else:
                            st.error(d.get("error", "Erro"))

    with tab3:
        st.subheader("Portais Disponiveis")
        status, data = api("GET", "/api/portals")
        if status == 200:
            for p in data.get("portals", []):
                st.write(f"🌐 {p}")

        st.divider()
        st.subheader("Descobrir Novo Portal")
        with st.form("discover"):
            url = st.text_input("URL do portal")
            if st.form_submit_button("Descobrir via IA"):
                if url:
                    with st.spinner("Descobrindo estrutura..."):
                        s, d = api("POST", "/api/portals/discover", {"url": url})
                    if s == 200:
                        st.json(d.get("config", {}))
                    else:
                        st.error(d.get("error", "Falha na descoberta"))
                else:
                    st.warning("Informe a URL")

    with tab4:
        st.subheader("Backups")
        if st.button("Criar Backup"):
            s, d = api("POST", "/api/backup", {"label": "manual"})
            if s == 200:
                st.success(f"Backup criado: {d.get('path')}")
            else:
                st.error(d.get("error", "Erro ao criar backup"))

        status, data = api("GET", "/api/backup")
        if status == 200:
            backups = data.get("backups", [])
            if backups:
                for b in backups:
                    st.write(f"📦 {b['name']} — {b.get('created', '?')}")
            else:
                st.info("Nenhum backup ainda")

    with tab5:
        st.subheader("Guia de Uso — BotDoProfessor")
        st.caption("Guia completo para o usuario final. Leia com calma!")

        st.markdown("---")
        st.markdown("### O que e o BotDoProfessor?")
        st.markdown("""
        E um programa que **automatiza o lancamento de notas e planos de aula** no sistema SGE da sua escola.

        Ele funciona assim:
        1. Voce prepara uma planilha com os nomes dos alunos e as notas
        2. O programa abre o navegador automaticamente
        3. Ele entra no SGE com seus dados
        4. Lanca as notas em cada aluno automaticamente
        5. Voce so precisa acompanhar!

        **O programa roda no seu computador** — nao precisa instalar nada no SGE.
        """)

        st.markdown("---")
        st.markdown("### Como instalar o programa")

        st.markdown("#### Passo 1: Baixar o programa")
        st.markdown("""
        - Acesse: **https://github.com/FelipeMarques-bot/botdoprofessor-local/releases/latest**
        - Clique em **"Baixar"** no arquivo **BotDoProfessor.exe**
        - O arquivo (cerca de 140MB) sera salvo na pasta **Downloads** do seu computador
        """)

        st.markdown("#### Passo 2: Encontrar o arquivo")
        st.markdown("""
        - Abra a pasta **Downloads** (ou a pasta onde o navegador salvou)
        - Procure por um arquivo chamado **BotDoProfessor.exe** com um icone de robo
        """)

        st.markdown("#### Passo 3: Executar o programa")
        st.markdown("""
        - **Duplo-clique** (clique duas vezes rapido) no arquivo BotDoProfessor.exe
        """)

        with st.expander("⚠️ Aviso de seguranca do Windows (clique para ver)", expanded=False):
            st.markdown("""
            O Windows pode mostrar uma tela dizendo **"O Windows protegeu seu computador"**.

            Isso e **normal** para programas baixados da internet. Para continuar:

            1. Clique em **"Mais informacoes"** (embaixo)
            2. Clique em **"Executar mesmo assim"**

            O programa e seguro — nao contem virus.
            """)

        st.markdown("#### Passo 4: Primeira configuracao")
        st.markdown("""
        Na primeira vez, o programa instala automaticamente o **navegador Chromium** (cerca de 180MB).

        - Isso demora **aproximadamente 2 minutos**
        - So acontece **uma unica vez**
        - **Nao feche a janela** enquanto estiver baixando
        - Aguarde ate ver a mensagem **"[OK] Navegador instalado com sucesso!"**
        """)

        st.markdown("#### Passo 5: Colar a chave de licenca")
        st.markdown("""
        O programa vai pedir sua chave de licenca.

        1. **Volte para o email** que voce recebeu quando assinou
        2. **Selecione a chave** (clique e arraste o mouse sobre ela)
        3. **Copie** — pressione `Ctrl+C` ou clique com o botao direito e escolha "Copiar"
        4. **Cole no programa** — pressione `Ctrl+V` ou clique com o botao direito e escolha "Colar"

        A chave e salva automaticamente — **nas proximas vezes nao precisa colar de novo**.
        """)

        st.info("Dica: Se o programa nao aceitar a chave, verifique se nao copiou espacos extras antes ou depois.")

        st.markdown("#### Passo 6: Informar o CPF")
        st.markdown("""
        Digite o CPF que voce usa para acessar o SGE.

        - Digite **so numeros** — sem pontos, sem traco, sem espacos
        - Exemplo: `12345678901` (11 numeros)
        - O CPF tambem e salvo automaticamente
        """)

        st.markdown("#### Passo 7: Configurar escola, turma e trimestre")
        st.markdown("""
        O programa vai perguntar:

        | Campo | O que digitar | Exemplo |
        |-------|---------------|---------|
        | Escola | Nome como aparece no SGE | Escola Municipal ABC |
        | Turno | Manha, Tarde ou Noite | Manha |
        | Turma | Serie e turma | 5o Ano A |
        | Trimestre | Qual trimestre | 1o Trimestre |

        Se nao souber, pressione **Enter** para usar o valor padrao.
        Essas configuracoes sao salvas — na proxima vez nao precisa digitar tudo de novo.
        """)

        st.markdown("#### Passo 8: Escolher o tipo de lancamento")
        st.markdown("""
        - Digite **`1`** para **Lancar Notas**
        - Digite **`2`** para **Lancar Plano de Aula**
        """)

        st.markdown("---")
        st.markdown("### Como preparar suas notas")

        st.markdown("#### Opcao 1: Planilha Excel (.xlsx)")
        st.markdown("""
        1. Abra o **Excel** (ou o WPS Office, LibreOffice, Google Sheets)
        2. Crie uma planilha com **duas colunas**:

        | Aluno | Nota |
        |-------|------|
        | Maria Silva | 8.5 |
        | Joao Santos | 7.0 |
        | Ana Oliveira | 9.2 |
        | Pedro Costa | 6.0 |

        3. Salve como **`.xlsx`** ou **`.csv`**
        4. Coloque o arquivo na pasta **Documents** ou na **Area de Trabalho** para encontrar facilmente
        """)

        st.markdown("#### Opcao 2: Google Sheets (online)")
        st.markdown("""
        1. Acesse **sheets.google.com**
        2. Crie uma nova planilha
        3. Na primeira linha, digite: `Aluno` na coluna A e `Nota` na coluna B
        4. Preencha com os nomes e notas dos alunos
        5. Clique em **"Compartilhar"** (canto superior direito)
        6. Em "Quem tem acesso", clique em **"Qualquer pessoa com o link"**
        7. Clique em **"Copiar link"**
        8. Cole o link quando o programa pedir o caminho do arquivo
        """)

        st.markdown("#### Opcao 3: Imagem / Foto")
        st.markdown("""
        Se voce tiver uma **foto ou print das notas** (por exemplo, uma foto de um caderno ou tela), o programa pode ler a imagem automaticamente e extrair as notas.

        Basta informar o caminho da imagem quando o programa pedir.

        *Nota: esta funcionalidade requer configuracao de IA (Gemini, GPT-4o ou Ollama).*
        """)

        st.markdown("---")
        st.markdown("### Perguntas Frequentes")

        with st.expander("O programa e seguro?", expanded=False):
            st.markdown("""
            Sim. O BotDoProfessor roda apenas no seu computador, nao envia seus dados para terceiros, e o codigo e aberto (pode ser verificado).
            """)

        with st.expander("Preciso de internet?", expanded=False):
            st.markdown("""
            Sim. O programa precisa de internet para conectar no SGE e lancar as notas.
            """)

        with st.expander("Funciona em qualquer escola?", expanded=False):
            st.markdown("""
            Funciona em escolas que usam o sistema **SGE**. Se a sua escola usa outro sistema, entre em contato conosco.
            """)

        with st.expander("Posso usar em mais de um computador?", expanded=False):
            st.markdown("""
            Sim, mas a chave de licenca esta vinculada a um numero limitado de maquinas. Se precisar trocar de computador, entre em contato.
            """)

        with st.expander("O programa lembra minhas configuracoes?", expanded=False):
            st.markdown("""
            Sim! Na segunda vez que voce usar, basta digitar `1` ou `2` e ele ja sabe a escola, turma, trimestre e CPF.
            """)

        with st.expander("Deu erro! O que faco?", expanded=False):
            st.markdown("""
            Verifique se:
            - A chave foi colada corretamente (sem espacos extras)
            - O CPF esta correto (11 numeros, sem pontos)
            - A planilha tem as colunas "Aluno" e "Nota"
            - Os nomes dos alunos estao iguais aos do SGE

            Se nao resolver, envie um email para **labintelligenceappoiments@gmail.com**
            """)

        with st.expander("Como alterar minha senha?", expanded=False):
            st.markdown("""
            No painel administrativo, va em **Usuarios** e solicite a alteracao de senha junto ao administrador.
            """)

        st.markdown("---")
        st.markdown("### Precisa de ajuda?")
        st.markdown("""
        - **Email:** labintelligenceappoiments@gmail.com
        - **Responda o email** que voce recebeu com a chave de licenca
        - **Guarde este email** — ele contem sua chave e todas as instrucoes
        """)

    st.divider()
    st.subheader("Usuarios")
    status, data = api("GET", "/api/admin/users")
    if status == 200:
        for u in data:
            icon = "✅" if u.get("active") else "❌"
            st.write(f"{icon} {u['username']} ({u['profile']}) — {u.get('email', '')}")


if st.session_state.token:
    dashboard_page()
    if st.sidebar.button("Sair"):
        st.session_state.token = None
        st.session_state.user = None
        st.rerun()
    st.sidebar.caption(f"API: {API_URL}")
else:
    login_page()
