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
        return resp.status_code, resp.json()
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

    tab1, tab2, tab3, tab4 = st.tabs(["Sistema", "Licenca", "Portais", "Backup"])

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
                    plan = st.selectbox("Plano", ["1ano", "2anos", "3anos"])
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
