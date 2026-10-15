"""`snow setup`: hidden key entry into the in-memory keyring (SAFE-09, D-24, D-25)."""

import builtins
import getpass

import pytest

from snow import cli
from snow.config import setup
from snow.config.secrets import KNOWN_KEYS, get_secret
from tests.conftest import InMemoryKeyring

GROQ_KEY = "gsk_SETUPTEST0123456789"


def _answers(monkeypatch: pytest.MonkeyPatch, answers: dict[str, str]) -> list[str]:
    """Feed getpass by the label in its prompt; unlisted keys get Enter."""
    asked: list[str] = []

    def fake(prompt: str = "", stream: object = None) -> str:
        asked.append(prompt)
        return next((v for label, v in answers.items() if prompt.startswith(label)), "")

    monkeypatch.setattr(getpass, "getpass", fake)
    return asked


def test_store_then_read_and_enter_skips(
    memory_keyring: InMemoryKeyring,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    asked = _answers(monkeypatch, {"Groq": GROQ_KEY})
    assert setup.main([]) == 0
    assert len(asked) == len(KNOWN_KEYS)
    secret = get_secret("groq")
    assert secret is not None and secret.reveal() == GROQ_KEY
    assert get_secret("cartesia") is None
    assert GROQ_KEY not in capsys.readouterr().out


def test_status_names_state_and_never_the_value(
    memory_keyring: InMemoryKeyring,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    memory_keyring.set_password("snow", "groq", GROQ_KEY)
    assert setup.main(["--status"]) == 0
    out = capsys.readouterr().out
    assert "Groq: configured" in out
    assert "Cartesia: not configured" in out
    assert len(out.splitlines()) == len(KNOWN_KEYS)
    assert GROQ_KEY not in out and "gsk_" not in out and str(len(GROQ_KEY)) not in out


def test_clear_removes_the_key(
    memory_keyring: InMemoryKeyring, capsys: pytest.CaptureFixture[str]
) -> None:
    memory_keyring.set_password("snow", "groq", GROQ_KEY)
    assert setup.main(["--clear", "groq"]) == 0
    assert get_secret("groq") is None
    assert setup.main(["--clear", "groq"]) == 0  # already absent is fine
    capsys.readouterr()


def test_only_prompts_for_one_key(
    memory_keyring: InMemoryKeyring, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked = _answers(monkeypatch, {"Groq": GROQ_KEY})
    assert setup.main(["--only", "groq"]) == 0
    assert len(asked) == 1 and get_secret("groq") is not None


def test_unknown_name_is_rejected(memory_keyring: InMemoryKeyring) -> None:
    with pytest.raises(SystemExit):
        setup.main(["--only", "nope"])


@pytest.mark.parametrize(("reply", "stored"), [("n", False), ("y", True)])
def test_wrong_prefix_asks_and_never_echoes_the_value(
    memory_keyring: InMemoryKeyring,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    reply: str,
    stored: bool,
) -> None:
    _answers(monkeypatch, {"Groq": "wrongprefix-VALUE-123"})
    monkeypatch.setattr(builtins, "input", lambda _p="": reply)
    setup.main(["--only", "groq"])
    out = capsys.readouterr().out
    assert "gsk_" in out  # the expected prefix is named
    assert "wrongprefix" not in out
    assert (get_secret("groq") is not None) is stored


def test_cli_dispatches_setup(
    memory_keyring: InMemoryKeyring, capsys: pytest.CaptureFixture[str]
) -> None:
    assert cli.main(["setup", "--status"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert len(lines) == len(KNOWN_KEYS)
    assert all(ln.endswith("configured") for ln in lines)
