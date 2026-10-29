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
echo Gerando app one-dir (via spec)...
if exist requirements-exe.txt (
    echo Instalando dependencias para build...
    python -m pip install -r requirements-exe.txt --quiet
)

python -m PyInstaller --noconfirm --clean BotDoProfessor.spec

echo.
if exist dist\BotDoProfessor\BotDoProfessor.exe (
    echo =============================================
    echo  Executavel gerado com sucesso!
    echo  Localizacao: %cd%\dist\BotDoProfessor\BotDoProfessor.exe
    echo =============================================
) else (
    echo ERRO: Falha ao gerar executavel.
)

echo.
pause
