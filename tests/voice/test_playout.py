"""Playout re-buffering, fades, synthesis RTF and clause hold. No device is opened."""

import logging

import numpy as np
import pytest

from snow.voice.playout import Playout
from tests.voice.test_tts_pipeline import (
    RATE,
    TTS_CFG,
    FakeStream,
    Speaker,
    delta,
    final,
    play_out,
    setup,
)

CFG = TTS_CFG.playout
BLOCK = int(RATE * 0.02)
FADE = int(RATE * 0.005)
REBUFFER = RATE * CFG.rebuffer_ms // 1000
PREBUFFER = RATE * CFG.prebuffer_ms // 1000


def tone(samples: int, value: float = 0.5) -> np.ndarray:
    return np.full(samples, value, dtype=np.float32)


def rig() -> tuple[Playout, FakeStream, list[np.ndarray]]:
    speaker, rendered = Speaker(), []
    playout = Playout(
        RATE,
        CFG,
        on_render=lambda block: rendered.append(block.copy()),
        stream_factory=speaker.factory,
    )
    playout.start_utterance()
    assert speaker.stream is not None
    return playout, speaker.stream, rendered


def block_of(stream: FakeStream) -> np.ndarray:
    out = np.zeros((BLOCK, 1), dtype=np.float32)
    stream.callback(out, BLOCK, None, None)
    return out[:, 0].copy()


def test_an_underrun_fades_out_rebuffers_and_fades_back_in() -> None:
    playout, stream, rendered = rig()
    playout.push(tone(int(RATE * 0.41)))  # 20 full blocks and half a block
    for _ in range(20):
        assert block_of(stream)[0] == pytest.approx(0.5)
    dry = block_of(stream)  # the queue runs dry inside this block
    half = int(RATE * 0.01)
    assert playout.underruns == 1
    assert dry[half - 1] <= 0.5 / FADE + 1e-6
    assert dry[half - FADE] == pytest.approx(0.5)  # the ramp starts at full level
    assert not dry[half:].any()
    assert (np.diff(dry[half - FADE : half]) < 0).all()
    assert np.array_equal(rendered[-1], dry)  # the echo reference equals the speaker

    playout.push(tone(REBUFFER - 1))
    assert not block_of(stream).any(), "one sample short of the re-buffer plays nothing"
    playout.push(tone(1))
    resumed = block_of(stream)
    assert resumed[0] <= 0.5 / FADE + 1e-6
    assert resumed[FADE - 1] == pytest.approx(0.5)
    assert (np.diff(resumed[:FADE]) > 0).all()
    assert np.array_equal(rendered[-1], resumed)
    assert playout.underruns == 1


def test_an_ended_utterance_that_drains_is_not_an_underrun() -> None:
    playout, stream, _ = rig()
    drained = []
    playout.on_drained = lambda: drained.append(1)
    playout.push(tone(PREBUFFER + 10))
    playout.end_utterance()
    for _ in range(40):
        block_of(stream)
    assert drained == [1]
    assert playout.underruns == 0


def test_the_underrun_count_resets_with_the_next_utterance() -> None:
    playout, stream, _ = rig()
    playout.push(tone(PREBUFFER + 10))
    for _ in range(40):
        block_of(stream)
    assert playout.underruns >= 1
    playout.start_utterance()
    assert playout.underruns == 0


def test_the_first_rtf_is_taken_as_is_then_blended() -> None:
    playout, _, _ = rig()
    playout.push(tone(RATE))  # exactly 1.0 s of audio
    playout.clause_done(0.4)
    assert playout.rtf == pytest.approx(0.4)
    playout.push(tone(RATE))
    playout.clause_done(0.8)
    assert playout.rtf == pytest.approx(0.6)  # EWMA, weight 0.5
    playout.clause_done(5.0)  # nothing was pushed: not a measurement
    assert playout.rtf == pytest.approx(0.6)


def test_rtf_exactly_at_hold_rtf_does_not_hold_but_just_above_does() -> None:
    playout, stream, _ = rig()
    playout.push(tone(RATE))
    playout.clause_done(CFG.hold_rtf)
    assert not playout.holding
    fresh, _, _ = rig()
    fresh.push(tone(RATE))
    fresh.clause_done(CFG.hold_rtf + 0.01)
    assert fresh.holding


def test_while_holding_a_clause_plays_only_once_complete() -> None:
    playout, stream, _ = rig()
    playout.push(tone(RATE))
    playout.clause_done(CFG.hold_rtf + 0.2)
    for _ in range(51):
        block_of(stream)  # play and drain the first clause
    playout.push(tone(int(RATE * 0.5)))  # more than the prebuffer
    assert not block_of(stream).any(), "held until the clause is complete"
    playout.clause_done(0.2)
    assert block_of(stream).any()


def test_while_holding_end_of_utterance_releases_the_audio() -> None:
    playout, stream, _ = rig()
    playout.push(tone(RATE))
    playout.clause_done(CFG.hold_rtf + 0.2)
    for _ in range(51):
        block_of(stream)
    playout.push(tone(int(RATE * 0.5)))
    playout.end_utterance()
    assert block_of(stream).any()


def test_a_finished_clause_shorter_than_the_prebuffer_starts_at_once() -> None:
    playout, stream, _ = rig()
    playout.push(tone(int(RATE * 0.2)))
    assert not block_of(stream).any()
    playout.clause_done(0.1)
    assert block_of(stream).any()


async def test_the_pipeline_reports_each_clause_and_logs_numbers_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pipeline, hub, engine, speaker, _turn = await setup()
    seen: list[float] = []
    assert pipeline._playout is not None  # noqa: SLF001
    real = pipeline._playout.clause_done  # noqa: SLF001
    pipeline._playout.clause_done = lambda s: (seen.append(s), real(s))[1]  # type: ignore[method-assign]  # noqa: SLF001
    caplog.set_level(logging.INFO, logger="snow.voice")
    await pipeline.on_hub_event(delta("Sure, I can do that. "))
    await pipeline.on_hub_event(delta("Second sentence here."))
    await pipeline.on_hub_event(final("Sure, I can do that. Second sentence here."))
    await play_out(pipeline, hub, speaker)

    assert len(seen) == len(engine.texts) == 2
    assert all(s >= 0 for s in seen)
    line = next(r.getMessage() for r in caplog.records if "tts_playout" in r.message)
    assert "underruns=" in line
    assert "rtf=" in line
    assert not any(t in caplog.text for t in engine.texts)
