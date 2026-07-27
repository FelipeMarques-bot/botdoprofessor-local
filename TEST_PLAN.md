# Plano: Teste local completo do fluxo

## O que pode ser testado localmente

### 1. Servidor Flask + Landing Page (100% testavel)
- Rodar `python app.py` → abre em http://localhost:5000
- Landing page, checkout, success pages funcionando
- Health check: http://localhost:5000/api/health

### 2. Validação de licença via .exe (100% testavel)
- `run_bot.py` aponta para localhost (variavel SERVER_URL)
- Endpoint `POST /api/license/public-validate` funcional
- Criar licenca via API admin e testar validacao

### 3. Webhook Mercado Pago (parcialmente testavel)
- Na maquina local, o webhook nao recebe notificacoes do MP
- Mas podemos simular uma chamada POST ao endpoint
- Testar se `_process_approved_payment` gera licenca e envia email

### 4. Bot Playwright + SGE (soh com credenciais)
- Precisa de CPF real + acesso ao SGE
- O `run_bot.py` pode ser testado com `--dry-run` se tivermos
- Sem credenciais reais, soh testamos ate o login

### 5. Geracao do .exe (requer PyInstaller)
- `pip install pyinstaller`
- `pyinstaller --onefile --name BotDoProfessor run_bot.py`
- Testar o .exe gerado

## Cenarios de teste

### Cenario A: Fluxo completo simulado (sem SGE)
1. `python app.py` → servidor rodando
2. Acessar http://localhost:5000 → landing page OK
3. Clicar "Assinar agora" → checkout OK
4. Criar licenca via API (admin)
5. Testar `run_bot.py` com `SERVER_URL=http://localhost:5000`
6. Validar que a licenca e aceita

### Cenario B: Webhook simulado
1. Criar pagamento via API
2. Simular notificacao POST ao webhook
3. Verificar se licenca foi gerada
4. Verificar se email foi enviado (ou log se SMTP nao configurado)

### Cenario C: .exe gerado
1. `pyinstaller --onefile --name BotDoProfessor run_bot.py`
2. Executar `dist/BotDoProfessor.exe`
3. Testar interativamente

## Limitacoes do teste local
- **Playwright + SGE**: Nao da para testar sem CPF real e portal SGE aberto
- **Email**: SMTP_PASS esta vazio no .env → email sera logado no console
- **Webhook MP**: Notificacoes so funcionam com IP publico (ngrok ou similar)
- **Mercado Pago SDK**: Em modo TESTE, so funciona com checkout real do MP

## Como executar o teste
Dependendo do modo escolhido pelo usuario:

### Modo rapido (so valida codigo)
```
python -m pytest tests/ -v  # Ja feito, 55/55 OK
```

### Modo interativo (landing + API)
```
python app.py
# Abrir http://localhost:5000 no browser
# Testar checkout, criar licenca via API
```

### Modo completo (com Playwright)
```
python run_bot.py
# Insera chave de licenca
# Insira CPF real do SGE
# Teste lancamento (dry-run ou real)
```
