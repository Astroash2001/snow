"""Conversation flow of the TurnEngine on scripted VAD (no models), in audio time."""

import numpy as np
import pytest
from pydantic import ValidationError

from snow.config.settings import load_config
from snow.voice.config import ConversationConfig, TurnConfig, VoiceConfig
from snow.voice.turn import CHUNK, TurnEngine, mic_level
from snow.voice.wake import WakeHit
from tests.voice.conftest import voice_cfg

CFG = voice_cfg()
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

    def on_barge_in(self) -> None:
        self.calls.append(("barge_in", None))


def make(
    vad: Vad | None = None,
    silence: float = 45.0,
    reply: float = 20.0,
    turn: TurnConfig | None = None,
) -> tuple[TurnEngine, Vad, Log]:
    vad = vad or Vad()
    log = Log()
    conv = ConversationConfig(silence_timeout_s=silence, reply_timeout_s=reply)
    engine = TurnEngine(turn or CFG.turn, vad, AlwaysComplete(), log, conversation=conv)  # type: ignore[arg-type]
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


def quiet(engine: TurnEngine, chunks: int = 1) -> None:
    for _ in range(chunks):
        engine.feed(np.zeros(CHUNK, dtype=np.int16))


def test_the_wake_phrase_while_snow_speaks_cuts_it_and_listens() -> None:
    engine, vad, log = make()
    wake(engine)
    speak(engine, vad)  # the turn ended: a reply is pending
    engine.set_speaking(True)
    quiet(engine)  # the inbox drains
    log.calls.clear()
    wake(engine)
    assert [c for c in log.calls if c[0] != "level"] == [
        ("barge_in", None),
        ("presence", "listening"),
        ("wake", None),
    ]
    feed_s(engine, 1.5)
    assert log.count("wake_alone") == 1  # a fresh wake turn was opened


def test_the_wake_phrase_while_thinking_is_still_ignored() -> None:
    engine, vad, log = make()
    wake(engine)
    speak(engine, vad)  # a reply is pending, Snow is not audible yet
    wake(engine)
    assert log.count("wake") == 1
    assert log.count("barge_in") == 0


class Over:
    """An engine with a reply pending and audible; every pause and check request
    is recorded, and no verdict comes until the test sends one."""

    def __init__(self, turn: TurnConfig | None = None) -> None:
        self.engine, self.vad, self.log = make(turn=turn)
        wake(self.engine)
        speak(self.engine, self.vad)
        self.engine.set_speaking(True)
        self.pauses: list[bool] = []
        self.checks: list[tuple[int, int]] = []  # (window samples, episode)
        self.engine.pause = self.pauses.append
        self.engine.check = lambda pcm, ep: self.checks.append((len(pcm), ep))
        quiet(self.engine)  # the inbox drains

    def hear(self, chunks: int, *, speech: bool) -> None:
        self.vad.speech = speech
        for _ in range(chunks):
            self.engine.feed(np.zeros(CHUNK, dtype=np.int16))

    def talk(self, chunks: int) -> None:
        self.hear(chunks, speech=True)

    def hush(self, chunks: int) -> None:
        self.hear(chunks, speech=False)

    def barge_ins(self) -> int:
        return self.log.count("barge_in")


def test_a_barge_in_tolerates_a_short_gap_inside_the_words() -> None:
    o = Over()
    o.talk(4)
    o.hush(2)
    o.talk(3)
    assert o.pauses == []  # 7 speech chunks: three short of 300 ms
    o.talk(3)
    assert o.pauses == [True]


def test_a_gap_over_150_ms_breaks_the_run() -> None:
    o = Over()
    o.talk(4)
    o.hush(5)
    o.talk(4)
    assert o.pauses == []


def test_the_pause_is_the_first_and_only_reaction_at_the_trigger() -> None:
    o = Over()
    assert not hasattr(o.engine, "duck")
    o.talk(9)  # 288 ms
    assert o.pauses == []
    o.talk(1)  # 10 chunks, 320 ms
    assert o.pauses == [True]
    assert o.barge_ins() == 0 and o.checks == []


def test_the_live_timings_pause_at_160_ms_and_have_no_duck_stage() -> None:
    # only the fixtures' 0.2 s stop is borrowed, so Over() ends its first turn fast
    live = load_config("voice.toml", VoiceConfig).turn.model_copy(
        update={"stop_secs": 0.2}
    )
    assert {"duck_after_ms", "duck_gain"}.isdisjoint(TurnConfig.model_fields)
    o = Over(live)
    o.talk(4)  # 128 ms
    assert o.pauses == []
    o.talk(1)  # 160 ms
    assert o.pauses == [True]


def test_a_warming_canceller_needs_600_ms_before_the_pause() -> None:
    o = Over()
    o.engine.echo_warming = lambda: True
    o.talk(18)
    assert o.pauses == []
    o.talk(1)
    assert o.pauses == [True]


def test_the_check_window_skips_the_echo_tail_and_asks_once_at_700_ms() -> None:
    o = Over()
    o.talk(10)  # the pause; the next 8 chunks (250 ms) are Snow's dying echo
    o.talk(29)  # chunks 11-39: window speech 21 chunks, 10752 samples
    assert o.checks == []
    o.talk(1)  # the window's 22nd speech chunk reaches 700 ms
    assert o.checks == [(22 * CHUNK, 1)]
    o.talk(5)
    assert len(o.checks) == 1  # exactly one check per episode


def test_an_accepting_verdict_cuts_and_the_turn_covers_the_episode_and_lead() -> None:
    o = Over()
    o.hush(20)
    o.talk(40)
    assert o.checks == [(22 * CHUNK, 1)]
    o.engine.verdict(1, True)
    o.talk(1)
    names = [n for n in o.log.names() if n != "level"]
    assert names[-3:] == ["barge_in", "presence", "turn_start"]
    assert o.pauses == [True]  # the pipeline's abort ends it
    o.hush(10)
    # the 40 speech chunks, 10 of lead (0.3 s), then 1 more speech and 7 quiet chunks
    assert o.log.turn_bytes[-1] == (50 + 1 + 7) * CHUNK * 2


def test_a_rejecting_verdict_resumes_and_the_hold_postpones_the_next_pause() -> None:
    o = Over()
    o.talk(40)
    o.engine.verdict(1, False)
    o.hush(1)  # the verdict chunk counts down the 1 s hold (32 chunks) once
    assert o.pauses == [True, False]
    assert o.barge_ins() == 0
    o.hush(5)
    o.talk(25)  # a 25-chunk run inside the hold: never a pause
    assert o.pauses == [True, False]
    o.talk(1)  # chunk 32: the hold reaches 0 and the pause fires at once
    assert o.pauses == [True, False, True]
    o.talk(8 + 22)  # the echo tail, then a 700 ms window: check episode 2
    assert o.checks[-1] == (22 * CHUNK, 2)
    o.engine.verdict(2, True)
    o.talk(1)
    assert o.barge_ins() == 1


def test_the_reject_hold_ends_after_one_second_of_audible_snow() -> None:
    o = Over()
    o.talk(40)
    o.engine.verdict(1, False)
    o.hush(32)  # 1 s of audible Snow, the verdict chunk included
    o.talk(9)
    assert o.pauses == [True, False]
    o.talk(1)  # the trigger chunk
    assert o.pauses == [True, False, True]


def test_a_short_stop_that_ends_before_the_pause_is_still_checked() -> None:
    o = Over()
    o.talk(4)  # 128 ms: under the pause trigger
    o.hush(12)  # 384 ms of quiet: not yet
    assert o.checks == []
    o.hush(1)  # 416 ms reaches quiet_resume_ms
    assert o.checks == [(17 * CHUNK, 1)]  # the whole episode
    assert o.pauses == []
    o.engine.verdict(1, True)
    o.hush(1)
    assert o.barge_ins() == 1


def test_a_one_word_stop_after_the_pause_is_checked_once_on_the_whole_episode() -> None:
    o = Over()
    o.talk(10)
    o.hush(13)
    assert o.checks == [(23 * CHUNK, 1)]
    o.hush(10)
    assert len(o.checks) == 1
    o.engine.verdict(1, False)
    o.hush(1)
    assert o.pauses == [True, False]
    o.talk(10)
    assert o.pauses == [True, False]  # the hold: no second pause


def test_a_blip_under_120_ms_is_given_back_with_no_check() -> None:
    o = Over()
    o.talk(3)
    o.hush(13)
    assert o.checks == [] and o.pauses == []
    o.talk(3)  # a fresh episode, still no hold
    o.hush(13)
    assert o.checks == []


def test_a_pending_check_gives_the_voice_back_at_the_release() -> None:
    o = Over()
    o.talk(40)  # checked, no verdict comes
    o.talk(23)  # 63 chunks: 2.02 s from the first speech
    assert o.pauses == [True, False]
    o.engine.verdict(1, True)  # late: ignored
    o.hush(1)
    assert o.barge_ins() == 0


def test_spaced_short_bursts_get_their_one_check_at_the_release() -> None:
    o = Over()
    for _ in range(4):  # 56 chunks of 4 speech and 10 quiet
        o.talk(4)
        o.hush(10)
    assert o.checks == [] and o.pauses == []
    o.talk(4)
    o.hush(3)  # 63 chunks: the release
    assert o.checks == [(63 * CHUNK, 1)]
    o.engine.verdict(1, True)  # still awaited: the verdict arrives inside the grace
    o.hush(1)
    assert o.barge_ins() == 1


def test_spaced_bursts_that_get_no_verdict_end_after_the_grace() -> None:
    o = Over()
    for _ in range(5):
        o.talk(4)
        o.hush(10)
    assert len(o.checks) == 1
    for _ in range(60):  # past 4 s of episode: the deadline plus the grace
        o.talk(1)
        o.hush(1)
    o.engine.verdict(1, True)
    o.hush(1)
    assert o.barge_ins() == 0


def test_stale_verdicts_never_cut() -> None:
    o = Over()
    o.engine.verdict(1, True)  # no episode, no check
    o.talk(2)
    assert o.barge_ins() == 0
    o.talk(38)
    assert len(o.checks) == 1
    o.engine.verdict(7, True)  # another episode's
    o.talk(1)
    assert o.barge_ins() == 0


def test_the_wake_phrase_cuts_a_paused_reply_at_once_with_no_check() -> None:
    o = Over()
    o.talk(10)
    assert o.pauses == [True]
    o.log.calls.clear()
    wake(o.engine)
    assert [c for c in o.log.calls if c[0] != "level"][:2] == [
        ("barge_in", None),
        ("presence", "listening"),
    ]
    assert o.checks == []


def test_the_default_check_accepts_at_once() -> None:
    engine, vad, log = make()
    wake(engine)
    speak(engine, vad)
    engine.set_speaking(True)
    quiet(engine)
    vad.speech = True
    for _ in range(41):
        engine.feed(np.zeros(CHUNK, dtype=np.int16))
    assert log.count("barge_in") == 1


@pytest.mark.parametrize(
    "update",
    [
        {"duck_release_s": 0.5},
        {"duck_release_s": 1.5},  # under pause + echo tail + check window
        {"check_min_speech_ms": 400},
        {"echo_tail_ms": 0},
        {"reject_hold_s": 0.0},
        {"reject_hold_s": 1.5},  # a held-back pause, echo tail and window need > 2 s
    ],
)
def test_bad_turn_settings_fail_at_load(update: dict[str, float]) -> None:
    with pytest.raises(ValidationError):
        TurnConfig(**{**CFG.turn.model_dump(), **update})


def test_the_fixture_turn_settings_are_valid_so_the_bad_cases_are_not_vacuous() -> None:
    TurnConfig(**CFG.turn.model_dump())


def test_a_release_shorter_than_the_words_check_fails_at_load() -> None:
    live = load_config("voice.toml", VoiceConfig)
    check = live.barge_check.model_copy(update={"timeout_s": 5.0})
    with pytest.raises(ValidationError):
        VoiceConfig(**{**live.model_dump(), "barge_check": check.model_dump()})
