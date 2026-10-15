"""Skeleton JSON-line logger. Plan 01-11 swaps in structlog with redaction.

Log event names, ids and error kinds only, never transcript or reply text.
"""

import json
import logging
import time

from snow.config.settings import data_dir

_MARK = "_snow_handler"


class _JsonFormatter(logging.Formatter):
    def __init__(self, process: str) -> None:
        super().__init__()
        self._process = process

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps(
            {
                "ts": time.time(),
                "level": record.levelname,
                "process": self._process,
                "logger": record.name,
                "msg": record.getMessage(),
            }
        )


def configure(process: str) -> None:
    logs = data_dir() / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    for h in [h for h in root.handlers if getattr(h, _MARK, False)]:
        root.removeHandler(h)
        h.close()
    handler = logging.FileHandler(logs / f"{process}.log", encoding="utf-8")
    handler.setFormatter(_JsonFormatter(process))
    setattr(handler, _MARK, True)
    root.addHandler(handler)
    root.setLevel(logging.INFO)
