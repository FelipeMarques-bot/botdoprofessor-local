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


def _csv_skip_comments(f):
    for line in f:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue
        yield line


def ler_notas_csv(caminho: str, logger: Optional[LogFn] = None) -> List[RegistroNota]:
    registros: List[RegistroNota] = []
    with open(caminho, encoding="utf-8-sig") as f:
        reader = csv.DictReader(_csv_skip_comments(f))
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


def _normalize_str(s: str) -> str:
    import unicodedata
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch)).strip()


def gerar_template_notas_xlsx() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Exemplo - 6º Ano"
    headers = [
        "Escola", "Turno", "Turma", "Trimestre",
        "Nome do Aluno", "Atividade 1", "Atividade 2", "Atividade 3",
        "Data realização 1", "Data realização 2", "Data realização 3",
        "Observações 1", "Observações 2", "Observações 3",
    ]
    ws.append(headers)
    ws.append([
        "Juvenal", "Matutino", "6º Ano", "1º Trimestre",
        "Exemplo Aluno", "8,5", "7,0", "9,0",
        "01/03/2026", "15/04/2026", "20/05/2026",
        "", "", "",
    ])
    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[col[0].column_letter].width = max(max_len + 2, 18)

    _add_notas_instrucoes(wb)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _add_notas_instrucoes(wb):
    ws2 = wb.create_sheet("Instrucoes", 0)
    instrucoes = [
        ["INSTRUCOES - PLANILHA DE NOTAS", "", ""],
        ["", "", ""],
        ["O que e cada coluna:", "", ""],
        ["", "", ""],
        ["Coluna", "O que preencher", "Exemplo"],
        ["Escola", "Nome da escola (como aparece no portal)", "Juvenal"],
        ["Turno", "Matutino, Vespertino ou Noturno", "Matutino"],
        ["Turma", "Turma completa (ex: 6o Ano, 7o Ano)", "6o Ano"],
        ["Trimestre", "1o Trimestre, 2o Trimestre ou 3o Trimestre", "1o Trimestre"],
        ["Nome do Aluno", "Nome completo do aluno", "Joao Silva"],
        ["Atividade 1", "Nota da primeira atividade (use virgula para decimal)", "8,5"],
        ["Atividade 2", "Nota da segunda atividade", "7,0"],
        ["Atividade 3", "Nota da terceira atividade", "9,0"],
        ["Data realizacao 1", "Data que a atividade 1 foi aplicada (dd/mm/aaaa)", "01/03/2026"],
        ["Data realizacao 2", "Data que a atividade 2 foi aplicada (dd/mm/aaaa)", "15/04/2026"],
        ["Data realizacao 3", "Data que a atividade 3 foi aplicada (dd/mm/aaaa)", "20/05/2026"],
        ["Observacoes 1", "Observacao sobre a atividade 1 (opcional)", ""],
        ["Observacoes 2", "Observacao sobre a atividade 2 (opcional)", ""],
        ["Observacoes 3", "Observacao sobre a atividade 3 (opcional)", ""],
        ["", "", ""],
        ["DICAS IMPORTANTES:", "", ""],
        ["1. Os nomes das atividades (Atividade 1, 2, 3) devem ser IGUAIS aos nomes", "que aparecem no portal SGE para aquela turma/trimestre.", ""],
        ["2. Preencha uma linha por aluno. Repita os dados de escola/turma/trimestre", "para cada aluno.", ""],
        ["3. Use virgula (,) como separador decimal nas notas. Ex: 8,5", "", ""],
        ["4. Datas sempre no formato: dia/mes/ano (ex: 01/03/2026)", "", ""],
        ["5. Deixe em branco o que nao for preencher.", "", ""],
    ]
    for row in instrucoes:
        ws2.append(row)
    ws2.column_dimensions["A"].width = 24
    ws2.column_dimensions["B"].width = 60
    ws2.column_dimensions["C"].width = 24


def gerar_template_notas_csv() -> str:
    buf = io.StringIO()
    _write_csv_comments(buf, [
        "INSTRUCOES - Planilha de Notas",
        "Escola: nome da escola. Ex: Juvenal",
        "Turno: Matutino, Vespertino ou Noturno",
        "Turma: 6o Ano, 7o Ano, etc.",
        "Trimestre: 1o Trimestre, 2o Trimestre ou 3o Trimestre",
        "Nome do Aluno: nome completo do aluno",
        "Atividade 1/2/3: nota de cada atividade (use virgula p/ decimal). Ex: 8,5",
        "Data realizacao 1/2/3: data da atividade no formato dd/mm/aaaa",
        "Observacoes 1/2/3: opcional",
        "",
        "IMPORTANTE: os nomes das atividades devem ser IGUAIS aos nomes no portal SGE",
        "",
    ])
    writer = csv.writer(buf)
    writer.writerow([
        "Escola", "Turno", "Turma", "Trimestre",
        "Nome do Aluno", "Atividade 1", "Atividade 2", "Atividade 3",
        "Data realização 1", "Data realização 2", "Data realização 3",
        "Observações 1", "Observações 2", "Observações 3",
    ])
    writer.writerow([
        "Juvenal", "Matutino", "6º Ano", "1º Trimestre",
        "Exemplo Aluno", "8,5", "7,0", "9,0",
        "01/03/2026", "15/04/2026", "20/05/2026",
        "", "", "",
    ])
    return buf.getvalue()


def gerar_template_sequencias_xlsx() -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sequências"
    headers = [
        "Name", "Escola", "Ano", "Periodo inicio", "Periodo fim",
        "N aulas", "Titulo Documento", "Link do Arquivo",
        "Ativo", "Observações",
    ]
    ws.append(headers)
    ws.append([
        "SD - 6º Ano - Matemática", "Juvenal", "6º Ano",
        "01/03/2026", "31/03/2026", 4,
        "Sequência Didática - Matemática - 6º Ano",
        "https://drive.google.com/your-file-link-here",
        "Sim", "",
    ])
    ws.append([
        "SD - 7º Ano - Português", "Arapongas", "7º Ano",
        "01/04/2026", "30/04/2026", 4,
        "Sequência Didática - Português - 7º Ano",
        "https://drive.google.com/your-file-link-here",
        "Sim", "",
    ])
    for col in ws.columns:
        max_len = max((len(str(c.value or "")) for c in col), default=0)
        ws.column_dimensions[col[0].column_letter].width = max(max_len + 2, 22)

    _add_seq_instrucoes(wb)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.getvalue()


def _add_seq_instrucoes(wb):
    ws2 = wb.create_sheet("Instrucoes", 0)
    instrucoes = [
        ["INSTRUCOES - PLANILHA DE SEQUENCIAS DIDATICAS", "", ""],
        ["", "", ""],
        ["O que e cada coluna:", "", ""],
        ["", "", ""],
        ["Coluna", "O que preencher", "Exemplo"],
        ["Name", "Nome da sequencia (para identificacao)", "SD - 6o Ano - Matematica"],
        ["Escola", "Nome da escola (como aparece no portal)", "Juvenal"],
        ["Ano", "Ano escolar (6o Ano, 7o Ano, 8o Ano, 9o Ano)", "6o Ano"],
        ["Periodo inicio", "Data de inicio da sequencia (dd/mm/aaaa)", "01/03/2026"],
        ["Periodo fim", "Data de termino da sequencia (dd/mm/aaaa)", "31/03/2026"],
        ["N aulas", "Numero de aulas da sequencia", "4"],
        ["Titulo Documento", "Titulo do documento que aparecera no portal", "Sequencia Didatica - Matematica - 6o Ano"],
        ["Link do Arquivo", "Link do Google Drive para o PDF do plano de aula", "https://drive.google.com/..."],
        ["Ativo", "'Sim' para processar, 'Nao' para pular esta linha", "Sim"],
        ["Observacoes", "Observacao opcional (nao vai para o portal)", ""],
        ["", "", ""],
        ["DICAS IMPORTANTES:", "", ""],
        ["1. Coloque 'Nao' na coluna Ativo para pular linhas sem deleta-las.", "", ""],
        ["2. Os links do Google Drive devem ser compartilhados como 'Qualquer um com o link pode ver'.", "", ""],
        ["3. Datas sempre no formato: dia/mes/ano (ex: 01/03/2026)", "", ""],
        ["4. Deixe em branco o que nao for preencher.", "", ""],
    ]
    for row in instrucoes:
        ws2.append(row)
    ws2.column_dimensions["A"].width = 24
    ws2.column_dimensions["B"].width = 60
    ws2.column_dimensions["C"].width = 24


def _write_csv_comments(buf, lines):
    for line in lines:
        buf.write(f"#{line}\n")


def gerar_template_sequencias_csv() -> str:
    buf = io.StringIO()
    _write_csv_comments(buf, [
        "INSTRUCOES - Planilha de Sequencias Didaticas",
        "Name: nome da sequencia para identificacao. Ex: SD - 6o Ano - Matematica",
        "Escola: nome da escola. Ex: Juvenal",
        "Ano: 6o Ano, 7o Ano, 8o Ano ou 9o Ano",
        "Periodo inicio: data de inicio (dd/mm/aaaa). Ex: 01/03/2026",
        "Periodo fim: data de termino (dd/mm/aaaa). Ex: 31/03/2026",
        "N aulas: numero de aulas. Ex: 4",
        "Titulo Documento: titulo que aparecera no portal",
        "Link do Arquivo: link do Google Drive para o PDF",
        "Ativo: Sim para processar, Nao para pular",
        "Observacoes: opcional",
        "",
        "IMPORTANTE: links do Drive devem estar como 'Qualquer um com o link pode ver'",
        "",
    ])
    writer = csv.writer(buf)
    writer.writerow([
        "Name", "Escola", "Ano", "Periodo inicio", "Periodo fim",
        "N aulas", "Titulo Documento", "Link do Arquivo",
        "Ativo", "Observações",
    ])
    writer.writerow([
        "SD - 6º Ano - Matemática", "Juvenal", "6º Ano",
        "01/03/2026", "31/03/2026", 4,
        "Sequência Didática - Matemática - 6º Ano",
        "https://drive.google.com/your-file-link-here",
        "Sim", "",
    ])
    return buf.getvalue()


def ler_sequencias_excel(caminho: str, logger: Optional[LogFn] = None) -> list:
    try:
        import openpyxl
    except ImportError:
        raise RuntimeError("openpyxl nao instalado")
    from datetime import datetime as _dt

    wb = openpyxl.load_workbook(caminho, data_only=True)
    registros = []
    for sheet_name in wb.sheetnames:
        ws = wb[sheet_name]
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            continue
        headers = [str(h or "").strip() for h in rows[0]]
        h_norm = {_normalize_str(h): i for i, h in enumerate(headers)}

        def _col(names):
            for n in names:
                nn = _normalize_str(n)
                if nn in h_norm:
                    return h_norm[nn]
            return None

        col_name = _col(["Name", "Nome", "Titulo"])
        col_escola = _col(["Escola"])
        col_ano = _col(["Ano"])
        col_periodo_inicio = _col(["Periodo inicio", "Periodo início", "Data inicio", "Data início"])
        col_periodo_fim = _col(["Periodo fim", "Periodo fim", "Data fim"])
        col_n_aulas = _col(["N aulas", "Nº aulas", "Numero de aulas"])
        col_titulo_doc = _col(["Titulo Documento", "Título Documento", "Titulo do Documento"])
        col_link = _col(["Link do Arquivo", "Link do arquivo", "Arquivo PDF", "URL"])
        col_ativo = _col(["Ativo"])

        if col_name is None:
            if logger:
                logger(f"Aba '{sheet_name}': coluna 'Name' nao encontrada. Pulando.")
            continue

        for row_idx, row in enumerate(rows[1:], start=2):
            name = str(row[col_name] or "").strip()
            if not name:
                continue
            escola = str(row[col_escola] or "").strip() if col_escola is not None else ""
            ano = str(row[col_ano] or "").strip() if col_ano is not None else ""
            periodo_inicio = _fmt_date(str(row[col_periodo_inicio] or "")) if col_periodo_inicio is not None else ""
            periodo_fim = _fmt_date(str(row[col_periodo_fim] or "")) if col_periodo_fim is not None else ""
            n_aulas_raw = row[col_n_aulas] if col_n_aulas is not None else None
            n_aulas = 4
            if n_aulas_raw is not None:
                try:
                    n_aulas = int(float(str(n_aulas_raw).replace(",", ".")))
                except (ValueError, TypeError):
                    pass
            titulo_doc = str(row[col_titulo_doc] or "").strip() if col_titulo_doc is not None else name
            link = str(row[col_link] or "").strip() if col_link is not None else ""
            ativo_raw = str(row[col_ativo] or "").strip().lower() if col_ativo is not None else "sim"
            ativo = ativo_raw in ("sim", "s", "yes", "1", "true", "verdadeiro")

            if not ativo:
                if logger:
                    logger(f"Linha {row_idx}: registro '{name}' ignorado (Ativo = '{ativo_raw}').")
                continue

            registros.append({
                "page_id": "",
                "ano": ano,
                "escola": escola,
                "turno": "",
                "turma": "",
                "titulo_documento": titulo_doc,
                "arquivo_nome": f"{name}.pdf",
                "arquivo_url": link,
                "link_arquivo": link,
                "periodo_inicio": periodo_inicio,
                "periodo_fim": periodo_fim,
                "n_aulas": n_aulas,
                "status": "",
            })

        if logger:
            logger(f"Aba '{sheet_name}': {len(registros)} sequencias carregadas.")

    wb.close()
    return registros


def ler_sequencias_csv(caminho: str, logger: Optional[LogFn] = None) -> list:
    registros = []
    from datetime import datetime as _dt

    with open(caminho, encoding="utf-8-sig") as f:
        reader = csv.DictReader(_csv_skip_comments(f))
        headers = reader.fieldnames or []
        h_norm = {_normalize_str(h): h for h in headers}

        def _col(names):
            for n in names:
                nn = _normalize_str(n)
                if nn in h_norm:
                    return h_norm[nn]
            return None

        col_name = _col(["Name", "Nome", "Titulo"])
        col_escola = _col(["Escola"])
        col_ano = _col(["Ano"])
        col_periodo_inicio = _col(["Periodo inicio", "Periodo início", "Data inicio", "Data início"])
        col_periodo_fim = _col(["Periodo fim", "Periodo fim", "Data fim"])
        col_n_aulas = _col(["N aulas", "Nº aulas", "Numero de aulas"])
        col_titulo_doc = _col(["Titulo Documento", "Título Documento", "Titulo do Documento"])
        col_link = _col(["Link do Arquivo", "Link do arquivo", "Arquivo PDF", "URL"])
        col_ativo = _col(["Ativo"])

        if not col_name:
            if logger:
                logger("CSV: coluna 'Name' nao encontrada")
            return registros

        for row in reader:
            name = (row.get(col_name) or "").strip()
            if not name:
                continue

            escola = (row.get(col_escola) or "").strip() if col_escola else ""
            ano = (row.get(col_ano) or "").strip() if col_ano else ""
            periodo_inicio = _fmt_date(row.get(col_periodo_inicio, "")) if col_periodo_inicio else ""
            periodo_fim = _fmt_date(row.get(col_periodo_fim, "")) if col_periodo_fim else ""
            n_aulas = 4
            if col_n_aulas:
                try:
                    n_aulas = int(float(str(row.get(col_n_aulas, "4")).replace(",", ".")))
                except (ValueError, TypeError):
                    pass
            titulo_doc = (row.get(col_titulo_doc) or name).strip() if col_titulo_doc else name
            link = (row.get(col_link) or "").strip() if col_link else ""
            ativo_raw = (row.get(col_ativo) or "sim").strip().lower() if col_ativo else "sim"
            ativo = ativo_raw in ("sim", "s", "yes", "1", "true", "verdadeiro")
            if not ativo:
                continue

            registros.append({
                "page_id": "",
                "ano": ano,
                "escola": escola,
                "turno": "",
                "turma": "",
                "titulo_documento": titulo_doc,
                "arquivo_nome": f"{name}.pdf",
                "arquivo_url": link,
                "link_arquivo": link,
                "periodo_inicio": periodo_inicio,
                "periodo_fim": periodo_fim,
                "n_aulas": n_aulas,
                "status": "",
            })

    if logger:
        logger(f"CSV: {len(registros)} sequencias carregadas")
    return registros


def _fmt_date(value: str) -> str:
    from datetime import datetime as _dt
    raw = value.strip()
    if not raw:
        return ""
    if re.fullmatch(r"\d{2}/\d{2}/\d{4}", raw):
        return raw
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        return _dt.strptime(raw, "%Y-%m-%d").strftime("%d/%m/%Y")
    try:
        import openpyxl
        from datetime import datetime as _py_dt
        if isinstance(value, _py_dt):
            return value.strftime("%d/%m/%Y")
    except ImportError:
        pass
    return raw


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
