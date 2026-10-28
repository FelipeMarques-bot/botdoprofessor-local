"""Configuracao unica de logging com rotacao e redacao de segredos."""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional, Union

from bot.security.redaction import redact_text


class RedactingFormatter(logging.Formatter):
    """Formata e redige a mensagem final, incluindo tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        return redact_text(super().format(record))


def setup_logging(
    name: str = "botdoprofessor",
    log_file: Optional[Union[str, Path]] = None,
    level: Union[int, str] = logging.INFO,
    console: bool = False,
) -> logging.Logger:
    """Configura um logger de arquivo idempotente.

    Se `log_file` nao for informado, usa ~/.bot_local/logs/app.log.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(level)
    logger.propagate = False

    formatter = RedactingFormatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    path = Path(log_file) if log_file else Path.home() / ".bot_local" / "logs" / "app.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        from logging.handlers import RotatingFileHandler

        file_handler = RotatingFileHandler(
            path,
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
            delay=True,
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        console = True

    if console:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)

    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    return logger
