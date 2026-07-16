"""Armazenamento local de status de lancamento de notas.

Quando o usuario nao usa Notion, o status (Lancada/Falha) e gravado em um
arquivo JSON ao lado da fonte de dados (CSV, Excel, etc.) ou em um diretorio
centralizado de status.
"""

import json
import os
import time
from typing import Any, Callable, Dict, List, Optional

LogFn = Callable[[str], None]


def _log(logger: Optional[LogFn], msg: str) -> None:
    if logger:
        logger(msg)


def _status_path_for_source(caminho_fonte: str) -> str:
    """Retorna o caminho do arquivo de status para uma dada fonte de dados.

    Ex: /notas/notas_2tri.xlsx -> /notas/notas_2tri.status.json
    """
    base, _ = os.path.splitext(caminho_fonte)
    return base + ".status.json"


def _central_status_path(caminho_fonte: str) -> str:
    """Caminho fallback: pasta .status/ ao lado da fonte."""
    parent = os.path.dirname(caminho_fonte) or "."
    status_dir = os.path.join(parent, ".status")
    os.makedirs(status_dir, exist_ok=True)
    basename = os.path.splitext(os.path.basename(caminho_fonte))[0]
    return os.path.join(status_dir, basename + ".json")


class StatusStore:
    """Armazena e consulta status de lancamento de notas em arquivo JSON.

    Estrutura do JSON:
    {
        "registros": {
            "<chave>": {
                "status": "Lancada" | "Falha",
                "nota": 8.5,
                "atividade": "21-Atividade",
                "aluno": "Maria",
                "timestamp": "2025-07-10T14:00:00"
            }
        },
        "ultima_atualizacao": "2025-07-10T14:00:00"
    }
    """

    def __init__(self, caminho_fonte: str, logger: Optional[LogFn] = None):
        self._logger = logger
        self._arquivo = _status_path_for_source(caminho_fonte)
        self._dados: Dict[str, Any] = {"registros": {}, "ultima_atualizacao": ""}
        self._carregar()

    def _carregar(self) -> None:
        if os.path.exists(self._arquivo):
            try:
                with open(self._arquivo, encoding="utf-8") as f:
                    self._dados = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                _log(self._logger, f"Aviso: arquivo de status corrompido, criando novo: {exc}")
                self._dados = {"registros": {}, "ultima_atualizacao": ""}
        else:
            self._dados = {"registros": {}, "ultima_atualizacao": ""}

        if "registros" not in self._dados:
            self._dados["registros"] = {}

    def _salvar(self) -> None:
        self._dados["ultima_atualizacao"] = _agora()
        try:
            with open(self._arquivo, "w", encoding="utf-8") as f:
                json.dump(self._dados, f, ensure_ascii=False, indent=2)
        except OSError as exc:
            _log(self._logger, f"Aviso: falha ao salvar status: {exc}")

    def _chave(self, escola: str, turno: str, turma: str, trimestre: str,
               aluno: str, atividade: str) -> str:
        return "|".join([
            escola.strip().lower(),
            turno.strip().lower(),
            turma.strip().lower(),
            trimestre.strip().lower(),
            aluno.strip().lower(),
            atividade.strip().lower(),
        ])

    def esta_lancada(self, escola: str, turno: str, turma: str, trimestre: str,
                      aluno: str, atividade: str) -> bool:
        """Verifica se a nota ja foi lancada com sucesso."""
        chave = self._chave(escola, turno, turma, trimestre, aluno, atividade)
        reg = self._dados["registros"].get(chave, {})
        return reg.get("status") == "Lancada"

    def marcar_lancada(self, escola: str, turno: str, turma: str, trimestre: str,
                        aluno: str, atividade: str, nota: float) -> None:
        """Marca uma nota como lancada com sucesso."""
        chave = self._chave(escola, turno, turma, trimestre, aluno, atividade)
        self._dados["registros"][chave] = {
            "status": "Lancada",
            "nota": nota,
            "atividade": atividade,
            "aluno": aluno,
            "timestamp": _agora(),
        }
        self._salvar()

    def marcar_falha(self, escola: str, turno: str, turma: str, trimestre: str,
                      aluno: str, atividade: str, nota: float, erro: str = "") -> None:
        """Marca uma nota com falha no lancamento."""
        chave = self._chave(escola, turno, turma, trimestre, aluno, atividade)
        self._dados["registros"][chave] = {
            "status": "Falha",
            "nota": nota,
            "atividade": atividade,
            "aluno": aluno,
            "erro": erro,
            "timestamp": _agora(),
        }
        self._salvar()

    def marcar_lote(self, registros: List[Dict[str, Any]], status: str) -> int:
        """Marca varios registros de uma vez. Retorna quantidade atualizada."""
        count = 0
        for reg in registros:
            chave = self._chave(
                reg.get("escola", ""),
                reg.get("turno", ""),
                reg.get("turma", ""),
                reg.get("trimestre", ""),
                reg.get("aluno", ""),
                reg.get("atividade", ""),
            )
            self._dados["registros"][chave] = {
                "status": status,
                "nota": reg.get("nota"),
                "atividade": reg.get("atividade", ""),
                "aluno": reg.get("aluno", ""),
                "timestamp": _agora(),
            }
            count += 1
        if count:
            self._salvar()
        return count

    def contar_por_status(self) -> Dict[str, int]:
        """Retorna contagem de registros por status."""
        contagem: Dict[str, int] = {}
        for reg in self._dados["registros"].values():
            s = reg.get("status", "Desconhecido")
            contagem[s] = contagem.get(s, 0) + 1
        return contagem

    @property
    def arquivo(self) -> str:
        return self._arquivo


def _agora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
