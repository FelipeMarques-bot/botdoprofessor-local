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

## Execução do painel fora do diretório de extração (`_MEI`)

**Causa raiz dos erros de "python311.dll conflicts" e "LookupError: unknown
encoding: idna" nos usuários:** o executável é compilado com Python 3.11 e o
PyInstaller (onefile) extrai em `%TEMP%\_MEIxxxxx` um ambiente completo da 3.11,
incluindo `unicodedata.pyd`, `_socket.pyd`, `_ssl.pyd`, `select.pyd`, etc.
(build 3.11), junto com o `painel.py` e os demais módulos do app (`--add-data`).

O launcher sobe o Streamlit com o Python 3.12 do venv do usuário. Como o script
`painel.py` roda de dentro do `_MEI`, aquele diretório vira `sys.path[0]` e o
interpretador 3.12 passa a carregar as extensões 3.11 ali dentro:

- `import unicodedata` → `ImportError: Module use of python311.dll conflicts...`
- `urllib → socket.getaddrinfo → codec idna → import encodings.idna → unicodedata`
  → o `ImportError` é engolido pelo `encodings.search_function` e vira
  `LookupError: unknown encoding: idna` (ex.: ao validar a licença no painel).

**Solução:** `get_painel_path()` (apenas em modo frozen) copia os módulos do app
do bundle para `~/.bot_local/app/` e retorna esse caminho. O Streamlit roda o
`painel.py` de lá, então `sys.path[0]` passa a ser um diretório limpo (sem `.pyd`
3.11) e todos os imports resolvem para o Python 3.12. Os arquivos são
ressincronizados a cada execução quando a versão do bundle muda (compara `mtime`).

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

- **v1.4.3** — endurecimento: no modo frozen o Streamlit roda com
  `PYTHONSAFEPATH=1` e `PYTHONPATH=~/.bot_local/app`, garantindo que o diretório
  de extração `_MEI` (com `.pyd` 3.11) nunca entre no `sys.path` do processo;
  `get_painel_path()` registra em log o caminho escolhido.
- **v1.4.2** — `get_painel_path()` em modo frozen copia os módulos do bundle para
  `~/.bot_local/app/`, evitando que o Streamlit (Python 3.12) importe as extensões
  3.11 extraídas pelo PyInstaller no `_MEI` (causa do crash `python311.dll
  conflicts` e do `LookupError: unknown encoding: idna` na validação de licença).
- **v1.4.1** — adiciona `--server.address=127.0.0.1` (elimina o crash da detecção
  de IP externo); `_venv_works()` passa a testar `unicodedata`, `requests`,
  `charset_normalizer`, `idna` e `streamlit`.
- **v1.4.0** — adiciona validação de licença no launcher (janela de ativação).
