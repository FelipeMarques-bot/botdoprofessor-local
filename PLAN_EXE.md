# Plano: Executável .exe para distribuição

## Assinatura

Pagina de assinatura: [https://botdoprofessor.onrender.com](https://botdoprofessor.onrender.com)
A chave de licenca e enviada por email apos a compra.

## Arquitetura atual

```
[Render Server]                    [Máquina do usuário]
Landing page                       BotDoProfessor.exe
Payment API                        (Playwright + SGE)
License delivery ← email
```

O .exe é o CLIENTE local que roda o Playwright e automatiza o SGE.
O servidor Render já está funcionando (landing + pagamento + licença).

## O que o .exe precisa fazer

1. Perguntar: chave de licença, CPF, senha do SGE
2. Validar a licença (checar com o servidor Render)
3. Iniciar browser Playwright
4. Fazer login no SGE
5. Executar lanças de notas / planos de aula
6. Mostrar progresso e resultado

## Desafios técnicos

### PyInstaller + Playwright
- Playwright precisa de binários do Chromium (~180MB)
- PyInstaller NÃO inclui binários do Playwright automaticamente
- Solução: incluir script de instalação automática no primeiro uso

### Estrutura proposta

```
BotDoProfessor/
├── BotDoProfessor.exe          # Executável principal (~15MB)
├── first_run.bat               # Instala Playwright (executa uma vez)
├── playwright_browsers/        # Criado pelo first_run.bat
│   └── chromium-xxx/
└── config/
    └── settings.json           # Configurações do usuário
```

## Interface do .exe

### Opção A: CLI interativo (mais simples)
```
=== BotDoProfessor ===
Chave de licença: XXXX-XXXX-XXXX
CPF: 123.456.789-00
Senha do SGE: ****
Escola: Escola Municipal
Turma: 6 serie A
Trimestre: 1o Trimestre
Tipo: [1] Notas  [2] Plano de Aula
> 1
Arquivo de notas (CSV/Excel): notas.csv
Iniciando...
[OK] 28 alunos lancados, 0 erros
```

### Opção B: GUI com tkinter (mais amigável)
- Campos: licença, CPF, senha, escola, turma, trimestre
- Botões: "Lançar Notas", "Plano de Aula"
- Area de progresso
- Log de resultados

## Plano de implementação

### Fase 1: Criar entry point para o .exe
1. Criar `run_bot.py` — interface CLI/GUI que:
   - Pede credenciais
   - Valida licença com servidor
   - Executa o SGEAdapter
   - Mostra resultado
2. Configurar PyInstaller spec

### Fase 2: Script de instalação do Playwright
1. Criar `install_baixar.py` que roda `playwright install chromium`
2. `first_run.bat` que executa o install na primeira vez
3. Detectar se browsers já estão instalados

### Fase 3: Build do .exe
1. `pyinstaller --onefile --name BotDoProfessor run_bot.py`
2. Testar em máquina limpa (sem Python)
3. Resolver dependências ocultas

### Fase 4: Distribuição
1. Host do .exe + install_bat em algum lugar acessível
   - Opções: GitHub Releases, Google Drive, Render static files
2. Atualizar email de licença com link para download
3. Instruções de uso no email

## Checklist de arquivos a criar/modificar

- [ ] `run_bot.py` — Entry point para o .exe (CLI interativo)
- [ ] `BotDoProfessor.spec` — Configuração PyInstaller
- [ ] `install_baixar.py` — Instalação automática do Playwright
- [ ] `first_run.bat` — Script de primeira execução (Windows)
- [ ] `bot/payment/service.py` — Atualizar email com link de download
- [ ] `requirements-exe.txt` — Dependências para o .exe (playwright, etc.)
- [ ] `README_EXE.md` — Instruções para o usuário final

## Tamanho estimado do .exe
- Código Python + dependências: ~15-20MB
- Playwright Chromium: ~180MB (se bundled) ou download separado
- Total: ~200MB (bundled) ou ~20MB + download na primeira execução

## Decisão pendente
- CLI ou GUI? (CLI = mais simples, GUI = mais profissional)
- Bundled Chromium ou download separado?
- Onde hostear o .exe para download?
