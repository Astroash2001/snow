"""Conversation flow of the TurnEngine on scripted VAD (no models), in audio time."""

import numpy as np
import pytest

from snow.config.settings import load_config
from snow.voice.config import ConversationConfig, VoiceConfig
from snow.voice.turn import CHUNK, TurnEngine, mic_level
from snow.voice.wake import WakeHit

CFG = load_config("voice.toml", VoiceConfig)
FRAME = np.zeros(1280, dtype=np.int16)  # 80 ms
FRAMES_PER_S = 12.5


class Vad:
    """Says speech whenever `speech` is set; the test flips it between feeds."""

    def __init__(self) -> None:
        self.speech = False

    def speech_prob(self, chunk: object) -> float:
        return 1.0 if self.speech else 0.0

    def reset(self) -> None: ...


class AlwaysComplete:
    def append(self, pcm: object) -> None: ...

    def is_complete(self) -> bool:
        return True

    def clear(self) -> None: ...


class Log:
    """Records every engine callback as (name, argument)."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.turn_bytes: list[int] = []

    def names(self) -> list[str]:
        return [n for n, _ in self.calls]

    def count(self, name: str) -> int:
        return self.names().count(name)

    def on_wake(self, hit: object) -> None:
        self.calls.append(("wake", None))

    def on_conversation_start(self) -> None:
        self.calls.append(("conversation_start", None))

    def on_turn_start(self, turn_id: str) -> None:
        self.calls.append(("turn_start", turn_id))

    def on_turn_end(self, turn_id: str, pcm: bytes, dur: int, stop: int) -> None:
        self.turn_bytes.append(len(pcm))
        self.calls.append(("turn_end", turn_id))

    def on_wake_alone(self) -> None:
        self.calls.append(("wake_alone", None))

    def on_conversation_end(self, reason: str) -> None:
        self.calls.append(("conversation_end", reason))

    def on_presence(self, state: str) -> None:
        self.calls.append(("presence", state))

    def on_level(self, level: float) -> None:
        self.calls.append(("level", level))


def make(
    vad: Vad | None = None, silence: float = 45.0, reply: float = 20.0
) -> tuple[TurnEngine, Vad, Log]:
    vad = vad or Vad()
    log = Log()
    conv = ConversationConfig(silence_timeout_s=silence, reply_timeout_s=reply)
    engine = TurnEngine(CFG.turn, vad, AlwaysComplete(), log, conversation=conv)  # type: ignore[arg-type]
    return engine, vad, log


def feed_s(engine: TurnEngine, seconds: float) -> None:
    for _ in range(int(seconds * FRAMES_PER_S)):
        engine.feed(FRAME)


def wake(engine: TurnEngine) -> None:
    engine.on_wake(WakeHit(1.0, "t", [FRAME], 1280))


def speak(engine: TurnEngine, vad: Vad, seconds: float = 1.0) -> None:
    vad.speech = True
    feed_s(engine, seconds)
    vad.speech = False
    feed_s(engine, 0.5)  # 0.2 s of silence ends the turn (Smart Turn says complete)


def test_wake_alone_asks_for_an_ack_once_and_keeps_listening() -> None:
    engine, _, log = make()
    wake(engine)
    feed_s(engine, 5)
    assert log.count("wake_alone") == 1
    assert log.count("turn_end") == 0
    assert log.count("conversation_end") == 0


def test_second_turn_needs_no_new_wake() -> None:
    engine, vad, log = make()
    wake(engine)
    feed_s(engine, 2)  # wake alone
    speak(engine, vad)
    assert log.count("turn_end") == 1
    engine.reply_finished()
    feed_s(engine, 1)
    speak(engine, vad)
    assert (log.count("wake"), log.count("turn_end")) == (1, 2)
    assert log.count("conversation_start") == 1


def test_follow_on_turn_keeps_a_short_lead_in_not_the_idle_silence() -> None:
    engine, vad, log = make()
    wake(engine)
    feed_s(engine, 30)  # 30 s of nothing
    speak(engine, vad, 1.0)
    assert log.turn_bytes[0] < 2 * 16000 * 2  # under 2 s of 16-bit audio


def test_silence_ends_the_conversation_after_45_s_of_audio_time() -> None:
    engine, _, log = make()
    wake(engine)
    feed_s(engine, 44)
    assert log.count("conversation_end") == 0
    feed_s(engine, 2)
    assert ("conversation_end", "silence") in log.calls
    assert log.calls[-1] == ("presence", "sleeping")
    levels = log.count("level")
    feed_s(engine, 5)  # asleep: wake only, no levels
    assert log.count("level") == levels


def test_silence_timer_is_paused_while_a_reply_is_pending() -> None:
    engine, vad, log = make(reply=100.0)
    wake(engine)
    speak(engine, vad)
    feed_s(engine, 90)  # far past 45 s, but Snow is still answering
    assert log.count("conversation_end") == 0
    engine.reply_finished()
    feed_s(engine, 44)
    assert log.count("conversation_end") == 0
    feed_s(engine, 2)
    assert ("conversation_end", "silence") in log.calls


def test_a_reply_that_never_comes_times_out_back_to_listening() -> None:
    engine, vad, log = make(reply=20.0)
    wake(engine)
    speak(engine, vad)
    assert log.calls[-1][0] == "turn_end"
    feed_s(engine, 21)
    assert ("presence", "listening") == [c for c in log.calls if c[0] == "presence"][-1]


def test_end_request_from_the_loop_ends_the_conversation() -> None:
    engine, _, log = make()
    wake(engine)
    engine.end_conversation("phrase")
    engine.feed(FRAME)
    assert ("conversation_end", "phrase") in log.calls
    assert log.calls[-1] == ("presence", "sleeping")
    engine.reply_finished()  # late reply after the end changes nothing
    engine.feed(FRAME)
    assert log.count("conversation_end") == 1


def test_presence_follows_the_conversation() -> None:
    engine, vad, log = make()
    wake(engine)
    speak(engine, vad)
    engine.reply_finished()
    feed_s(engine, 0.5)
    states = [a for n, a in log.calls if n == "presence"]
    assert states == ["listening", "thinking", "listening"]


def test_mic_levels_only_while_listening_and_at_most_32_per_second() -> None:
    engine, vad, log = make()
    feed_s(engine, 2)  # asleep
    assert log.count("level") == 0
    wake(engine)
    assert log.count("level") == 0  # the pre-roll burst is not live audio
    feed_s(engine, 4)
    listening = log.count("level")
    assert 0 < listening <= 32 * 4
    speak(engine, vad)  # turn ends -> thinking
    thinking_from = log.count("level")
    feed_s(engine, 5)  # waiting for the reply: no levels
    assert log.count("level") == thinking_from


@pytest.mark.parametrize(
    ("amplitude", "lo", "hi"), [(0, 0.0, 0.0), (1036, 0.45, 0.55), (32767, 0.99, 1.0)]
)
def test_mic_level_scale(amplitude: int, lo: float, hi: float) -> None:
    chunk = np.full(CHUNK, amplitude, dtype=np.int16)
    assert lo <= mic_level(chunk) <= hi
