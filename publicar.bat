@echo off
title BotDoProfessor - Publicar (Build + Setup + Upload R2) - 1 clique
color 0A
cd /d "%~dp0"

echo =============================================
echo  BotDoProfessor - Publicacao automatica
echo =============================================
echo.
echo  Requisitos:
echo  - Python instalado e no PATH
echo  - NSIS instalado (C:\Program Files (x86)\NSIS)
echo  - .env com STORAGE_* configurado (credenciais do R2)
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ERRO: Python nao encontrado no PATH
    pause
    exit /b 1
)

if not exist .env (
    echo ERRO: .env nao encontrado nesta pasta
    echo Crie a partir de .env.example e preencha as credenciais STORAGE_* do R2.
    pause
    exit /b 1
)

setlocal enabledelayedexpansion

for /f "delims=" %%V in (VERSION.txt) do set "VER_ATUAL=%%V"
echo  Versao atual em VERSION.txt: v%VER_ATUAL%
echo.
set /p NOVA_VER="Nova versao (ex: 1.4.58, ou Enter para manter): "
if not "%NOVA_VER%"=="" echo %NOVA_VER%> VERSION.txt

for /f "delims=" %%V in (VERSION.txt) do set "VER_FINAL=%%V"
echo.
echo  Publicando v%VER_FINAL%...
echo.

echo [1/3] Gerando app one-dir (PyInstaller via spec)...
python -m pip install pyinstaller --quiet
if exist requirements-exe.txt python -m pip install -r requirements-exe.txt --quiet
python -m PyInstaller --noconfirm --clean BotDoProfessor.spec

if not exist dist\BotDoProfessor\BotDoProfessor.exe (
    echo.
    echo ERRO: Falha ao gerar o .exe
    pause
    exit /b 1
)
echo  App one-dir gerado.

echo.
echo [2/3] Gerando instalador NSIS...
set "NSIS_PATH="
if exist "C:\Program Files (x86)\NSIS\makensis.exe" set "NSIS_PATH=C:\Program Files (x86)\NSIS\makensis.exe"
if exist "C:\Program Files\NSIS\makensis.exe" set "NSIS_PATH=C:\Program Files\NSIS\makensis.exe"
where makensis >nul 2>nul
if %errorlevel% equ 0 set "NSIS_PATH=makensis"
if "%NSIS_PATH%"=="" (
    echo ERRO: NSIS nao encontrado!
    pause
    exit /b 1
)
"%NSIS_PATH%" installer.nsi

set "SETUP_PATH=dist\BotDoProfessor-Setup-v%VER_FINAL%.exe"
if not exist "%SETUP_PATH%" (
    echo ERRO: Falha ao gerar instalador.
    pause
    exit /b 1
)
echo  Instalador gerado: %SETUP_PATH%

echo.
echo [3/3] Enviando instalador ao Cloudflare R2...
python upload_binario.py "%SETUP_PATH%"

echo.
echo =============================================
echo  Publicacao concluida! v%VER_FINAL%
echo  - Setup publicado no R2 (object STORAGE_.env do servidor)
echo  - version.json atualizado (v%VER_FINAL%)
echo  - Usuarios recebem a atualizacao na proxima abertura
echo =============================================
pause
exit /b 0
