"""API keys live only in Windows Credential Manager (SAFE-09, D-24)."""

from dataclasses import dataclass

import keyring
import keyring.errors

KEYRING_SERVICE = "snow"


@dataclass(frozen=True)
class KeySpec:
    name: str  # keyring username
    label: str
    prefix_hint: str  # expected start of a valid key; only a typo guard


KNOWN_KEYS: tuple[KeySpec, ...] = (
    KeySpec("experiential", "Experiential Labs", "xpl_"),
    KeySpec("groq", "Groq", "gsk_"),
    KeySpec("google", "Google AI Studio", "AIza"),
    KeySpec("nvidia", "NVIDIA NIM", "nvapi-"),
    KeySpec("openrouter", "OpenRouter", "sk-or-"),
    KeySpec("cartesia", "Cartesia", "sk_car_"),
)

# Every value that ever left the keyring in this process; log redaction scrubs these by
# exact match so a key in an unfamiliar format is still caught (SAFE-09).
_revealed: set[str] = set()


def revealed_secret_values() -> frozenset[str]:
    return frozenset(_revealed)


class Secret:
    """Holds a secret so it cannot leak through repr, str or f-strings."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        _revealed.add(self._value)
        return self._value

    def __repr__(self) -> str:
        return "Secret('***')"

    __str__ = __repr__


def get_secret(key_name: str) -> Secret | None:
    value = keyring.get_password(KEYRING_SERVICE, key_name)
    return Secret(value) if value else None


def set_secret(name: str, value: str) -> None:
    keyring.set_password(KEYRING_SERVICE, name, value)
    _revealed.add(value)


def delete_secret(name: str) -> None:
    try:
        keyring.delete_password(KEYRING_SERVICE, name)
    except keyring.errors.PasswordDeleteError:
        pass  # already absent
