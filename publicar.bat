@echo off
title BotDoProfessor - Publicar (Build + Upload R2) - 1 clique
color 0A
cd /d "%~dp0"

echo =============================================
echo  BotDoProfessor - Publicacao automatica
echo =============================================
echo.
echo  Requisitos:
echo  - Python instalado e no PATH
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
set /p NOVA_VER="Nova versao (ex: 1.4.41, ou Enter para manter): "
if not "%NOVA_VER%"=="" echo %NOVA_VER%> VERSION.txt

for /f "delims=" %%V in (VERSION.txt) do set "VER_FINAL=%%V"
echo.
echo  Publicando v%VER_FINAL%...
echo.

echo [1/2] Gerando .exe (PyInstaller)...
python -m pip install pyinstaller --quiet
python -m PyInstaller ^
    --onefile ^
    --name "BotDoProfessor" ^
    --noconfirm ^
    --clean ^
    --add-data "painel.py;." ^
    --add-data "autofix.py;." ^
    --add-data "lancar_notas_sge.py;." ^
    --add-data "lancar_professor_online.py;." ^
    --add-data "aprender_novo_portal.py;." ^
    --add-data "lancar_sequencia_didatica_sge.py;." ^
    --add-data "leitor_planilhas.py;." ^
    --add-data "ai_assist.py;." ^
    --add-data "status_store.py;." ^
    --add-data "lancar_chamada_sge.py;." ^
    --add-data "interpretar_pedido.py;." ^
    --add-data "bot;bot" ^
    --add-data "docs;docs" ^
    --add-data ".env.example;." ^
    --add-data "VERSION.txt;." ^
    --hidden-import "streamlit" ^
    --hidden-import "playwright" ^
    --hidden-import "playwright.sync_api" ^
    --hidden-import "openpyxl" ^
    --hidden-import "pandas" ^
    --hidden-import "google.genai" ^
    --hidden-import "openai" ^
    --hidden-import "anthropic" ^
    --hidden-import "requests" ^
    --hidden-import "dotenv" ^
    launcher.py

if not exist dist\BotDoProfessor.exe (
    echo.
    echo ERRO: Falha ao gerar o .exe
    pause
    exit /b 1
)
for %%I in (dist\BotDoProfessor.exe) do echo  .exe gerado: %%~zI bytes

echo.
echo [2/2] Enviando ao Cloudflare R2...
python upload_binario.py

echo.
echo =============================================
echo  Publicacao concluida! v%VER_FINAL%
echo  - .exe publicado no R2
echo  - version.json atualizado (v%VER_FINAL%)
echo  - Usuarios receberao na proxima abertura do exe
echo =============================================
echo.
echo  Dica: suba o arquivo dist\BotDoProfessor.exe como
echo  Release no GitHub tambem (opcional), pelo passo 4
echo  do build_release.bat.
pause
exit /b 0