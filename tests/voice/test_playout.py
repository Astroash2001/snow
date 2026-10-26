"""Playout re-buffering, fades, synthesis RTF and clause hold. No device is opened."""

import logging

import numpy as np
import pytest

from snow.voice import playout as playout_mod
from snow.voice.playout import Playout, device_rate
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


def test_device_rate_is_the_wasapi_default_outputs_own_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sd = playout_mod.sd
    wasapi = [
        {"name": "MME", "default_output_device": 3},
        {"name": "Windows WASAPI", "default_output_device": 11},
    ]
    monkeypatch.setattr(sd, "query_hostapis", lambda: wasapi)
    monkeypatch.setattr(sd, "query_devices", lambda i: {"default_samplerate": 48000.0})
    assert device_rate() == 48000
    monkeypatch.setattr(sd, "query_hostapis", lambda: [wasapi[0]])
    assert device_rate() is None  # no WASAPI
    monkeypatch.setattr(
        sd, "query_hostapis", lambda: [{"name": "WASAPI", "default_output_device": -1}]
    )
    assert device_rate() is None  # no default output

    def broken(i: int) -> dict[str, float]:
        raise OSError

    monkeypatch.setattr(sd, "query_hostapis", lambda: wasapi)
    monkeypatch.setattr(sd, "query_devices", broken)
    assert device_rate() is None


def test_a_duck_ramps_down_within_30_ms_and_the_echo_reference_matches() -> None:
    playout, stream, rendered = rig()
    playout.push(tone(RATE))
    assert block_of(stream)[0] == pytest.approx(0.5)
    playout.set_gain(0.25)
    ducking = block_of(stream)
    assert ducking[0] < 0.5
    assert (np.diff(ducking) <= 1e-7).all()
    assert np.array_equal(rendered[-1], ducking)
    assert ducking[BLOCK // 2 - 1] > 0.125  # still ramping 10 ms in
    settled = block_of(stream)
    assert settled[BLOCK // 2] == pytest.approx(0.125)  # 30 ms after the duck
    third = block_of(stream)
    assert third == pytest.approx(np.full(BLOCK, 0.125), abs=1e-6)
    assert np.array_equal(rendered[-1], third)


def test_releasing_the_duck_rises_back_to_full_level_within_30_ms() -> None:
    playout, stream, _ = rig()
    playout.push(tone(RATE))
    playout.set_gain(0.25)
    for _ in range(3):
        block_of(stream)
    playout.set_gain(1.0)
    up = block_of(stream)
    assert (np.diff(up) >= -1e-7).all()
    assert block_of(stream)[BLOCK // 2] == pytest.approx(0.5)


def test_abort_and_a_drained_utterance_reset_the_gain() -> None:
    playout, stream, _ = rig()
    playout.push(tone(RATE))
    playout.set_gain(0.25)
    for _ in range(3):
        block_of(stream)
    playout.abort()
    playout.start_utterance()
    playout.push(tone(PREBUFFER + 10))
    assert block_of(stream)[0] == pytest.approx(0.5)

    playout.set_gain(0.25)
    playout.end_utterance()
    for _ in range(PREBUFFER // BLOCK + 3):  # play out and drain
        block_of(stream)
    playout.start_utterance()
    playout.push(tone(PREBUFFER + 10))
    assert block_of(stream)[0] == pytest.approx(0.5)


def ramp_signal(samples: int) -> np.ndarray:
    """1, 2, 3 ... scaled small: every sample is unique, so a resume position shows."""
    return (np.arange(1, samples + 1, dtype=np.float32)) / 1_000_000


def test_a_pause_ramps_to_silence_in_30_ms_then_holds_every_sample() -> None:
    playout, stream, rendered = rig()
    playout.push(tone(RATE))
    assert block_of(stream)[0] == pytest.approx(0.5)
    playout.set_paused(True)
    ramping = block_of(stream)
    assert ramping[0] < 0.5
    assert (np.diff(ramping) <= 1e-7).all()
    assert np.array_equal(rendered[-1], ramping)
    for _ in range(2):  # 30 ms is done by the second block after the pause
        block_of(stream)
    played, buffered = playout.played, playout._buffered  # noqa: SLF001
    for _ in range(5):
        held = block_of(stream)
        assert not held.any()
        assert np.array_equal(rendered[-1], held)  # the echo reference is silence too
    assert (playout.played, playout._buffered) == (played, buffered)  # noqa: SLF001


def test_a_paused_utterance_never_drains_or_underruns() -> None:
    for queued in (0, 5000):
        playout, stream, _ = rig()
        drained: list[int] = []
        playout.on_drained = lambda d=drained: d.append(1)
        playout.push(tone(PREBUFFER + 10))
        for _ in range(3):
            block_of(stream)
        playout.set_paused(True)
        for _ in range(3):
            block_of(stream)
        if queued == 0:
            playout._chunks.clear()  # noqa: SLF001
            playout._buffered = 0  # noqa: SLF001
        playout.end_utterance()
        for _ in range(10):
            block_of(stream)
        assert drained == []
        assert playout.underruns == 0


def test_resuming_continues_from_the_first_unplayed_sample_and_then_drains() -> None:
    playout, stream, _ = rig()
    drained: list[int] = []
    playout.on_drained = lambda: drained.append(1)
    signal = ramp_signal(PREBUFFER + 5000)
    playout.push(signal)
    playout.end_utterance()
    block_of(stream)
    playout.set_paused(True)
    for _ in range(4):
        block_of(stream)
    held_at = playout.played  # the first sample that has not played
    playout.set_paused(False)
    up = block_of(stream)
    step = 1.0 / (RATE * 0.03)
    rising = signal[held_at : held_at + BLOCK] * (np.arange(1, BLOCK + 1) * step)
    assert up == pytest.approx(rising, rel=1e-4)  # the held sample, ramping up
    full = block_of(stream)
    assert full[BLOCK // 2] == pytest.approx(signal[held_at + BLOCK + BLOCK // 2])
    while not drained:
        block_of(stream)
    assert drained == [1]


def test_abort_and_a_new_utterance_clear_a_pause() -> None:
    playout, stream, _ = rig()
    playout.push(tone(PREBUFFER + 10))
    playout.set_paused(True)
    for _ in range(3):
        block_of(stream)
    playout.abort()
    playout.start_utterance()
    playout.push(tone(PREBUFFER + 10))
    assert block_of(stream)[0] == pytest.approx(0.5)

    playout.set_paused(True)
    playout.start_utterance()
    playout.push(tone(PREBUFFER + 10))
    assert block_of(stream)[0] == pytest.approx(0.5)
