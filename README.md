# Bot do Professor

Automacao de lancamento de notas do Notion para o portal SGE (sge8147.com.br).

## O que faz

1. Le as notas de databases do Notion (por escola, turno, turma, trimestre e atividade)
2. Abre o portal SGE via navegador automatizado (Playwright)
3. Preenche as notas de cada aluno na grade do SGE
4. Marca no Notion o status como "Lancada" apos cada lancamento bem-sucedido
5. (Opcional) Usa IA local (Ollama) para辅助ar navegacao quando elementos nao sao encontrados

## Requisitos

- **Windows 10/11**
- **Python 3.12+** (o `run.bat` instala automaticamente)
- **Conta no portal SGE** (credenciais CPF + senha)
- **Integracao com Notion** (token de integracao + ID da pagina raiz)

## Instalacao rapida

1. Copie a pasta do projeto para a maquina
2. Clique duas vezes em `run.bat`
3. O script instala tudo automaticamente:
   - Python (se nao tiver)
   - Dependencias (`requirements.txt`)
   - Navegador Chromium (Playwright)
   - Ollama + modelo de IA (opcional)
4. Na primeira execucao, o arquivo `.env` e criado e aberto para edicao
5. Preencha as credenciais e salve
6. O painel web abre automaticamente no navegador

## Configuracao

Edite o arquivo `.env` (criado na primeira execucao):

| Variavel | Obrigatoria | Descricao |
|----------|:-----------:|-----------|
| `SGE_CPF` | Sim | CPF de login no portal SGE |
| `SGE_SENHA` | Sim | Senha do portal SGE |
| `NOTION_TOKEN` | Sim | Token de integracao do Notion |
| `ROOT_PAGE_ID` | Sim | ID da pagina raiz do Notion |
| `AI_ASSIST` | Nao | `1` para ativar IA, `0` para desativar |
| `AI_PROVIDER` | Nao | `ollama` (local), `gemini` (Google), `openai` (GPT-4o), `anthropic` (Claude) |
| `HEADLESS` | Nao | `0` para ver o navegador, `1` para oculto |

Consulte `.env.example` para todas as opcoes disponiveis.

## Como obter as credenciais do Notion

1. Acesse https://www.notion.so/my-integrations
2. Crie uma nova integracao e copie o **Token**
3. No Notion, abra a pagina raiz do workspace
4. Clique em "..." > "Connections" > adicione sua integracao
5. O **Page ID** esta na URL: `notion.so/workspace/PAGE_ID?...`

## Estrutura do Notion

O bot espera encontrar databases no Notion com:

- **Colunas de nota**: nomeadas com padrao like `21-Atividade Avaliativa Individua`
- **Coluna Status**: `Status lancamento N` (ex: `Status lancamento 1`) com opcao "Lancada"
- **Contexto**: escola, turno, turma e trimestre devem estar nas propriedades do database

O bot detecta automaticamente quais colunas sao notas (ignorando colunas como "ID", "Aluno", "Escola", etc.).

## Uso pelo painel web

1. Execute `run.bat` ou `python -m streamlit run painel.py`
2. No painel, configure:
   - Credenciais do SGE (se nao estiver no `.env`)
   - Token do Notion e Page ID (se nao estiver no `.env`)
   - Filtros: escola, turno, turma, trimestre
3. Clique em "Lancar Notas"
4. Acompanhe o progresso no log

## Uso pela linha de comando

```bash
# Listar contextos disponiveis
python lancar_notas_sge.py --listar-contextos

# Lancar notas com filtros
python lancar_notas_sge.py --escola "EMEF" --turno "Vespertino" --turma "9o Ano"

# Dry-run (sem enviar ao SGE)
python lancar_notas_sge.py --dry-run
```

## Protecao contra duplicacao

O bot verifica antes de cada lancamento:

1. **Status no Notion**: se ja esta "Lancada", pula o registro
2. **Valor no SGE**: se a celula ja tem nota preenchida, nao sobrescreve e apenas confirma o status no Notion

## Arquitetura

```
BotDoProfessor/
  painel.py                     # Interface Streamlit
  lancar_notas_sge.py           # Logica principal de lancamento
  notion_lancamento.py          # Helpers de integracao Notion
  ai_assist.py                  # Integracao com Ollama / Gemini
  lancar_sequencia_didatica_sge.py  # Lancamento de sequencia didatica
  requirements.txt              # Dependencias Python
  run.bat                       # Instalador + executor (Windows)
  .env.example                  # Modelo de configuracao
```

## Assinatura

Para obter uma chave de licenca, acesse a pagina de assinatura:
[https://botdoprofessor.onrender.com](https://botdoprofessor.onrender.com)

Apos a compra, a chave sera enviada por email. Use-a no launcher para ativar o software.

## Solucao de problemas

### "Python nao encontrado"
- Instale Python em https://python.org
- Marque **"Add Python to PATH"** durante a instalacao
- Reinicie o terminal

### "NOTION_TOKEN ausente"
- Verifique se o `.env` existe e tem o token preenchido
- O token comeca com `secret_`

### "Nenhuma nota valida foi encontrada no Notion"
- Verifique se os databases tem colunas de nota com valores numericos
- Confirme se o `ROOT_PAGE_ID` esta correto
- O bot ignora registros sem nota preenchida

### Nota ja lancada mas status nao atualizado no Notion
- Verifique se existe a propriedade "Status lancamento N" no database do Notion
- O tipo da propriedade deve ser **Select** com opcao "Lancada"

### Bot nao encontra aluno no SGE
- O bot tenta encontrar o aluno por nome com paginação
- Verifique se o nome no Notion confere exatamente com o nome no SGE
- Ative `AI_ASSIST=1` para usar IA como fallback

### Erro 500 do Ollama
- Maquinas com RAM < 16GB ou sem GPU dedicada podem ter problemas com modelos grandes
- O bot usa automaticamente `openbmb/minicpm-v4.6` (1.6GB) como fallback
- Desative com `AI_ASSIST=0` se nao precisar de IA

## Licenca

Uso interno. Nao distribuir.
