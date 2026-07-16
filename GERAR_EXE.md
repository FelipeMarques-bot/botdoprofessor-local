# Gerar Executavel (.exe) para Windows

Para usuarios sem conhecimento tecnico, gere um unico arquivo .exe:

## Metodo 1: Usando o script automatico

1. Execute `gerar_exe.bat` (clique duas vezes)
2. Aguardar a compilacao (1-2 minutos)
3. O .exe estara em `dist/BotSGE.exe`

## Metodo 2: Manual

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --name "BotSGE" painel.py
```

O arquivo `dist/BotSGE.exe` pode ser executado em qualquer computador Windows
sem precisar instalar Python ou dependencias.

## Observacoes

- O .exe gerado funciona apenas no Windows
- O Playwright (navegador Chromium) sera incluido no .exe (~200MB)
- Anti-virus pode alertar falsamente (e normal para automacoes de navegador)
- O .exe pode ser compartilhado com outros usuarios
