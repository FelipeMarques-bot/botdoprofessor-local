from flask import Blueprint, request, jsonify, send_from_directory
from bot.payment.service import PaymentService

payment_bp = Blueprint("payment", __name__, url_prefix="/api/payment")
webhook_bp = Blueprint("webhook", __name__, url_prefix="/api/webhook")

_service = PaymentService()


@payment_bp.route("/create", methods=["POST"])
def create_payment():
    data = request.get_json() or {}
    plan = data.get("plan", "")
    name = data.get("name", "")
    email = data.get("email", "")
    cpf = data.get("cpf", "")
    method = data.get("payment_method", "card")

    if not all([plan, name, email, cpf]):
        return jsonify({"error": "plan, name, email e cpf sao obrigatorios"}), 400

    result = _service.create_preference(plan, name, email, cpf, method)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@payment_bp.route("/verify/<reference>", methods=["GET"])
def verify_payment(reference):
    result = _service.verify_manual_payment(reference)
    return jsonify(result)


@webhook_bp.route("/mercadopago", methods=["POST"])
def mercadopago_webhook():
    data = request.get_json() or {}
    result = _service.handle_webhook(data)
    return jsonify(result)
