@echo off
title BotDoProfessor
color 0B
chcp 65001 >nul 2>nul

echo.
echo =============================================
echo   BotDoProfessor - Instalacao Automatica
echo =============================================
echo.

REM === Verificar/Instalar Python automaticamente ===
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [i] Python nao encontrado. Baixando e instalando...
    echo.

    set "PYTHON_URL=https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    set "PYTHON_INSTALLER=%TEMP%\python-installer.exe"

    echo [i] Baixando Python 3.11.9 (~25MB)...
    powershell -Command "Invoke-WebRequest -Uri '%PYTHON_INSTALLER_URL%' -OutFile '%PYTHON_INSTALLER%'" 2>nul
    if not exist "%PYTHON_INSTALLER%" (
        powershell -Command "Invoke-WebRequest -Uri '%PYTHON_URL%' -OutFile '%PYTHON_INSTALLer%'" 2>nul
    )

    if not exist "%PYTHON_INSTALLER%" (
        echo.
        echo [ERRO] Nao foi possivel baixar o Python.
        echo        Baixe manualmente: https://www.python.org/downloads/
        echo        MARQUE: [x] Add python.exe to PATH
        echo.
        pause
        exit /b 1
    )

    echo [i] Instalando Python (silencioso)...
    "%PYTHON_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0
    if %errorlevel% neq 0 (
        echo.
        echo [ERRO] Falha na instalacao do Python.
        echo        Baixe manualmente: https://www.python.org/downloads/
        echo        MARQUE: [x] Add python.exe to PATH
        echo.
        pause
        exit /b 1
    )

    del "%PYTHON_INSTALLER%" >nul 2>nul

    REM Atualizar PATH para esta sessao
    set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Python\Python311;%LOCALAPPDATA%\Programs\Python\Python311\Scripts"

    echo [OK] Python instalado com sucesso!
    echo.
)

REM === Verificar Python novamente ===
where python >nul 2>nul
if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Python ainda nao esta disponivel.
    echo        Feche e abra esta janela novamente apos a instalacao.
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo [OK] %PYVER% encontrado

REM === Criar ambiente virtual ===
if not exist "%USERPROFILE%\.bot_local\venv" (
    echo.
    echo [i] Criando ambiente virtual...
    python -m venv "%USERPROFILE%\.bot_local\venv"
    if %errorlevel% neq 0 (
        echo.
        echo [ERRO] Falha ao criar ambiente virtual.
        echo.
        pause
        exit /b 1
    )
    echo [OK] Ambiente virtual criado

    echo.
    echo [i] Instalando dependencias (2-3 minutos na primeira vez)...
    "%USERPROFILE%\.bot_local\venv\Scripts\pip.exe" install --quiet streamlit playwright openpyxl pandas requests python-dotenv google-generativeai openai anthropic
    if %errorlevel% neq 0 (
        echo.
        echo [ERRO] Falha ao instalar dependencias. Verifique a internet.
        echo.
        pause
        exit /b 1
    )
    echo [OK] Dependencias instaladas

    echo.
    echo [i] Baixando navegador Chromium (~180MB, primeira vez)...
    "%USERPROFILE%\.bot_local\venv\Scripts\python.exe" -m playwright install chromium
    if %errorlevel% neq 0 (
        echo [AVISO] Falha ao baixar Chromium. Tente depois.
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
