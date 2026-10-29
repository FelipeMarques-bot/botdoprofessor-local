# -*- mode: python ; coding: utf-8 -*-
# Build one-dir: dist\BotDoProfessor\. Abertura instantanea, sem extracao
# por execucao. O instalador NSIS (installer.nsi) empacota a pasta inteira.

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=[('painel.py', '.'), ('autofix.py', '.'), ('lancar_notas_sge.py', '.'), ('lancar_professor_online.py', '.'), ('aprender_novo_portal.py', '.'), ('lancar_sequencia_didatica_sge.py', '.'), ('leitor_planilhas.py', '.'), ('ai_assist.py', '.'), ('status_store.py', '.'), ('lancar_chamada_sge.py', '.'), ('interpretar_pedido.py', '.'), ('bot', 'bot'), ('docs', 'docs'), ('.env.example', '.'), ('VERSION.txt', '.'), ('requirements-exe.txt', '.'), ('.streamlit/config.toml', '.streamlit')],
    hiddenimports=['streamlit', 'playwright', 'playwright.sync_api', 'openpyxl', 'pandas', 'httpx', 'notion_client', 'google.genai', 'openai', 'anthropic', 'gdown', 'cryptography', 'requests', 'dotenv'],
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
    [],
    exclude_binaries=True,
    name='BotDoProfessor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='BotDoProfessor',
)
