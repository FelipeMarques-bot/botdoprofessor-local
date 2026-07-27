@echo off
title BotDoProfessor
color 0B
chcp 65001 >nul 2>nul

echo.
echo =============================================
echo   BotDoProfessor - Instalacao Automatica
echo =============================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo =============================================
    echo   [ERRO] Python nao encontrado!
    echo =============================================
    echo.
    echo   Voce precisa instalar o Python primeiro.
    echo.
    echo   Passo 1: Acesse https://www.python.org/downloads/
    echo   Passo 2: Clique em "Download Python 3.x.x"
    echo   Passo 3: NA INSTALACAO, marque a opcao:
    echo            [x] Add python.exe to PATH
    echo   Passo 4: Clique em "Install Now"
    echo   Passo 5: Depois de instalar, volte aqui e
    echo             clique duas vezes em "iniciar.bat" novamente.
    echo.
    echo =============================================
    echo.
    pause
    exit /b 1
)

echo [OK] Python encontrado

if not exist "%USERPROFILE%\.bot_local\venv" (
    echo.
    echo [i] Criando ambiente virtual...
    python -m venv "%USERPROFILE%\.bot_local\venv"
    if %errorlevel% neq 0 (
        echo.
        echo [ERRO] Falha ao criar ambiente virtual.
        echo        Verifique se o Python esta instalado corretamente.
        echo.
        pause
        exit /b 1
    )
    echo [OK] Ambiente virtual criado

    echo.
    echo [i] Instalando dependencias (pode demorar 2-3 minutos)...
    "%USERPROFILE%\.bot_local\venv\Scripts\pip.exe" install --quiet streamlit playwright openpyxl pandas requests python-dotenv google-generativeai openai anthropic
    if %errorlevel% neq 0 (
        echo.
        echo [ERRO] Falha ao instalar dependencias.
        echo        Verifique sua conexao com a internet.
        echo.
        pause
        exit /b 1
    )
    echo [OK] Dependencias instaladas

    echo.
    echo [i] Baixando navegador Chromium (~180MB, primeira vez)...
    "%USERPROFILE%\.bot_local\venv\Scripts\python.exe" -m playwright install chromium
    if %errorlevel% neq 0 (
        echo.
        echo [AVISO] Falha ao baixar Chromium.
        echo         Tente novamente depois.
        echo.
    ) else (
        echo [OK] Navegador instalado!
    )
) else (
    echo [OK] Ambiente ja configurado
)

echo.
echo =============================================
echo   Iniciando o painel...
echo   O navegador vai abrir automaticamente.
echo   Para fechar, feche esta janela.
echo =============================================
echo.

start "" http://localhost:8501
"%USERPROFILE%\.bot_local\venv\Scripts\python.exe" -m streamlit run "%~dp0painel.py" --server.headless true --server.port 8501 --browser.gatherUsageStats false

echo.
echo =============================================
echo   Programa encerrado.
echo =============================================
pause
