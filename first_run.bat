@echo off
title BotDoProfessor — Instalacao
echo.
echo ==========================================
echo   BotDoProfessor — Instalacao Automatica
echo ==========================================
echo.

where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ER] Python nao encontrado no PATH.
    echo.
    echo Baixe Python em: https://www.python.org/downloads/
    echo Marque "Add Python to PATH" durante a instalacao.
    echo.
    pause
    exit /b 1
)

echo [OK] Python encontrado
echo.

echo Instalando dependencias...
python -m pip install --quiet playwright openpyxl requests
if %ERRORLEVEL% neq 0 (
    echo [ER] Falha ao instalar dependencias.
    pause
    exit /b 1
)
echo [OK] Dependencias instaladas
echo.

echo Baixando Chromium (pode demorar)...
python -m playwright install chromium
if %ERRORLEVEL% neq 0 (
    echo [ER] Falha ao baixar Chromium.
    pause
    exit /b 1
)
echo.
echo [OK] Instalacao concluida!
echo.
echo Agora execute: BotDoProfessor.exe
echo.
pause
