"""Structured, redacting JSON logs (QUAL-03, SAFE-09, D-18)."""

import json
import logging
import logging.handlers
from collections.abc import Iterator
from pathlib import Path

import pytest
import structlog
from loguru import logger as loguru_logger

from snow.config.secrets import Secret
from snow.logging import configure
from tests.conftest import SnowDirs

REDACTED = "[REDACTED]"


@pytest.fixture
def log_file(snow_dirs: SnowDirs) -> Iterator[Path]:
    configure("testproc")
    yield snow_dirs.data / "logs" / "testproc.log"
    root = logging.getLogger()
    for h in list(root.handlers):
        if getattr(h, "_snow_handler", False):
            root.removeHandler(h)
            h.close()
    loguru_logger.remove()


def lines(path: Path) -> list[dict[str, object]]:
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines()]


def test_every_line_is_json_with_the_required_fields(log_file: Path) -> None:
    structlog.get_logger("t").info("turn_started", turn_id="abc")
    logging.getLogger("snow.x").warning("stdlib_event")
    rows = lines(log_file)
    assert len(rows) == 2
    for row in rows:
        assert {"timestamp", "level", "process", "event"} <= row.keys()
        assert row["process"] == "testproc"
    assert rows[0]["event"] == "turn_started" and rows[0]["turn_id"] == "abc"
    assert rows[1]["level"] == "warning"


@pytest.mark.parametrize(
    "key", ["api_key", "Authorization", "token", "client_secret", "password", "cookie"]
)
def test_sensitive_field_names_are_redacted(log_file: Path, key: str) -> None:
    structlog.get_logger("t").info("evt", **{key: "plain-value-1"})
    structlog.get_logger("t").info("evt", nested={key: "plain-value-2"})
    text = log_file.read_text(encoding="utf-8")
    assert "plain-value" not in text
    assert lines(log_file)[0][key] == REDACTED


@pytest.mark.parametrize(
    "secret",
    [
        "gsk_abc123def456ghi789",
        "xpl_abc123def456ghi789",
        "nvapi-abc123def456ghi789",
        "sk-or-abc123def456ghi789",
        "sk_car_abc123def456ghi789",
        "AIza" + "A1b2C3d4E5" * 3 + "xyz12",
        "Bearer eyJhbGciOi.payload-part_1",
    ],
)
def test_key_shaped_substrings_are_scrubbed(log_file: Path, secret: str) -> None:
    structlog.get_logger("t").info(f"calling with {secret} now", detail=[secret])
    logging.getLogger("snow.x").error("provider said %s", secret)
    text = log_file.read_text(encoding="utf-8")
    assert secret not in text
    assert text.count(REDACTED) >= 3


def test_revealed_secret_of_unfamiliar_format_is_scrubbed_by_exact_match(
    log_file: Path,
) -> None:
    value = "unfamiliar-FORMAT-77aa31"
    assert Secret(value).reveal() == value
    structlog.get_logger("t").info(f"echo {value}")
    assert value not in log_file.read_text(encoding="utf-8")


def test_exception_tracebacks_are_scrubbed(log_file: Path) -> None:
    try:
        raise RuntimeError("401 bad key gsk_abc123def456ghi789")
    except RuntimeError:
        logging.getLogger("snow.x").exception("call_failed")
    text = log_file.read_text(encoding="utf-8")
    assert "RuntimeError" in text and "gsk_abc123def456ghi789" not in text


def test_loguru_warning_is_bridged_redacted_and_debug_is_dropped(
    log_file: Path,
) -> None:
    loguru_logger.debug("Generating chat from context: zebra transcript")
    loguru_logger.info("info chatter zebra transcript")
    loguru_logger.warning("pipecat trouble gsk_abc123def456ghi789")
    rows = lines(log_file)
    assert len(rows) == 1
    assert rows[0]["logger"] == "pipecat" and rows[0]["level"] == "warning"
    assert REDACTED in str(rows[0]["event"])
    assert "zebra" not in log_file.read_text(encoding="utf-8")


def test_file_rotates_and_noisy_libraries_are_quiet(log_file: Path) -> None:
    handlers = [
        h
        for h in logging.getLogger().handlers
        if isinstance(h, logging.handlers.RotatingFileHandler)
    ]
    assert len(handlers) == 1
    assert (handlers[0].maxBytes, handlers[0].backupCount) == (5_000_000, 5)
    for name in ("openai", "httpx", "httpcore", "websockets"):
        assert logging.getLogger(name).level == logging.WARNING


def test_configure_twice_does_not_duplicate_lines(log_file: Path) -> None:
    configure("testproc")
    structlog.get_logger("t").info("once")
    assert len(lines(log_file)) == 1
