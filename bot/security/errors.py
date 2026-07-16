import logging
import time
import traceback
from flask import Flask, request, jsonify
from bot.security.crypto import sanitize_log

log = logging.getLogger(__name__)


class BotError(Exception):
    def __init__(self, message: str, code: str = "BOT_ERROR", status: int = 500):
        self.message = message
        self.code = code
        self.status = status
        super().__init__(message)


class LicenseExpiredError(BotError):
    def __init__(self):
        super().__init__("Licenca expirada", "LICENSE_EXPIRED", 403)


class LicenseInvalidError(BotError):
    def __init__(self, detail: str = ""):
        super().__init__(f"Licenca invalida: {detail}", "LICENSE_INVALID", 403)


class PortalNotSupportedError(BotError):
    def __init__(self, portal: str):
        super().__init__(f"Portal nao suportado: {portal}", "PORTAL_UNSUPPORTED", 400)


class LoginFailedError(BotError):
    def __init__(self):
        super().__init__("Falha no login do portal", "LOGIN_FAILED", 401)


class NavigationError(BotError):
    def __init__(self, detail: str = ""):
        super().__init__(f"Erro de navegacao: {detail}", "NAVIGATION_ERROR", 500)


class GradeFillError(BotError):
    def __init__(self, aluno: str):
        super().__init__(f"Falha ao preencher nota de {aluno}", "GRADE_FILL_ERROR", 500)


def register_error_handlers(app: Flask):
    @app.errorhandler(BotError)
    def handle_bot_error(e: BotError):
        log.warning("BotError [%s]: %s", e.code, e.message)
        return jsonify({"error": e.message, "code": e.code}), e.status

    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify({"error": "Recurso nao encontrado", "code": "NOT_FOUND"}), 404

    @app.errorhandler(500)
    def handle_internal_error(e):
        log.error("Internal error: %s", traceback.format_exc())
        return jsonify({"error": "Erro interno do servidor", "code": "INTERNAL_ERROR"}), 500

    @app.before_request
    def log_request():
        request._start_time = time.time()

    @app.after_request
    def log_response(response):
        duration = time.time() - getattr(request, "_start_time", time.time())
        status = response.status_code
        log_data = {
            "method": request.method,
            "path": request.path,
            "status": status,
            "duration_ms": round(duration * 1000, 1),
            "ip": request.remote_addr,
        }
        if status >= 500:
            log.error("REQUEST %s", sanitize_log(log_data))
        elif status >= 400:
            log.warning("REQUEST %s", sanitize_log(log_data))
        else:
            log.info("REQUEST %s", sanitize_log(log_data))
        return response
