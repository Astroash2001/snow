"""Structured JSON logs with secret redaction, one rotating file per Snow process.

Logging policy (D-18, D-19): log event names, ids, kinds and durations. Never log what
the user said or what Snow replied; speech text lives only in the event log, which has
retention. Secrets are scrubbed three ways before any line reaches disk (SAFE-09):
by field name, by key-shaped value, and by exact match against every revealed secret.
"""

import logging
import logging.handlers
import os
import re
from typing import Any

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from snow.config.secrets import revealed_secret_values
from snow.config.settings import data_dir

REDACTED = "[REDACTED]"
_MARK = "_snow_handler"
_SENSITIVE_KEY = re.compile(r"api_key|authorization|token|secret|password|cookie", re.I)
_SECRET_SHAPE = re.compile(
    r"(?:xpl_|gsk_|nvapi-|sk-or-|sk_car_)[A-Za-z0-9_\-]{8,}"
    r"|AIza[0-9A-Za-z_\-]{35}"
    r"|Bearer\s+[A-Za-z0-9._\-]+"
)
_MIN_EXACT_LEN = 8  # shorter revealed values would shred ordinary words
_NOISY = ("openai", "httpx", "httpx2", "httpcore", "websockets")


def _scrub(text: str) -> str:
    text = _SECRET_SHAPE.sub(REDACTED, text)
    for value in revealed_secret_values():
        if len(value) >= _MIN_EXACT_LEN:
            text = text.replace(value, REDACTED)
    return text


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return _scrub(value)
    if isinstance(value, dict):
        items: dict[Any, Any] = value  # pyright: ignore[reportUnknownVariableType]
        return {
            k: REDACTED if _SENSITIVE_KEY.search(str(k)) else _clean(v)
            for k, v in items.items()
        }
    if isinstance(value, list | tuple):
        seq: list[Any] = list(value)  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
        return [_clean(v) for v in seq]
    if value is None or isinstance(value, bool | int | float):
        return value
    return _scrub(repr(value))  # unknown objects: JSON would repr them unscrubbed


def redact_secrets(
    _logger: WrappedLogger | None, _method: str, event_dict: EventDict
) -> EventDict:
    return _clean(event_dict)


def _add_process(process: str) -> Processor:
    def add(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
        return {**event_dict, "process": process}

    return add


def _handler_for(process: str) -> logging.Handler:
    logs = data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        logs / f"{process}.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"
    )
    shared: list[Any] = [
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _add_process(process),
        structlog.processors.format_exc_info,  # before redaction: tracebacks echo keys
        redact_secrets,
    ]
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=shared,
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
        )
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            *shared,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
    )
    setattr(handler, _MARK, True)
    return handler


def _bridge_loguru() -> None:
    """Pipecat logs through loguru and dumps LLM context (transcripts) at DEBUG."""
    os.environ["LOGURU_LEVEL"] = "WARNING"
    try:
        from loguru import logger
    except ImportError:
        return
    log = logging.getLogger("pipecat")

    def forward(message: Any) -> None:
        record = message.record
        log.log(record["level"].no, record["message"])

    logger.remove()
    logger.add(forward, level="WARNING", format="{message}")


def configure(process: str) -> None:
    root = logging.getLogger()
    for h in [h for h in root.handlers if getattr(h, _MARK, False)]:
        root.removeHandler(h)
        h.close()
    root.addHandler(_handler_for(process))
    root.setLevel(logging.INFO)
    for name in _NOISY:
        logging.getLogger(name).setLevel(logging.WARNING)
    _bridge_loguru()
