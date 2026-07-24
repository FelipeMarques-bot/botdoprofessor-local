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
python -m PyInstaller ^
    --onefile ^
    --name "BotDoProfessor" ^
    --add-data "painel.py;." ^
    --add-data "lancar_notas_sge.py;." ^
    --add-data "lancar_sequencia_didatica_sge.py;." ^
    --add-data "leitor_planilhas.py;." ^
    --add-data "ai_assist.py;." ^
    --add-data "status_store.py;." ^
    --hidden-import "streamlit" ^
    --hidden-import "playwright" ^
    --hidden-import "playwright.sync_api" ^
    --hidden-import "openpyxl" ^
    --hidden-import "pandas" ^
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
