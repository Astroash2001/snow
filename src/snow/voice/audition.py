"""`snow dev audition-voices`: hear candidate voices, write the user's pick (D-05).

A developer tool. It speaks `audition_line` from tts.toml (never a Snow reply), asks
before spending Cartesia credits, and rewrites only the voice lines it was asked to.
Audio is played from memory and never written anywhere; the microphone is never
opened. Every clip it writes carries a consent tag; one without it is refused (T-01-50).
"""

import argparse
import asyncio
import json
import re
import tomllib
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

import httpx2
import numpy as np

from snow.config.secrets import Secret, get_secret
from snow.config.settings import config_dir
from snow.voice.tts.base import EngineError, Samples
from snow.voice.tts.cartesia import CartesiaEngine
from snow.voice.tts.config import (
    CONSENTS,
    CartesiaConfig,
    Mood,
    TtsConfig,
    VoiceClip,
)
from snow.voice.tts.pocket import PocketEngine

EMOTIONS = ("content", "neutral")  # each Cartesia candidate is heard in both
_PAGES = 5  # at most 500 stock voices are read
_HTTP_TIMEOUT_S = 10.0

Speech = Coroutine[Any, Any, Samples]
CartesiaSynth = Callable[[str, str], Speech]  # (voice id, emotion)
PocketSynth = Callable[[str], Coroutine[Any, Any, tuple[Samples, int]]]  # (clip path)


def _play(samples: Samples, rate: int) -> None:
    import sounddevice as sd  # noqa: PLC0415 - only a real listening session needs it

    sd.play(samples, rate)  # pyright: ignore[reportUnknownMemberType]
    sd.wait()  # pyright: ignore[reportUnknownMemberType]


@dataclass
class Tools:
    """Everything that touches the user or the world, so tests can fake it."""

    ask: Callable[[str], str] = input
    say: Callable[[str], None] = print
    play: Callable[[Samples, int], None] = _play
    secret: Callable[[str], Secret | None] = get_secret
    transport: httpx2.AsyncBaseTransport | None = None
    cartesia_voice: CartesiaSynth | None = None  # None: real Cartesia synthesis
    pocket_voice: PocketSynth | None = None  # None: the real Pocket TTS engine


def set_line(text: str, section: str, key: str, value: str) -> str:
    """Replace the `key = ...` line inside `[section]`, touching no other line. The
    old line's trailing comment goes with it."""
    lines = text.splitlines(keepends=True)
    inside = False
    for i, line in enumerate(lines):
        head = line.strip()
        if head.startswith("["):
            inside = head == f"[{section}]"
        elif inside and re.match(rf"{re.escape(key)}\s*=", head):
            end = line[len(line.rstrip("\r\n")) :]
            lines[i] = f"{key} = {value}{end}"
            return "".join(lines)
    raise ValueError(f"[{section}] has no '{key} =' line to rewrite")


def _clip_value(clip: VoiceClip) -> str:
    return f"{{ path = {json.dumps(clip.path)}, consent = {json.dumps(clip.consent)} }}"


def shortlist(
    voices: list[dict[str, Any]], names: list[str], limit: int
) -> list[dict[str, Any]]:
    """English male stock voices: the research shortlist first, then British-sounding
    ones, then the rest in Cartesia's order."""
    wanted = {n.lower() for n in names}
    men = [
        v
        for v in voices
        if str(v.get("language", "")).startswith("en")
        and v.get("gender") == "masculine"
    ]

    def rank(item: tuple[int, dict[str, Any]]) -> tuple[int, int, int]:
        i, v = item
        about = f"{v.get('description')} {v.get('accents')} {v.get('country')}".lower()
        return (
            0 if str(v.get("name", "")).lower() in wanted else 1,
            0 if "british" in about else 1,
            i,
        )

    return [v for _, v in sorted(enumerate(men), key=rank)][:limit]


async def list_voices(
    cfg: CartesiaConfig, secret: Secret, transport: httpx2.AsyncBaseTransport | None
) -> list[dict[str, Any]]:
    """Cartesia's stock voices through the credit-free GET /voices (key in headers)."""
    key = secret.reveal()
    headers = {
        "X-API-Key": key,
        "Authorization": f"Bearer {key}",
        "Cartesia-Version": cfg.api_version,
    }
    found: list[dict[str, Any]] = []
    params: dict[str, Any] = {"limit": 100}
    async with httpx2.AsyncClient(transport=transport, timeout=_HTTP_TIMEOUT_S) as c:
        for _ in range(_PAGES):
            response = await c.get(
                f"{cfg.api_base}/voices", params=params, headers=headers
            )
            response.raise_for_status()
            body: Any = response.json()
            found += [v for v in body.get("data", []) if isinstance(v, dict)]
            if not body.get("has_more") or not body.get("next_page"):
                break
            params = {"limit": 100, "starting_after": body["next_page"]}
    return found


async def _collect(chunks: AsyncIterator[Samples]) -> Samples:
    parts = [c async for c in chunks]
    return np.concatenate(parts) if parts else np.zeros(0, dtype=np.float32)


def _cartesia_synth(cfg: TtsConfig, tools: Tools) -> CartesiaSynth:
    async def speak(voice_id: str, emotion: str) -> Samples:
        engine = CartesiaEngine(
            cfg.engines.cartesia.model_copy(update={"voice_id": voice_id}), tools.secret
        )
        try:
            return await _collect(engine.stream(cfg.audition_line, emotion))
        finally:
            await engine.end_reply()
            engine.cancel()  # drop the socket: nothing else will use it

    return speak


def _pocket_synth(cfg: TtsConfig) -> PocketSynth:
    engine = PocketEngine(cfg.engines.pocket_tts)
    engine.load()  # slow once: the model and every configured clip

    async def speak(path: str) -> tuple[Samples, int]:
        return await _collect(
            engine.preview(cfg.audition_line, path)
        ), engine.sample_rate

    return speak


def _read(path: Path) -> tuple[str, TtsConfig]:
    text = path.read_bytes().decode("utf-8")  # bytes: line endings stay as they are
    return text, TtsConfig.model_validate(tomllib.loads(text))


def _save(path: Path, text: str) -> None:
    TtsConfig.model_validate(
        tomllib.loads(text)
    )  # never write a file Snow cannot start on
    path.write_bytes(text.encode("utf-8"))


def _number(tools: Tools, prompt: str, count: int) -> int | None:
    """A 1-based choice, or None for blank (skip). Asks again on anything else."""
    while True:
        answer = tools.ask(prompt).strip()
        if not answer:
            return None
        if answer.isdigit() and 1 <= int(answer) <= count:
            return int(answer) - 1
        tools.say(f"Enter a number from 1 to {count}, or press Enter to skip.")


def audition_cartesia(path: Path, tools: Tools) -> int:
    text, cfg = _read(path)
    cart = cfg.engines.cartesia
    secret = tools.secret(cart.key_name)
    if secret is None:
        tools.say(
            "No Cartesia key is stored; run `snow setup` first. Skipping Cartesia."
        )
        return 0
    try:
        voices = asyncio.run(list_voices(cart, secret, tools.transport))
    except (httpx2.HTTPError, ValueError) as e:
        tools.say(f"Could not list Cartesia voices ({type(e).__name__}). Skipping.")
        return 1
    picks = shortlist(
        voices, cfg.audition.cartesia_shortlist, cfg.audition.max_candidates
    )
    if not picks:
        tools.say("Cartesia listed no English male voices.")
        return 1
    cost = len(cfg.audition_line) * len(EMOTIONS) * len(picks)
    tools.say(f"{len(picks)} candidate voices, each heard in {' and '.join(EMOTIONS)}:")
    for i, v in enumerate(picks, 1):
        tools.say(f"  {i}. {v.get('name')}: {str(v.get('description'))[:70]}")
    reply = tools.ask(f"This spends about {cost} Cartesia credits. Speak them? [y/N] ")
    if reply.strip().lower() not in ("y", "yes"):
        tools.say("Nothing spent.")
        return 0
    speak = tools.cartesia_voice or _cartesia_synth(cfg, tools)
    for i, v in enumerate(picks, 1):
        for emotion in EMOTIONS:
            tools.say(f"{i}. {v.get('name')} ({emotion})")
            try:
                tools.play(asyncio.run(speak(str(v["id"]), emotion)), cart.sample_rate)
            except EngineError as e:
                tools.say(f"Cartesia failed ({e}); stopping so no more credits go.")
                return 1
    index = _number(
        tools, "Pick the voice for Cartesia (Enter to keep none): ", len(picks)
    )
    if index is None:
        return 0
    chosen = picks[index]
    for key, value in (("voice_id", chosen["id"]), ("voice_name", chosen["name"])):
        text = set_line(text, "engines.cartesia", key, json.dumps(str(value)))
    _save(path, text)
    tools.say(f"Saved Cartesia voice {chosen['name']} to {path.name}.")
    return 0


def _clip_of(tools: Tools, clip_path: str) -> VoiceClip | None:
    """A clip of the user's own: asks whose voice it is. None if refused."""
    if not Path(clip_path).is_file():
        tools.say(f"No file at {clip_path}; refused.")
        return None
    consent = tools.ask(f"Whose voice is it? {' / '.join(CONSENTS)}: ").strip()
    if consent not in CONSENTS:
        tools.say(
            "A clip needs a consent tag. Refused: Snow never clones a voice without it."
        )
        return None
    return VoiceClip.model_validate({"path": clip_path, "consent": consent})


def audition_pocket(path: Path, tools: Tools) -> int:
    text, cfg = _read(path)
    presets = cfg.audition.pocket_voices
    speak = tools.pocket_voice or _pocket_synth(cfg)

    def hear(label: str, clip: str) -> bool:
        tools.say(label)
        try:
            samples, rate = asyncio.run(speak(clip))
        except Exception as e:  # noqa: BLE001 - e.g. an audio clip without the cloning weights
            tools.say(f"Could not speak {clip} ({type(e).__name__}: {str(e)[:120]}).")
            return False
        tools.play(samples, rate)
        return True

    for i, name in enumerate(presets, 1):
        hear(f"{i}. {name}", name)
    answer = tools.ask(
        "Pick a number, or the path of a clip of your own voice (Enter keeps it): "
    ).strip()
    if not answer:
        return 0
    if answer.isdigit() and 1 <= int(answer) <= len(presets):
        base: VoiceClip | None = VoiceClip(
            path=presets[int(answer) - 1], consent="licensed_preset"
        )
    else:
        base = _clip_of(tools, answer)
        if base is not None and not hear("your clip", base.path):
            base = None
    if base is None:
        return 2  # refused or unusable: nothing is written
    moods: dict[str, VoiceClip] = {}
    tools.say("Mood clips must be the same voice. Enter a clip path, or press Enter.")
    for mood in get_args(Mood):
        given = tools.ask(f"Clip for {mood} (Enter = base voice): ").strip()
        moods[mood] = (_clip_of(tools, given) if given else base) or base
    for mood, clip in moods.items():
        if clip != base and not hear(f"mood {mood}", clip.path):
            moods[mood] = base  # a clip that cannot be spoken is not saved
    text = set_line(text, "engines.pocket_tts", "reference", _clip_value(base))
    for mood, clip in moods.items():
        text = set_line(text, "engines.pocket_tts.moods", mood, _clip_value(clip))
    _save(path, text)
    tools.say(f"Saved Pocket voice {base.path} and {len(moods)} moods to {path.name}.")
    return 0


def main(argv: list[str] | None = None, *, tools: Tools | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="snow dev audition-voices",
        description="Hear the candidate voices and write your pick into tts.toml.",
    )
    parser.add_argument(
        "--cartesia", action="store_true", help="only the Cartesia voice"
    )
    parser.add_argument(
        "--pocket", action="store_true", help="only the Pocket TTS voice"
    )
    parser.add_argument("--config", type=Path, help="tts.toml to read and update")
    args = parser.parse_args(argv)
    path = args.config or config_dir() / "tts.toml"
    both = not (args.cartesia or args.pocket)
    tools = tools or Tools()
    result = 0
    if args.cartesia or both:
        result = audition_cartesia(path, tools)
    if args.pocket or both:
        result = max(result, audition_pocket(path, tools))
    return result
