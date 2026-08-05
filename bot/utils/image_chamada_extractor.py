"""Extract chamada (frequencia de um dia) from a photo of the class diary using AI vision.

Usage:
    from bot.utils.image_chamada_extractor import extract_chamada_from_image
    chamada = extract_chamada_from_image(image_bytes)
"""

import logging
from typing import Any, Callable, Dict, Optional

log = logging.getLogger(__name__)

LogFn = Callable[[str], None]


def extract_chamada_from_image(
    image_bytes: bytes,
    logger: Optional[LogFn] = None,
) -> Dict[str, Any]:
    """Extrai a chamada (aluno x situacao) de uma foto do diario de classe.

    Delega para ai_assist.extrair_chamada_imagem, que usa o mesmo pipeline
    reforcado das notas (fallback entre provedores, parsing tolerante, retry).

    Returns:
        Dict com chaves: alunos, total_encontrados, data, observacoes, error
    """
    if not image_bytes:
        return {"alunos": [], "total_encontrados": 0, "error": "Imagem vazia"}

    def _log(msg: str):
        if logger:
            logger(msg)
        log.info(msg)

    _log("[ChamadaExtractor] Enviando imagem para analise de IA...")
    _log(f"[ChamadaExtractor] Tamanho da imagem: {len(image_bytes)} bytes")

    try:
        from ai_assist import extrair_chamada_imagem
        alunos = extrair_chamada_imagem(image_bytes, logger=_log)
    except Exception as e:  # noqa: BLE001
        _log(f"[ChamadaExtractor] ERRO ao chamar IA: {e}")
        return {"alunos": [], "total_encontrados": 0, "error": str(e)}

    total = len(alunos)
    _log(f"[ChamadaExtractor] {total} aluno(s) extraidos.")

    return {
        "alunos": alunos,
        "total_encontrados": total,
        "confianca": "alta" if total else "baixa",
        "observacoes": "" if total else "Nenhuma chamada lida na imagem.",
    }
