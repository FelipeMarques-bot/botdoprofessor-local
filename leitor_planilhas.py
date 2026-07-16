import csv
import io
import os
import re
import tempfile
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple

LogFn = Callable[[str], None]


@dataclass
class RegistroNota:
    escola: str
    turno: str
    turma: str
    trimestre: str
    aluno: str
    atividade: str
    nota: float


def _normalize(s: str) -> str:
    import unicodedata
    text = (s or "").strip().lower()
    text = text.replace("º", "o").replace("°", "o").replace("ª", "a")
    text = text.replace("\u00a0", " ")
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = "".join(ch for ch in text if unicodedata.category(ch) not in {"Cf", "Cc"})
    return re.sub(r"\s+", " ", text)


def _to_float(value: object) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(" ", "")
    if not text:
        return None
    text = text.replace(",", ".")
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        try:
            return float(text)
        except ValueError:
            return None
    return None


IGNORE_COLS = {
    "Nome", "Status", "Status Fluxo", "Media", "Media Final",
    "Observacoes", "Observacoes Pedagogicas",
}


def _is_grade_column(col_name: str) -> bool:
    clean = col_name.strip()
    if not clean or clean in IGNORE_COLS:
        return False
    lowered = clean.lower()
    blacklist = ["status", "media", "obs", "coment", "nome", "id", "chamada", "frequencia"]
    return all(word not in lowered for word in blacklist)


def ler_notas_excel(caminho: str, logger: Optional[LogFn] = None) -> List[RegistroNota]:
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl nao instalado. Rode: pip install openpyxl")

    wb = openpyxl.load_workbook(caminho, data_only=True)
    registros: List[RegistroNota] = []

    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue

        headers = [str(h or "") for h in rows[0]]

        col_escola = _find_col_index(headers, ["escola", "escola"])
        col_turno = _find_col_index(headers, ["turno", "turno"])
        col_turma = _find_col_index(headers, ["turma", "turma", "classe", "sala"])
        col_trimestre = _find_col_index(headers, ["trimestre", "trimestre", "bimestre", "periodo"])
        col_nome = _find_col_index(headers, ["nome", "nome", "aluno", "estudante", "nome aluno"])

        grade_cols = {}
        for i, h in enumerate(headers):
            if _is_grade_column(h):
                grade_cols[i] = h.strip()

        if col_nome is None:
            continue

        escola = ""
        turno = ""
        turma = ""
        trimestre = ""
        info_rows = [r for r in rows[1:] if any(v is not None for v in r)]

        for row in info_rows:
            if col_escola is not None and not escola:
                escola = str(row[col_escola] or "").strip()
            if col_turno is not None and not turno:
                turno = str(row[col_turno] or "").strip()
            if col_turma is not None and not turma:
                turma = str(row[col_turma] or "").strip()
            if col_trimestre is not None and not trimestre:
                trimestre = str(row[col_trimestre] or "").strip()

        if not escola:
            escola = os.path.splitext(os.path.basename(caminho))[0]
        if not turno:
            turno = "Nao informado"
        if not turma:
            turma = sheet_name
        if not trimestre:
            trimestre = "Nao informado"

        for row in info_rows:
            nome = str(row[col_nome] or "").strip()
            if not nome:
                continue

            for col_idx, atividade in grade_cols.items():
                nota = _to_float(row[col_idx] if col_idx < len(row) else None)
                if nota is None:
                    continue
                registros.append(RegistroNota(
                    escola=escola,
                    turno=turno,
                    turma=turma,
                    trimestre=trimestre,
                    aluno=nome,
                    atividade=atividade,
                    nota=nota,
                ))

        if logger:
            logger(f"Planilha '{sheet_name}': {len([r for r in info_rows if str(r[col_nome] or '').strip()])} alunos, {len(grade_cols)} atividades com notas")

    wb.close()
    return registros


def ler_notas_csv(caminho: str, logger: Optional[LogFn] = None) -> List[RegistroNota]:
    registros: List[RegistroNota] = []
    with open(caminho, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        headers = reader.fieldnames or []

        grade_cols = {h: h for h in headers if _is_grade_column(h) and _normalize(h) not in ("nome", "aluno")}
        nome_col = _find_header(headers, ["nome", "aluno", "estudante"])
        escola_col = _find_header(headers, ["escola"])
        turno_col = _find_header(headers, ["turno"])
        turma_col = _find_header(headers, ["turma", "classe", "sala"])
        trimestre_col = _find_header(headers, ["trimestre", "bimestre", "periodo"])

        if not nome_col:
            if logger:
                logger("CSV: coluna 'Nome' nao encontrada")
            return registros

        for row in reader:
            nome = (row.get(nome_col) or "").strip()
            if not nome:
                continue
            for col_h, atividade in grade_cols.items():
                raw = (row.get(col_h) or "").strip()
                nota = _to_float(raw)
                if nota is None:
                    continue
                registros.append(RegistroNota(
                    escola=(row.get(escola_col) or "").strip() or "Nao informado",
                    turno=(row.get(turno_col) or "").strip() or "Nao informado",
                    turma=(row.get(turma_col) or "").strip() or "Nao informado",
                    trimestre=(row.get(trimestre_col) or "").strip() or "Nao informado",
                    aluno=nome,
                    atividade=atividade,
                    nota=nota,
                ))

    if logger:
        logger(f"CSV: {len(registros)} notas carregadas")
    return registros


def ler_notas_google_sheets(url_or_id: str, logger: Optional[LogFn] = None) -> List[RegistroNota]:
    sheet_id = _extract_sheet_id(url_or_id)
    if not sheet_id:
        raise ValueError(f"URL/ID de planilha invalida: {url_or_id}")

    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"

    try:
        with urllib.request.urlopen(export_url, timeout=30) as resp:
            content = resp.read().decode("utf-8-sig")
    except Exception as exc:
        raise RuntimeError(f"Falha ao baixar planilha do Google Sheets: {exc}")

    registros: List[RegistroNota] = []
    reader = csv.DictReader(io.StringIO(content))
    headers = reader.fieldnames or []

    grade_cols = {h: h for h in headers if _is_grade_column(h) and _normalize(h) not in ("nome", "aluno")}
    nome_col = _find_header(headers, ["nome", "aluno", "estudante"])
    escola_col = _find_header(headers, ["escola"])
    turno_col = _find_header(headers, ["turno"])
    turma_col = _find_header(headers, ["turma", "classe", "sala"])
    trimestre_col = _find_header(headers, ["trimestre", "bimestre", "periodo"])

    if not nome_col:
        if logger:
            logger("Google Sheets: coluna 'Nome' nao encontrada")
        return registros

    for row in reader:
        nome = (row.get(nome_col) or "").strip()
        if not nome:
            continue
        for col_h, atividade in grade_cols.items():
            raw = (row.get(col_h) or "").strip()
            nota = _to_float(raw)
            if nota is None:
                continue
            registros.append(RegistroNota(
                escola=(row.get(escola_col) or "").strip() or "Nao informado",
                turno=(row.get(turno_col) or "").strip() or "Nao informado",
                turma=(row.get(turma_col) or "").strip() or "Nao informado",
                trimestre=(row.get(trimestre_col) or "").strip() or "Nao informado",
                aluno=nome,
                atividade=atividade,
                nota=nota,
            ))

    if logger:
        logger(f"Google Sheets: {len(registros)} notas carregadas")
    return registros


def _find_header(headers: List[str], candidates: List[str]) -> Optional[str]:
    h_norm = {h: _normalize(h) for h in headers}
    for cand in candidates:
        cand_norm = _normalize(cand)
        for h, hn in h_norm.items():
            if cand_norm == hn:
                return h
    for cand in candidates:
        cand_norm = _normalize(cand)
        for h, hn in h_norm.items():
            if cand_norm in hn or hn in cand_norm:
                return h
    return None


def _find_col_index(headers: List[str], candidates: List[str]) -> Optional[int]:
    h_norm = {i: _normalize(h) for i, h in enumerate(headers)}
    for cand in candidates:
        cand_norm = _normalize(cand)
        for i, hn in h_norm.items():
            if cand_norm == hn:
                return i
    for cand in candidates:
        cand_norm = _normalize(cand)
        for i, hn in h_norm.items():
            if cand_norm in hn or hn in cand_norm:
                return i
    return None


def ler_notas_google_drive(url_or_id: str, logger: Optional[LogFn] = None) -> List[RegistroNota]:
    try:
        import gdown
    except ImportError:
        raise RuntimeError("gdown nao instalado. Rode: pip install gdown")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx")
    tmp_path = tmp.name
    tmp.close()

    try:
        if re.match(r"^https?://", url_or_id):
            gdown.download(url_or_id, tmp_path, quiet=True)
        else:
            gdown.download(id=url_or_id, output=tmp_path, quiet=True)

        ext = os.path.splitext(url_or_id)[1].lower()
        if ext == ".csv":
            registros = ler_notas_csv(tmp_path, logger=logger)
        else:
            registros = ler_notas_excel(tmp_path, logger=logger)

        os.unlink(tmp_path)
        if logger:
            logger(f"Google Drive: {len(registros)} notas carregadas")
        return registros
    except Exception as exc:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise RuntimeError(f"Falha ao baixar arquivo do Google Drive: {exc}")


def _extract_sheet_id(url_or_id: str) -> Optional[str]:
    url_or_id = url_or_id.strip()
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9_-]+)", url_or_id)
    if match:
        return match.group(1)
    if re.match(r"^[a-zA-Z0-9_-]{20,}$", url_or_id):
        return url_or_id
    return None


def carregar_notas(
    fonte: str,
    caminho_ou_url: str,
    logger: Optional[LogFn] = None,
) -> List[RegistroNota]:
    if fonte == "notion":
        msg = "Use lancar_notas_sge.carregar_notas_notion() para fonte Notion"
        raise ValueError(msg)

    if fonte == "excel":
        if not os.path.exists(caminho_ou_url):
            raise FileNotFoundError(f"Arquivo nao encontrado: {caminho_ou_url}")
        return ler_notas_excel(caminho_ou_url, logger=logger)

    if fonte == "csv":
        if not os.path.exists(caminho_ou_url):
            raise FileNotFoundError(f"Arquivo nao encontrado: {caminho_ou_url}")
        return ler_notas_csv(caminho_ou_url, logger=logger)

    if fonte == "google_sheets":
        return ler_notas_google_sheets(caminho_ou_url, logger=logger)

    if fonte == "google_drive":
        return ler_notas_google_drive(caminho_ou_url, logger=logger)

    raise ValueError(f"Fonte desconhecida: {fonte}. Use: excel, csv, google_sheets, google_drive, notion")
