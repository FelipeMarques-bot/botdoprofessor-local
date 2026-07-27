# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('painel.py', '.'), ('lancar_notas_sge.py', '.'), ('lancar_sequencia_didatica_sge.py', '.'), ('leitor_planilhas.py', '.'), ('ai_assist.py', '.'), ('status_store.py', '.'), ('.env.example', '.')],
    hiddenimports=['streamlit', 'playwright', 'playwright.sync_api', 'openpyxl', 'pandas', 'google.genai', 'openai', 'anthropic', 'requests', 'python_dotenv'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='BotDoProfessor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
