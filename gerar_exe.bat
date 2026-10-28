@echo off
title Gerando executavel Bot do Professor...
color 0A

echo =============================================
echo  Gerando Executavel do Bot do Professor
echo =============================================
echo.
echo Este processo leva alguns minutos.
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo ERRO: Python nao encontrado!
    pause
    exit /b 1
)

echo Instalando PyInstaller...
python -m pip install pyinstaller --quiet

echo.
echo Gerando .exe...
if exist requirements-exe.txt (
    echo Instalando dependencias para build...
    python -m pip install -r requirements-exe.txt --quiet
)

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
    --add-data "requirements-exe.txt;." ^
    --hidden-import "streamlit" ^
    --hidden-import "playwright" ^
    --hidden-import "playwright.sync_api" ^
    --hidden-import "openpyxl" ^
    --hidden-import "pandas" ^
    --hidden-import "httpx" ^
    --hidden-import "notion_client" ^
    --hidden-import "google.genai" ^
    --hidden-import "openai" ^
    --hidden-import "anthropic" ^
    --hidden-import "gdown" ^
    --hidden-import "cryptography" ^
    --hidden-import "requests" ^
    --hidden-import "dotenv" ^
    launcher.py

echo.
if exist dist\BotDoProfessor.exe (
    echo =============================================
    echo  Executavel gerado com sucesso!
    echo  Localizacao: %cd%\dist\BotDoProfessor.exe
    echo  Tamanho: 
    for %%I in (dist\BotDoProfessor.exe) do echo  %%~zI bytes
    echo =============================================
) else (
    echo ERRO: Falha ao gerar executavel.
)

echo.
pause
