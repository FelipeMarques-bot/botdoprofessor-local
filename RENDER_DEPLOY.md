# Deploy no Render — Guia Passo a Passo

Apos o deploy, a landing page com assinaturas estara em:
[https://botdoprofessor.onrender.com](https://botdoprofessor.onrender.com)

## Pre-requisitos
- Conta no GitHub (repositorio do projeto)
- Conta no Render (render.com)
- Chaves Mercado Pago (Public Key + Access Token)

---

## Passo 1 — Push para o GitHub

No terminal, dentro de `C:\Users\Adm\Desktop\BotDoProfessor-Local`:

```bash
git init
git add .
git commit -m "BotDoProfessor v1.0"
git remote add origin https://github.com/SEU-Usuario/BotDoProfessor-Local.git
git push -u origin main
```

## Passo 2 — Criar Web Service no Render

1. Acesse https://dashboard.render.com
2. Clique em **"New +"** → **"Web Service"**
3. Conecte sua conta GitHub
4. Selecione o repositorio `BotDoProfessor-Local`
5. Configure:

| Campo | Valor |
|-------|-------|
| Name | `botdoprofessor` |
| Runtime | `Python 3` |
| Build Command | `pip install -r requirements.txt && playwright install chromium` |
| Start Command | `python app.py` |
| Instance Type | `Free` (ou `Starter` para producao) |

## Passo 3 — Criar Banco PostgreSQL (Neon)

O SQLite nao persiste entre deploys no Render. Use PostgreSQL gratuito no Neon:

1. Acesse https://neon.tech e crie uma conta gratis
2. Crie um projeto (regiao: AWS US East ou similar)
3. No painel, va em **Connection Details** e copie a **Connection String** (formato: `postgresql://...`)
4. No Render, va em **Environment** e adicione:

```
DATABASE_URL=<cole a connection string do Neon>
```

**IMPORTANTE:** A string do Neon vem com `postgres://` — o Render converte automaticamente para `postgresql://`.

> O banco PostgreSQL e **persistente** — seus dados (usuarios, pagamentos, licencas) nao serao apagados entre deploys.

## Passo 4 — Variaveis de Ambiente no Render

Na pagina do Web Service, va em **"Environment"** e adicione:

```
SECRET_KEY=<gerar um aleatorio longo>
APP_URL=https://botdoprofessor.onrender.com
MP_PUBLIC_KEY=TEST-0c535199-a88c-4153-b69b-07c063d8a38b
MP_ACCESS_TOKEN=TEST-4683227438495768-071612-c3f780c572e0e884fcb851f05eca499c-330006403
PIX_KEY=<sua chave pix>
PIX_NAME=BotDoProfessor
CONTACT_EMAIL=labintelligenceappoiments@gmail.com
SMTP_USER=ensinoreligiosoemacao@gmail.com
SMTP_PASS=<senha de app Gmail>
AI_PROVIDER=local
ADMIN_USER=admin
ADMIN_PASS=<sua senha segura>
```

## Passo 5 — Deploy automatico

Apos salvar, o Render faz o deploy automatico. O site ficara em:
`https://botdoprofessor.onrender.com`

---

## Passo 6 — Configurar Webhook no Mercado Pago

1. Acesse https://www.mercadopago.com.br/developers
2. Va em **"Credenciais"** → **"Webhooks"**
3. Clique em **"Adicionar webhook"**
4. Preencha:

| Campo | Valor |
|-------|-------|
| URL | `https://botdoprofessor.onrender.com/api/webhook/mercadopago` |
| Evento | `Pagamentos` |

5. Salve

## Passo 7 — Trocar para Producao

Quando estiver pronto para vender:

1. No Mercado Pago, va em **Credenciais** → **Producao**
2. Copie a **Public Key** e **Access Token** de Producao
3. No Render, atualize as variaveis:
   - `MP_PUBLIC_KEY` → Production Key (`APP_USR-xxxx`)
   - `MP_ACCESS_TOKEN` → Production Token (`APP_USR-xxxx`)

## Passo 8 — Configurar Email (Gmail)

Para o Gmail enviar emails automaticamente:

1. Acesse https://myaccount.google.com
2. Seguranca → Verificacao em 2 etapas → Ativar
3. Depois, Seguranca → Senhas de app
4. Gere uma senha para "BotDoProfessor"
5. Use essa senha no campo `SMTP_PASS`

---

## Checklist pos-deploy

- [ ] Site acessivel em https://botdoprofessor.onrender.com
- [ ] Checkout com cartao funcionando (Mercado Pago teste)
- [ ] Checkout com Pix funcionando
- [ ] Email de licenca sendo enviado
- [ ] Webhook recebendo notificacoes
- [ ] Trocar credenciais TEST para PRODUCTION
