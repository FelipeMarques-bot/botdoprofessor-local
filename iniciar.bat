@echo off
title BotDoProfessor - Instalando...
color 0B

echo.
echo =============================================
echo   BotDoProfessor - Instalacao Automatica
echo =============================================
echo.
echo   Este programa vai configurar tudo automaticamente.
echo   Na primeira vez leva 2-3 minutos. Depois e instantaneo.
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [ER] Python nao encontrado!
    echo.
    echo   Baixe e instale o Python:
    echo   https://www.python.org/downloads/
    echo.
    echo   IMPORTANTE: Marque a opcao "Add Python to PATH"
    echo   durante a instalacao!
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
        echo [ER] Falha ao criar ambiente virtual
        pause
        exit /b 1
    )
    echo [OK] Ambiente virtual criado

    echo.
    echo [i] Instalando dependencias (pode demorar na primeira vez)...
    "%USERPROFILE%\.bot_local\venv\Scripts\pip.exe" install --quiet streamlit playwright openpyxl pandas requests python-dotenv google-generativeai openai anthropic
    if %errorlevel% neq 0 (
        echo [ER] Falha ao instalar dependencias
        pause
        exit /b 1
    )
    echo [OK] Dependencias instaladas

    echo.
    echo [i] Baixando navegador Chromium (~180MB, primeira vez)...
    "%USERPROFILE%\.bot_local\venv\Scripts\python.exe" -m playwright install chromium
    if %errorlevel% neq 0 (
        echo [AVISO] Falha ao baixar Chromium. Tente novamente depois.
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
echo [!] O programa foi encerrado.
pause
