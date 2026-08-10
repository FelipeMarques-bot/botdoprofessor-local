@echo off
title BotDoProfessor - Build e Release
color 0A

echo =============================================
echo  BotDoProfessor - Build Completo
echo =============================================
echo.
echo  Opcoes:
echo  [1] Gerar .exe (PyInstaller)
echo  [2] Gerar .exe + Instalador NSIS
echo  [3] Submeter para whitelist de antivirus
echo  [4] Criar release no GitHub
echo  [5] Tudo (build + installer + release)
echo.
set /p opcao="Escolha (1-5): "

if "%opcao%"=="1" goto :build_exe
if "%opcao%"=="2" goto :build_installer
if "%opcao%"=="3" goto :whitelist
if "%opcao%"=="4" goto :github_release
if "%opcao%"=="5" goto :build_all
echo Opcao invalida!
pause
exit /b 1

:build_exe
echo.
echo [1/3] Instalando PyInstaller...
python -m pip install pyinstaller --quiet

echo [2/3] Gerando .exe (sem UPX - reduz falsos positivos)...
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

echo [3/3] Verificando resultado...
if exist dist\BotDoProfessor.exe (
    echo.
    echo =============================================
    echo  .exe gerado com sucesso!
    echo  Localizacao: %cd%\dist\BotDoProfessor.exe
    for %%I in (dist\BotDoProfessor.exe) do echo  Tamanho: %%~zI bytes
    echo =============================================
) else (
    echo ERRO: Falha ao gerar .exe.
)
pause
exit /b 0

:build_installer
call :build_exe
echo.
echo [NSIS] Verificando NSIS...
set "NSIS_PATH="
if exist "C:\Program Files (x86)\NSIS\makensis.exe" (
    set "NSIS_PATH=C:\Program Files (x86)\NSIS\makensis.exe"
)
if exist "C:\Program Files\NSIS\makensis.exe" (
    set "NSIS_PATH=C:\Program Files\NSIS\makensis.exe"
)
where makensis >nul 2>nul
if %errorlevel% equ 0 (
    set "NSIS_PATH=makensis"
)
if "%NSIS_PATH%"=="" (
    echo NSIS nao encontrado!
    echo Baixe em: https://nsis.sourceforge.io/Download
    echo Instale e adicione ao PATH do sistema.
    pause
    exit /b 1
)
echo [NSIS] Gerando instalador...
"%NSIS_PATH%" installer.nsi
if exist dist\BotDoProfessor-Setup-v1.4.33.exe (
    echo.
    echo =============================================
    echo  Instalador gerado!
    echo  Localizacao: %cd%\dist\BotDoProfessor-Setup-v1.4.33.exe
    echo =============================================
)
pause
exit /b 0

:whitelist
echo.
echo =============================================
echo  Submissao para Whitelist de Anti-Virus
echo =============================================
echo.
echo  1. Acesse os links abaixo e submeta o .exe:
echo.
echo  Microsoft: https://www.microsoft.com/en-us/wdsi/filesubmission
echo  Kaspersky: https://opentip.kaspersky.com/
echo  Norton:    https://submit.symantec.com/false_positive
echo  Avast:     https://www.avast.com/false-positive-file-form.php
echo  Bitdefender: https://www.bitdefender.com/consumer/support/
echo  ESET:      https://support.eset.com/kb141/
echo.
echo  2. Submeta em TODOS de uma vez (paralelo)
echo  3. Aguarde 24-48h para aprovacao
echo  4. Documente os IDs de referencia
echo.
pause
exit /b 0

:github_release
echo.
echo =============================================
echo  Criar Release no GitHub
echo =============================================
echo.
echo  Requisitos:
echo  - Git instalado
echo  - GitHub CLI (gh) instalado: winget install GitHub.cli
echo  - Conta no GitHub configurada
echo.
where gh >nul 2>nul
if %errorlevel% neq 0 (
    echo GitHub CLI nao encontrado!
    echo Instale: winget install GitHub.cli
    pause
    exit /b 1
)
echo  Fazendo login no GitHub...
gh auth login
echo.
echo  Criando tag e release...
set /p versao="Versao (ex: 1.0.0): "
git tag -a v%versao% -m "Release v%versao%"
git push origin v%versao%
gh release create v%versao% ^
    dist\BotDoProfessor.exe ^
    --title "BotDoProfessor v%versao%" ^
    --notes "Versao %versao% do BotDoProfessor" ^
    --latest
echo.
echo =============================================
echo  Release criado!
echo  URL: https://github.com/FelipeMarques-bot/botdoprofessor-local/releases
echo =============================================
pause
exit /b 0

:build_all
call :build_exe
call :build_installer
call :github_release
exit /b 0
