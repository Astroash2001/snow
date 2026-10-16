"""`snow dev probe-models [--json] [--latency N]`: gateway and latency probe.

D-29: list each keyed provider's models, resolve empty `model` IDs from the entry's
`match` glob, check streaming, tool calling and (vision role) image input. D-30: time to
first token for the two fast-role candidates. Prompts are synthetic with no user
content, so they are safe for the untrusted providers too. Keys flow only through
`get_secret` into the client; the report holds IDs, booleans and timings, never a key
or an error body (T-01-35).
"""

import argparse
import asyncio
import base64
import fnmatch
import json
import math
import re
import statistics
import struct
import sys
import time
import zlib
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

import httpx2
from openai import APIStatusError, AsyncOpenAI, OpenAIError
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionToolParam

from snow.brain.config import ChainEntry, ModelsConfig
from snow.config.secrets import Secret, get_secret
from snow.config.settings import load_config

CATALOG_URL = "https://api.experientiallabs.ai/api/models"  # keyless
LATENCY_TARGETS = (
    ("groq", "openai/gpt-oss-120b"),
    ("experiential", "deepseek-v4-flash"),
)
_PROMPT: list[ChatCompletionMessageParam] = [
    {"role": "user", "content": "Reply with OK"}
]
_PING: ChatCompletionToolParam = {
    "type": "function",
    "function": {
        "name": "ping",
        "description": "Connectivity check.",
        "parameters": {"type": "object", "properties": {}},
    },
}
_MAX_TOKENS = 64  # reasoning models spend tokens thinking before the first visible text
_MAX_CANDIDATES = (
    3  # how many ranked glob matches to try when an entry `requires` tools
)


def _png() -> str:
    """An 8x8 solid red PNG as a data URL (no image file needed)."""

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + b"\xff\x00\x00" * 8 for _ in range(8))
    raw = (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 8, 8, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )
    return "data:image/png;base64," + base64.b64encode(raw).decode()


@dataclass
class EntryReport:
    role: str
    provider: str
    configured: str  # model ID in models.toml ("" when it needs resolving)
    model: str  # confirmed ID ("" when unresolved)
    listed: bool
    stream: bool | None = None
    tools: bool | None = None
    vision: bool | None = None  # None = not checked (non-vision role)
    ttft_s: float | None = None
    note: str = ""


Clients = dict[str, AsyncOpenAI]


def _why(exc: Exception) -> str:
    """Failure kind only: error bodies can echo request content (T-01-20)."""
    if isinstance(exc, APIStatusError):
        return f"{type(exc).__name__} {exc.status_code}"
    return type(exc).__name__


def _natural(model_id: str) -> list[tuple[int, int, str]]:
    return [
        (1, int(p), "") if p.isdigit() else (0, 0, p)
        for p in re.split(r"(\d+)", model_id)
        if p
    ]


def rank_matches(pattern: str, ids: list[str]) -> list[str]:
    """IDs matching the glob, highest version first."""
    return sorted(fnmatch.filter(ids, pattern), key=_natural, reverse=True)


def _body(entry: ChainEntry | None) -> dict[str, Any]:
    params = entry.params if entry else {}
    dropped = entry.drop_params if entry else []
    return {k: v for k, v in params.items() if k not in dropped}


async def check_stream(
    client: AsyncOpenAI, model: str, extra: dict[str, Any]
) -> tuple[bool, float | None, str]:
    """Streaming chat; returns (ok, seconds to first text, failure kind)."""
    start = time.perf_counter()
    ttft: float | None = None
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=_PROMPT,
            max_tokens=_MAX_TOKENS,
            stream=True,
            extra_body=extra,
        )
        async for chunk in stream:
            if ttft is None and chunk.choices and chunk.choices[0].delta.content:
                ttft = time.perf_counter() - start
    except OpenAIError as e:
        return False, ttft, _why(e)
    return ttft is not None, ttft, "" if ttft is not None else "no text"


async def check_tools(
    client: AsyncOpenAI, model: str, extra: dict[str, Any]
) -> tuple[bool, str]:
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Call the ping function."}],
            tools=[_PING],
            tool_choice="required",
            max_tokens=_MAX_TOKENS,
            extra_body=extra,
        )
    except OpenAIError as e:
        return False, _why(e)
    return bool(resp.choices and resp.choices[0].message.tool_calls), ""


async def check_vision(
    client: AsyncOpenAI, model: str, extra: dict[str, Any]
) -> tuple[bool, str]:
    content: Any = [
        {"type": "text", "text": "What colour is this image? One word."},
        {"type": "image_url", "image_url": {"url": _png()}},
    ]
    try:
        await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": content}],
            max_tokens=_MAX_TOKENS,
            extra_body=extra,
        )
    except OpenAIError as e:
        return False, _why(e)
    return True, ""


async def fetch_catalog(http: httpx2.AsyncClient) -> dict[str, dict[str, Any]]:
    """Experiential's keyless catalog: slug -> input modalities and params."""
    try:
        data = (await http.get(CATALOG_URL, timeout=20)).json()
        out: dict[str, dict[str, Any]] = {}
        for item in data["models"]:
            m = item["model"]
            info = {
                "input": m.get("input_modalities", []),
                "params": sorted(
                    k for k, v in m.get("supported_params", {}).items() if v
                ),
            }
            out[m["slug"]] = info
        return out
    except (httpx2.HTTPError, ValueError, KeyError, TypeError):
        return {}


async def _list_ids(client: AsyncOpenAI) -> list[str]:
    ids: list[str] = []
    async for m in client.models.list():
        # Google returns "models/gemini-..." ; chat requests accept the bare ID.
        ids.append(m.id.removeprefix("models/"))
    return ids


async def probe(
    models: ModelsConfig,
    *,
    secrets: Callable[[str], Secret | None] = get_secret,
    client_factory: Callable[..., AsyncOpenAI] = AsyncOpenAI,
    http: httpx2.AsyncClient | None = None,
    latency_n: int = 0,
) -> dict[str, Any]:
    clients: Clients = {}
    providers: dict[str, dict[str, Any]] = {}
    listing: dict[str, list[str]] = {}
    for name, prov in models.providers.items():
        secret = secrets(prov.key_name)
        if secret is None:
            providers[name] = {"status": "skipped: no key", "models": 0}
            continue
        client = client_factory(
            base_url=prov.base_url, api_key=secret.reveal(), max_retries=0, timeout=30
        )
        clients[name] = client
        try:
            listing[name] = await _list_ids(client)
            providers[name] = {"status": "ok", "models": len(listing[name])}
        except OpenAIError as e:
            listing[name] = []
            providers[name] = {"status": f"failed: {_why(e)}", "models": 0}

    own_http = http is None
    http = http or httpx2.AsyncClient()
    try:
        catalog = await fetch_catalog(http) if "experiential" in clients else {}
    finally:
        if own_http:
            await http.aclose()

    cache: dict[tuple[str, str], tuple[bool, bool, float | None]] = {}
    entries: list[EntryReport] = []

    async def stream_and_tools(
        prov: str, model: str, entry: ChainEntry
    ) -> tuple[bool, bool, float | None, str]:
        key = (prov, model)
        if key not in cache:
            extra = _body(entry)
            ok_s, ttft, why_s = await check_stream(clients[prov], model, extra)
            ok_t, why_t = await check_tools(clients[prov], model, extra)
            cache[key] = (ok_s, ok_t, ttft)
            return ok_s, ok_t, ttft, "; ".join(w for w in (why_s, why_t) if w)
        return (*cache[key], "")

    for role_name, role in models.roles.items():
        for entry in role.chain:
            prov = entry.provider
            base = EntryReport(role_name, prov, entry.model, entry.model, False)
            if prov not in clients or not listing.get(prov):
                base.note = (
                    providers[prov]["status"] if prov in providers else "no provider"
                )
                entries.append(base)
                continue
            ids = listing[prov]
            if entry.model:
                candidates = [entry.model]
                base.listed = entry.model in ids
            elif entry.match:
                candidates = rank_matches(entry.match, ids)[:_MAX_CANDIDATES]
                base.listed = bool(candidates)
                if not candidates:
                    base.note = f"no model matches {entry.match}"
                    entries.append(base)
                    continue
            else:
                base.note = "no model and no match"
                entries.append(base)
                continue
            for model in candidates:
                base.model = model
                (
                    base.stream,
                    base.tools,
                    base.ttft_s,
                    base.note,
                ) = await stream_and_tools(prov, model, entry)
                # A glob entry that needs tools keeps searching down the ranked list.
                if "tools" not in entry.requires or base.tools:
                    break
            if role_name == "vision" and base.stream:
                base.vision, why = await check_vision(
                    clients[prov], base.model, _body(entry)
                )
                base.note = "; ".join(x for x in (base.note, why) if x)
            if not entry.model and not base.stream:
                base.model = ""  # nothing confirmed: leave unresolved
            if prov == "experiential" and base.model in catalog:
                base.note = "; ".join(
                    x
                    for x in (
                        base.note,
                        f"catalog input={','.join(catalog[base.model]['input'])}",
                    )
                    if x
                )
            entries.append(base)

    report: dict[str, Any] = {
        "providers": providers,
        "entries": [asdict(e) for e in entries],
    }
    if latency_n:
        report["latency"] = await _latency(models, clients, latency_n)
    for client in clients.values():
        await client.close()
    return report


async def _latency(models: ModelsConfig, clients: Clients, n: int) -> dict[str, Any]:
    fast = {(e.provider, e.model): e for e in models.roles["fast"].chain}
    runs: dict[str, list[float]] = {f"{p}/{m}": [] for p, m in LATENCY_TARGETS}
    fails: dict[str, int] = {k: 0 for k in runs}
    for _ in range(n):
        for prov, model in LATENCY_TARGETS:
            label = f"{prov}/{model}"
            if prov not in clients:
                continue
            ok, ttft, _ = await check_stream(
                clients[prov], model, _body(fast.get((prov, model)))
            )
            if ok and ttft is not None:
                runs[label].append(ttft)
            else:
                fails[label] += 1
    out: dict[str, Any] = {}
    for label, vals in runs.items():
        if not vals:
            out[label] = {"n": 0, "errors": fails[label], "p50_s": None, "p95_s": None}
            continue
        vals.sort()
        p95 = vals[max(0, math.ceil(0.95 * len(vals)) - 1)]  # nearest rank
        out[label] = {
            "n": len(vals),
            "errors": fails[label],
            "p50_s": round(statistics.median(vals), 3),
            "p95_s": round(p95, 3),
        }
    return out


def _table(report: dict[str, Any]) -> str:
    lines = ["providers"]
    for name, p in report["providers"].items():
        lines.append(f"  {name:<13} {p['status']} ({p['models']} models)")
    lines.append("entries (role provider model stream tools vision ttft)")
    for e in report["entries"]:
        flags = " ".join(
            "-" if e[k] is None else ("yes" if e[k] else "NO")
            for k in ("stream", "tools", "vision")
        )
        ttft = "-" if e["ttft_s"] is None else f"{e['ttft_s']:.2f}s"
        model = e["model"] or "(unresolved)"
        note = f"  [{e['note']}]" if e["note"] else ""
        lines.append(
            f"  {e['role']:<7} {e['provider']:<13} {model} | {flags} | {ttft}{note}"
        )
    for label, v in report.get("latency", {}).items():
        lines.append(f"latency {label}: {v}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="snow dev probe-models")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument(
        "--latency",
        nargs="?",
        type=int,
        const=10,
        default=0,
        metavar="N",
        help="time to first token over N runs for the fast candidates (default 10)",
    )
    args = ap.parse_args(argv)
    report = asyncio.run(
        probe(load_config("models.toml", ModelsConfig), latency_n=args.latency)
    )
    print(json.dumps(report, indent=2) if args.json else _table(report))
    keyed = any(p["status"] != "skipped: no key" for p in report["providers"].values())
    if not keyed:
        print("snow: no provider key stored (run `snow setup`)", file=sys.stderr)
    return 0 if keyed else 1
