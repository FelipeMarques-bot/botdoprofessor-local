import os
import tempfile
from flask import Blueprint, request, jsonify, g
from bot.security.auth import require_auth
from bot.models.audit import AuditLog

image_grades_bp = Blueprint("image_grades", __name__, url_prefix="/api/grades")


@image_grades_bp.route("/from-image", methods=["POST"])
@require_auth
def extract_grades_from_image():
    """Extract grades from an uploaded image using AI vision.

    Accepts:
        - multipart/form-data with field "image" (file upload)
        - JSON with field "image_url" (URL to download image from)

    Returns:
        JSON with extracted grades array.
    """
    from bot.utils.image_grade_extractor import extract_grades_from_image as _extract, is_available

    if not is_available():
        AuditLog.log(g.current_user.id, "image_grades", status="error", details="AI vision not available")
        return jsonify({
            "error": "IA visual nao configurada",
            "hint": "Configure GEMINI_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY ou Ollama",
        }), 503

    image_bytes = None

    if request.content_type and "multipart" in request.content_type:
        if "image" not in request.files:
            return jsonify({"error": "Campo 'image' obrigatorio no form"}), 400
        file = request.files["image"]
        if not file.filename:
            return jsonify({"error": "Nenhum arquivo selecionado"}), 400
        ext = os.path.splitext(file.filename)[1].lower()
        if ext not in (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff"):
            return jsonify({"error": f"Formato nao suportado: {ext}. Use JPG, PNG, BMP ou WEBP"}), 400
        image_bytes = file.read()
    else:
        data = request.get_json() or {}
        image_url = data.get("image_url", "")
        if not image_url:
            return jsonify({"error": "Envie uma imagem (multipart) ou informe image_url"}), 400
        try:
            import urllib.request
            req = urllib.request.Request(image_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                image_bytes = resp.read()
        except Exception as e:
            return jsonify({"error": f"Falha ao baixar imagem: {e}"}), 400

    if not image_bytes:
        return jsonify({"error": "Imagem vazia"}), 400

    result = _extract(image_bytes, logger=lambda m: None)

    if result.get("error"):
        AuditLog.log(g.current_user.id, "image_grades", status="error", details=result["error"])
        return jsonify(result), 500

    AuditLog.log(
        g.current_user.id, "image_grades",
        status="success",
        details=f"{result.get('total_encontrados', 0)} alunos extraidos",
    )

    return jsonify({
        "alunos": result.get("alunos", []),
        "total_encontrados": result.get("total_encontrados", 0),
        "confianca": result.get("confianca", "desconhecida"),
        "observacoes": result.get("observacoes", ""),
    })
