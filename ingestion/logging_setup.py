"""Logging configuration for the ingestion routine.

A single :func:`configure_logging` call wires up a console handler and, when a
log directory is configured, a rotating file handler. Centralising this here
keeps every entry point (CLI commands, the eventual scheduler runner) emitting
the same structured lines — which the acceptance criteria require to carry the
run's success/failure, duration, team, and data volume.
"""

import logging
import os
from logging.config import dictConfig

from ingestion.config import settings

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s | %(message)s"
_configured = False


def configure_logging(
    level: str | None = None, log_dir: str | None = None
) -> None:
    """Idempotently configure root logging.

    ``level`` and ``log_dir`` fall back to the corresponding settings so a bare
    ``configure_logging()`` is enough in normal use.
    """
    global _configured
    if _configured:
        return

    resolved_level = (level or settings.log_level).upper()
    resolved_dir = log_dir if log_dir is not None else settings.log_dir

    handlers: dict[str, dict] = {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stderr",
        }
    }

    if resolved_dir:
        os.makedirs(resolved_dir, exist_ok=True)
        handlers["file"] = {
            "class": "logging.handlers.RotatingFileHandler",
            "formatter": "default",
            "filename": os.path.join(resolved_dir, "ingestion.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 7,
            "encoding": "utf-8",
        }

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {"default": {"format": _LOG_FORMAT}},
            "handlers": handlers,
            "root": {"level": resolved_level, "handlers": list(handlers)},
        }
    )

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Convenience accessor so callers don't import :mod:`logging` directly."""
    return logging.getLogger(name)
