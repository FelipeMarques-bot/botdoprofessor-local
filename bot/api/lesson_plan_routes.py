import os
import re
import uuid
import tempfile
import urllib.request
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from bot.security.auth import require_auth
from bot.models.audit import AuditLog

lesson_plan_bp = Blueprint("lesson_plan", __name__, url_prefix="/api/lesson-plan")


def _download_pdf_from_url(url: str, name_hint: str = "plano_aula.pdf") -> str:
    """Download PDF from URL (Google Drive or direct link)."""
    dl_url = url
    m = re.search(
        r"(?:drive\.google\.com/file/d/|drive\.google\.com/open\?id=|drive\.google\.com/uc\?id=)([a-zA-Z0-9_-]+)",
        url,
    )
    if m:
        dl_url = f"https://drive.google.com/uc?export=download&id={m.group(1)}"

    base_name = (name_hint or "plano_aula.pdf").strip()
    if not base_name.lower().endswith(".pdf"):
        base_name = f"{base_name}.pdf"
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", base_name)
    tmp_dir = tempfile.mkdtemp(prefix="plano_aula_")
    target = os.path.join(tmp_dir, safe_name)

    req = urllib.request.Request(dl_url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=45) as resp:
        data = resp.read()
    with open(target, "wb") as f:
        f.write(data)
    return target


@lesson_plan_bp.route("/execute", methods=["POST"])
@require_auth
def execute_lesson_plan():
    data = request.get_json() or {}
    escola = data.get("escola", "")
    turno = data.get("turno", "")
    turma = data.get("turma", "")
    trimestre = data.get("trimestre", "")
    titulo = data.get("titulo", "")
    data_inicio = data.get("data_inicio", "")
    data_fim = data.get("data_fim", "")
    n_aulas = data.get("n_aulas", 1)

    if not escola or not titulo or not data_inicio or not data_fim:
        return jsonify({"error": "escola, titulo, data_inicio, data_fim obrigatorios"}), 400

    try:
        n_aulas = int(n_aulas)
    except (TypeError, ValueError):
        n_aulas = 1

    from bot.core.portal_factory import get_adapter
    portal = get_adapter("SGE")

    try:
        portal.start()
        ctx = __import__("bot.core.portal_adapter", fromlist=["PortalContext"]).PortalContext(
            escola=escola, turno=turno, turma=turma, trimestre=trimestre,
        )

        if not portal.navigate_to_lesson_plan(ctx):
            AuditLog.log(g.current_user.id, "lesson_plan_navigate", target=escola, status="failed")
            return jsonify({"error": "Nao foi possivel navegar para Plano de Aulas"}), 500

        from bot.core.portal_adapter import LessonPlan
        plan = LessonPlan(
            titulo=titulo,
            data_inicio=data_inicio,
            data_fim=data_fim,
            n_aulas=n_aulas,
        )

        if not portal.create_lesson_plan(plan):
            AuditLog.log(g.current_user.id, "lesson_plan_create", target=titulo, status="failed")
            return jsonify({"error": "Falha ao criar planejamento"}), 500

        pdf_path = data.get("pdf_path", "")
        pdf_url = data.get("pdf_url", "")
        anexo_ok = False

        if pdf_url and not pdf_path:
            try:
                pdf_path = _download_pdf_from_url(pdf_url, titulo)
            except Exception as e:
                AuditLog.log(g.current_user.id, "lesson_plan_pdf_download", target=pdf_url, status="error", details=str(e))
                pdf_path = ""

        if pdf_path and os.path.isfile(pdf_path):
            anexo_ok = portal.upload_lesson_plan_pdf(titulo, pdf_path)

        AuditLog.log(g.current_user.id, "lesson_plan_execute", target=titulo, status="success")
        return jsonify({
            "message": "Plano de aula executado com sucesso",
            "planejamento_criado": True,
            "anexo_enviado": anexo_ok,
        })

    except Exception as e:
        AuditLog.log(g.current_user.id, "lesson_plan_execute", target=escola, status="error", details=str(e))
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            portal.stop()
        except Exception:
            pass
