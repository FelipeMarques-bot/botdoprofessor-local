@echo off
chcp 65001 >nul 2>nul
cd /d "%~dp0"
title Bot do Professor
color 0A

echo.
echo ============================================
echo       Bot do Professor - Notas SGE
echo ============================================
echo.

REM --- Encontrar Python ---
set "PY_CMD="
py --version >nul 2>nul
if %errorlevel% equ 0 (set "PY_CMD=py" & goto :ok_python)
python --version >nul 2>nul
if %errorlevel% equ 0 (set "PY_CMD=python" & goto :ok_python)
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe" & goto :ok_python)
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" (set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python311\python.exe" & goto :ok_python)

echo  Python nao encontrado. Instalando...
where winget >nul 2>nul
if %errorlevel% equ 0 (
    winget install Python.Python.3.12 --accept-source-agreements --accept-package-agreements
    echo.
    echo  Feche e abra novamente este arquivo.
    pause
    exit /b 0
)
echo  Instale Python: https://python.org
pause
exit /b 1

:ok_python
REM --- Instalar dependencias ---
echo  [1/3] Instalando dependencias...
%PY_CMD% -m pip install -r requirements.txt --quiet --disable-pip-version-check
if %errorlevel% neq 0 (
    echo  ERRO ao instalar dependencias.
    pause
    exit /b 1
)

REM --- Instalar Chromium ---
echo  [2/3] Verificando navegador...
%PY_CMD% -c "import playwright" >nul 2>nul
if %errorlevel% neq 0 (
    %PY_CMD% -m playwright install chromium --quiet
)

REM --- Iniciar painel ---
echo  [3/3] Iniciando painel web...
echo.
echo ============================================
echo  Preencha os dados na pagina que abrir.
echo  Feche esta janela para encerrar.
echo ============================================
echo.

set STREAMLIT_EMAIL=
%PY_CMD% -m streamlit run painel.py

pause
