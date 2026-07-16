import os
import uuid
import tempfile
from datetime import datetime
from flask import Blueprint, request, jsonify, g
from bot.security.auth import require_auth
from bot.models.audit import AuditLog

lesson_plan_bp = Blueprint("lesson_plan", __name__, url_prefix="/api/lesson-plan")


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

    from bot.core.portal_factory import PortalFactory
    portal = PortalFactory.create("SGE")

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
        anexo_ok = False
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
