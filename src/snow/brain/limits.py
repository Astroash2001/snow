"""Free-tier limit handling: header-driven cooldowns, per-day counters (CORE-09, D-27).

One `RateLimiter` lives in the brain process and is shared by every role chain, so
counters are per provider, not per role. A provider that answers "slow down" is skipped
for exactly as long as it said (Groq `retry-after` / `x-ratelimit-reset-*`, OpenRouter
`X-RateLimit-Reset`, Google `retryDelay`, Experiential error codes) and otherwise for a
configured default. Times are naive local datetimes: counters reset at local midnight.
"""

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING, cast

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:
    from snow.brain.config import ChainEntry

_MAX_COOLDOWN_S = 86_400  # a provider cannot park itself for longer than a day
_OVERLOADED_CODES = frozenset({"gateway_overloaded", "unavailable_route"})
_DURATION = re.compile(
    r"(?:(?P<h>\d+(?:\.\d+)?)h)?"
    r"(?:(?P<m>\d+(?:\.\d+)?)m(?!s))?"
    r"(?:(?P<s>\d+(?:\.\d+)?)s)?"
    r"(?:(?P<ms>\d+(?:\.\d+)?)ms)?"
)


class CooldownDefaults(BaseModel):
    """Cooldowns when a provider gives no usable timing; `[limits]` in models.toml."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rate_limit_s: float = 60
    out_of_quota_s: float = 1800
    transient_s: float = 20
    overloaded_s: float = 15


def parse_duration(text: str) -> float:
    """Seconds from `1h2m3.5s`, `2m59.56s`, `7.66s` or `250ms`; ValueError otherwise."""
    m = _DURATION.fullmatch(text.strip())
    if not m or not any(m.groupdict().values()):
        raise ValueError(f"not a duration: {text!r}")
    g = {k: float(v) if v else 0.0 for k, v in m.groupdict().items()}
    return g["h"] * 3600 + g["m"] * 60 + g["s"] + g["ms"] / 1000


def _to_seconds(text: str) -> float:
    """Bare seconds (`retry-after: 12`) or a duration string."""
    try:
        return float(text)
    except ValueError:
        return parse_duration(text)


def _find(body: object, key: str) -> object | None:
    """First value stored under `key` at any depth (provider error bodies differ)."""
    if isinstance(body, dict):
        d = cast("dict[str, object]", body)
        if key in d:
            return d[key]
        children = list(d.values())
    elif isinstance(body, list):
        children = cast("list[object]", body)
    else:
        return None
    for child in children:
        if (found := _find(child, key)) is not None:
            return found
    return None


def next_midnight(now: datetime) -> datetime:
    return (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)


@dataclass
class _Usage:
    day: date
    requests: int = 0
    tokens: int = 0


class RateLimiter:
    def __init__(
        self,
        now: Callable[[], datetime] = datetime.now,
        defaults: CooldownDefaults | None = None,
    ) -> None:
        self._now = now
        self.defaults = defaults or CooldownDefaults()
        self._usage: dict[str, _Usage] = {}
        self._cool: dict[str, datetime] = {}

    # shortcut: counters restart at zero when the brain restarts; provider 429s
    # re-teach the limits. Persist them only if double-spend is ever observed.
    def _today(self, provider: str) -> _Usage:
        today = self._now().date()
        usage = self._usage.get(provider)
        if usage is None or usage.day != today:
            usage = self._usage[provider] = _Usage(today)
        return usage

    def record_success(
        self,
        provider: str,
        entry: "ChainEntry",
        usage_tokens: int | None,
        text_len: int,
    ) -> None:
        """One served request; tokens from the usage chunk, else len(text)/4."""
        usage = self._today(provider)
        usage.requests += 1
        usage.tokens += usage_tokens if usage_tokens is not None else text_len // 4

    def record_failure(
        self,
        provider: str,
        reason: str,
        headers: Mapping[str, str],
        body: object,
    ) -> datetime | None:
        """Start a cooldown for `provider`; returns its end (None: entry-specific)."""
        if reason == "config_error":  # a bad parameter, not a provider-wide limit
            return None
        now = self._now()
        h = {k.lower(): v for k, v in headers.items()}
        code = _find(body, "code")
        if code == "key_daily_cap":
            until = next_midnight(now)
        else:
            seconds = self._hinted(h, body, now)
            if seconds is None:
                seconds = self._default(reason, code)
            until = now + timedelta(seconds=min(seconds, _MAX_COOLDOWN_S))
        self._cool[provider] = max(until, self._cool.get(provider, until))
        return until

    def _default(self, reason: str, code: object) -> float:
        d = self.defaults
        if code in _OVERLOADED_CODES:
            return d.overloaded_s
        if reason == "out_of_quota":
            return d.out_of_quota_s
        if reason in ("rate_limit", "bad_key"):
            return d.rate_limit_s
        return d.transient_s  # service_error, timeout, unreachable

    @staticmethod
    def _hinted(h: dict[str, str], body: object, now: datetime) -> float | None:
        """Seconds the provider asked for (first source wins), None if silent."""
        sources: list[Callable[[], float | None]] = [
            lambda: _to_seconds(h["retry-after"]) if "retry-after" in h else None,
            # Groq: only the window that is actually exhausted.
            lambda: max(
                (
                    _to_seconds(h[f"x-ratelimit-reset-{k}"])
                    for k in ("requests", "tokens")
                    if f"x-ratelimit-reset-{k}" in h
                    and h.get(f"x-ratelimit-remaining-{k}", "0").strip() == "0"
                ),
                default=None,
            ),
            # OpenRouter: epoch milliseconds.
            lambda: (
                float(h["x-ratelimit-reset"]) / 1000 - now.timestamp()
                if "x-ratelimit-reset" in h
                else None
            ),
            # Google: body retryDelay such as "13s".
            lambda: (
                _to_seconds(delay)
                if isinstance(delay := _find(body, "retryDelay"), str)
                else None
            ),
        ]
        for source in sources:
            try:
                seconds = source()
            except ValueError:
                continue
            if seconds is not None and seconds > 0:
                return seconds
        return None

    def cooling_until(self, provider: str, entry: "ChainEntry") -> datetime | None:
        """When `provider` is usable again; local midnight once the entry cap is hit."""
        now = self._now()
        until = self._cool.get(provider)
        if until is not None and until <= now:
            del self._cool[provider]
            until = None
        cap = entry.daily_request_cap
        if cap is not None and self._today(provider).requests >= cap:
            until = max(until or now, next_midnight(now))
        return until

    def snapshot(self, provider: str) -> tuple[int, int, datetime | None]:
        """(requests_today, tokens_today, cooling_until) for the health rows."""
        usage = self._today(provider)
        until = self._cool.get(provider)
        if until is not None and until <= self._now():
            del self._cool[provider]
            until = None
        return usage.requests, usage.tokens, until
