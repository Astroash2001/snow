"""API keys live only in Windows Credential Manager (SAFE-09, D-24)."""

import keyring

KEYRING_SERVICE = "snow"


class Secret:
    """Holds a secret so it cannot leak through repr, str or f-strings."""

    __slots__ = ("_value",)

    def __init__(self, value: str) -> None:
        self._value = value

    def reveal(self) -> str:
        return self._value

    def __repr__(self) -> str:
        return "Secret('***')"

    __str__ = __repr__


def get_secret(key_name: str) -> Secret | None:
    value = keyring.get_password(KEYRING_SERVICE, key_name)
    return Secret(value) if value else None
