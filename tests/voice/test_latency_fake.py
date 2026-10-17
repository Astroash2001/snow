"""Per-turn timing (SPCH-04) with zero-latency fakes: what the pipeline itself adds.

The real-hardware numbers (Groq, the fast chain, Pocket, the real speaker) live in
tests/hardware/test_latency.py. Nothing here opens a device or plays a sound.
"""

from snow.contracts.events import TurnTiming
from tests.voice.conftest import FakeGroq
from tests.voice.test_bargein import ask, make_rig
from tests.voice.test_tts_pipeline import FakeEngine, delta, final, of, play_out

BUDGET_NS = 100_000_000  # the pipeline's own share of the one-second budget


async def test_a_turn_reports_five_timestamps_and_adds_under_100_ms(
    groq: FakeGroq,
) -> None:
    rig = await make_rig(groq, FakeEngine())
    turn_id = await ask(rig)  # VAD stop, then the (fake) Groq final
    await rig.pipeline.on_hub_event(delta("Sure thing. ", turn_id))  # first token
    await rig.pipeline.on_hub_event(final("Sure thing.", turn_id))
    assert rig.pipeline._reply is not None  # noqa: SLF001
    await play_out(rig.pipeline, rig.hub, rig.speaker)

    [timing] = of(rig.hub, TurnTiming)
    assert timing.turn_id == turn_id
    stamps = [
        timing.vad_stop_ns,
        timing.stt_final_ns,
        timing.llm_first_token_ns,
        timing.tts_first_audio_ns,
        timing.audio_out_first_ns,
    ]
    assert None not in stamps
    known = [s for s in stamps if s is not None]
    assert known == sorted(known)  # the stages happen in this order
    assert known[-1] - known[0] < BUDGET_NS
