; BotDoProfessor - Instalador NSIS
; Anti-virus friendly: NSIS e reconhecido por todos os grandes AVs
; Gera: BotDoProfessor-Setup-vX.X.exe

!include "MUI2.nsh"
!include "FileFunc.nsh"

; === CONFIGURACOES ===
!define APP_NAME "BotDoProfessor"
!define APP_VERSION "1.4.40"
!define APP_PUBLISHER "BotDoProfessor"
!define APP_URL "https://github.com/FelipeMarques-bot/botdoprofessor-local"
!define INSTALL_DIR "$LOCALAPPDATA\BotDoProfessor"

Name "${APP_NAME} v${APP_VERSION}"
OutFile "dist\BotDoProfessor-Setup-v${APP_VERSION}.exe"
InstallDir "${INSTALL_DIR}"
InstallDirRegKey HKCU "Software\${APP_NAME}" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma

; === INTERFACE ===
;!define MUI_ICON "icon.ico"
;!define MUI_UNICON "icon.ico"
!define MUI_ABORTWARNING
!define MUI_WELCOMEPAGE_TITLE "BotDoProfessor - Instalacao"
!define MUI_WELCOMEPAGE_TEXT "Este assistente vai instalar o BotDoProfessor no seu computador.$\n$\nO programa automatiza o lancamento de notas no portal do professor.$\n$\nClique Avancar para continuar."

; === PAGINAS ===
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "LICENSE.txt"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "PortugueseBR"

; === SECAO DE INSTALACAO ===
Section "Instalar"
    SetOutPath "$INSTDIR"

    ; Arquivos principais
    File "dist\BotDoProfessor.exe"
    File "painel.py"
    File "lancar_notas_sge.py"
    File "lancar_professor_online.py"
    File "lancar_chamada_sge.py"
    File "lancar_sequencia_didatica_sge.py"
    File "leitor_planilhas.py"
    File "ai_assist.py"
    File "status_store.py"
    File "autofix.py"
    File "aprender_novo_portal.py"
    File "interpretar_pedido.py"
    File ".env.example"
    File "requirements.txt"

    ; Pasta bot/
    SetOutPath "$INSTDIR\bot"
    File /r "bot\*.py"

    ; Pasta config/
    SetOutPath "$INSTDIR\config"
    File /r "config\*.py"

    ; Pasta landing/
    SetOutPath "$INSTDIR\landing"
    File /r "landing\*.*"

    ; Criar desinstalador
    WriteUninstaller "$INSTDIR\uninstall.exe"

    ; Atalho no Menu Iniciar
    CreateDirectory "$SMPROGRAMS\${APP_NAME}"
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\${APP_NAME}.lnk" "$INSTDIR\BotDoProfessor.exe" "" "$INSTDIR\BotDoProfessor.exe" 0
    CreateShortCut "$SMPROGRAMS\${APP_NAME}\Desinstalar.lnk" "$INSTDIR\uninstall.exe"

    ; Atalho na Area de Trabalho
    CreateShortCut "$DESKTOP\${APP_NAME}.lnk" "$INSTDIR\BotDoProfessor.exe" "" "$INSTDIR\BotDoProfessor.exe" 0

    ; Registry para desinstalador
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayName" "${APP_NAME}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "UninstallString" "$INSTDIR\uninstall.exe"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "InstallLocation" "$INSTDIR"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "DisplayVersion" "${APP_VERSION}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "Publisher" "${APP_PUBLISHER}"
    WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "URLInfoAbout" "${APP_URL}"
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoModify" 1
    WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}" "NoRepair" 1

    ; Salvar diretorio de instalacao
    WriteRegStr HKCU "Software\${APP_NAME}" "InstallDir" "$INSTDIR"
SectionEnd

; === SECAO DE DESINSTALACAO ===
Section "Uninstall"
    ; Remover arquivos
    RMDir /r "$INSTDIR"

    ; Remover atalhos
    RMDir /r "$SMPROGRAMS\${APP_NAME}"
    Delete "$DESKTOP\${APP_NAME}.lnk"

    ; Remover registry
    DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APP_NAME}"
    DeleteRegKey HKCU "Software\${APP_NAME}"
SectionEnd
