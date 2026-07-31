# Launcher — documentação técnica

O `launcher.py` é o ponto de entrada do executável distribuído aos usuários
(`BotDoProfessor.exe`, compilado com PyInstaller). Ele cuida de toda a instalação
de forma transparente: valida a licença, cria o ambiente virtual, instala as
dependências e sobe o painel Streamlit, abrindo o navegador automaticamente.

## Fluxo de execução

1. **Validação de licença** — na primeira execução solicita a chave (janela de
   ativação) e valida em `POST {LICENSE_SERVER_URL}/api/license/public-validate`,
   com cache de 7 dias em `~/.bot_local/config.json`, 3 tentativas e timeout de 25s.
2. **Seleção do Python** — `find_system_python()` procura Python 3.10+ instalado,
   priorizando versões mais novas (ex.: `Python312`). Se não houver, usa o Python
   embutido 3.11.9 baixado para `~/.bot_local/python_portable`.
3. **Ambiente virtual** (`~/.bot_local/venv`) — `_venv_works()` confere a versão
   do Python e a importação dos módulos críticos; se falhar, o launcher deleta e
   recria o venv automaticamente (com nova tentativa de recovery).
4. **Diagnóstico de compatibilidade** — importa `_multiprocessing`; se não carregar,
   informa ao usuário o conflito entre Python 3.11 e 3.12 no PATH.
5. **Streamlit** — sobe `painel.py` e aguarda resposta em `http://localhost:8501`.

## Comando de inicialização do Streamlit

```python
[VENV_PYTHON, "-m", "streamlit", "run", painel_path,
 "--server.headless", "true",
 "--server.address", "127.0.0.1",
 "--server.port", "8501",
 "--browser.gatherUsageStats", "false"]
```

### Por que `--server.address=127.0.0.1`

Sem esse parâmetro, o Streamlit chama `net_util.get_external_ip()` para imprimir
a URL externa (bootstrap.py → `_print_url`). Esse caminho faz `import requests`
no `net_util.py`, que importa `idna` → `unicodedata`. Em máquinas com Python 3.11
e 3.12 em conflito (ex.: restos do uv/hermes-agent no ambiente), o import pode
carregar o `unicodedata.pyd` da versão errada e abortar o processo com:

```
ImportError: Module use of python311.dll conflicts with this version of Python.
```

Com `--server.address=127.0.0.1` o Streamlit pula essa detecção por completo:
o painel abre direto em `localhost` (mais seguro — a porta não fica exposta na
rede) e a falha deixa de ser possível nesse caminho.

## Variáveis de ambiente do subprocesso

Ambiente limpo para o processo do Streamlit:

- `PATH` = `venv\Scripts` + diretório do Python selecionado + `DLLs` +
  `Lib\site-packages\PyQt5` + `%SystemRoot%\system32` + `%SystemRoot%`
- remove `PYTHONPATH`, `PYTHONHOME` e `PYTHONNOUSERSITE`
- define `PYTHONDONTWRITEBYTECODE=1`

## Validação do venv

`_venv_works()` executa, no Python do venv:

```python
import unicodedata, requests, charset_normalizer, idna, streamlit
```

Qualquer falha → rebuild automático do venv antes de abrir o painel.

## Build do executável

Compilar **sempre** com Python 3.11.15 para evitar o falso positivo do Windows
Defender (`Trojan:Win32/Wacatac.B!ml`) que ocorre com builds feitos em Python 3.12:

```
python -m PyInstaller BotDoProfessor.spec --noconfirm --clean
```

- UPX não é utilizado (reduz falsos positivos).
- Artefato gerado em `dist/BotDoProfessor.exe`.
- Verificação de segurança: `MpCmdRun.exe -Scan -ScanType 3 -File dist\BotDoProfessor.exe`.

## Changelog técnico

- **v1.4.1** — adiciona `--server.address=127.0.0.1` (elimina o crash da detecção
  de IP externo); `_venv_works()` passa a testar `unicodedata`, `requests`,
  `charset_normalizer`, `idna` e `streamlit`.
- **v1.4.0** — adiciona validação de licença no launcher (janela de ativação).
