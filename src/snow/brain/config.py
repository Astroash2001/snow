"""Typed models.toml / persona.toml (CORE-04). Extras are forbidden: no key fields."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Provider(_Strict):
    label: str
    base_url: str
    key_name: str
    trust: Literal["trusted", "untrusted"]


class ChainEntry(_Strict):
    provider: str
    model: str
    params: dict[str, object] = {}
    drop_params: list[str] = []


class Role(_Strict):
    chain: list[ChainEntry]


class ModelsConfig(_Strict):
    providers: dict[str, Provider]
    roles: dict[Literal["brain", "fast", "vision"], Role]

    @model_validator(mode="after")
    def _chains_use_known_providers(self) -> Self:
        for role in self.roles.values():
            for entry in role.chain:
                if entry.provider not in self.providers:
                    raise ValueError(f"unknown provider {entry.provider!r}")
        return self


class PersonaConfig(_Strict):
    system_prompt: str
