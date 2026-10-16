"""Typed models.toml (CORE-04). Extras are forbidden: no key fields."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, model_validator

from snow.brain.limits import CooldownDefaults


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
    match: str = ""  # glob the model probe resolves into `model` (plan 01-17)
    requires: list[str] = []
    daily_request_cap: int | None = None


class Role(_Strict):
    chain: list[ChainEntry]
    ttft_timeout_s: float = 6.0  # no first token by then counts as a failure


class ModelsConfig(_Strict):
    providers: dict[str, Provider]
    roles: dict[Literal["brain", "fast", "vision"], Role]
    limits: CooldownDefaults = CooldownDefaults()  # optional [limits] table

    @model_validator(mode="after")
    def _chains_use_known_providers(self) -> Self:
        for role in self.roles.values():
            for entry in role.chain:
                if entry.provider not in self.providers:
                    raise ValueError(f"unknown provider {entry.provider!r}")
        return self
