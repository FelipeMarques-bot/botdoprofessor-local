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
    --windowed ^
    --name "BotDoProfessor" ^
    --add-data "painel.py;." ^
    --hidden-import "streamlit" ^
    --hidden-import "playwright" ^
    painel.py

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
