---
phase: 01-always-on-voice-loop
plan: 31
subsystem: voice
tags: [cartesia, tts, voice-router, budget, failback, spch-02, spch-03]
status: complete

requires:
  - phase: 01-always-on-voice-loop
    provides: "VoiceRouter and failover (01-26/01-28), barge-in abort path (01-29), emotion header and big_moment (01-16), voice.status / voice.switch / tts.spoken events and the cartesia_chars_today projection (01-04), HUD Voice card (01-22 pattern)"
provides:
  - "CartesiaEngine: one warm WebSocket, one context per reply, a flush after every router chunk, emotion validated against Cartesia's list (else neutral), key sent only in headers"
  - "CartesiaHealth (ok / out_of_credits / unreachable / no_key) with classify(): 402, 'credit' or 'quota' means out_of_credits, 401/403 means no_key, two consecutive connection failures mean unreachable"
  - "Free failback probe: authenticated GET /voices?limit=1 every probe_interval_s (90) while unavailable; a 200 restores Cartesia; router upkeep loop runs it, refreshes credits (only if credits_url is set) and keeps the socket warm"
  - "Per-chunk daily character budget (650): hub snapshot count plus characters started since; a new local day resets it"
  - "Router: Cartesia only for big moments with key, voice id, health and budget; any failure hands this chunk and the rest of the reply to the everyday voice; voice.switch published at the moment of fallback; voice.status carries credits / availability / reason and shows Cartesia while it just spoke"
  - "ReplyDelta.emotion and ReplyDelta.big_moment (additive): the brain sets them on every delta, the pipeline uses them from the first chunk"
  - "tts.spoken rows per engine that spoke (Cartesia's characters are never attributed to the last voice)"
affects: [01-32 voice audition (fills voice_id / voice_name), 01-33 Chatterbox, HUD Voice card]

commits: 2
plan_head_before: 166b6010eda0da37e63ac2f95ff57987720f9ed0
plan_head_after: 3fc751539de5195121c12d4cd55b7285a1a97ecf

actuals:
  tokens: 16700
  tasks: 1
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Engine owns its health; the router asks engine.unavailable_reason(len(chunk)) per chunk instead of using the cooldown map (Cartesia recovers by probe, not by timer)"
    - "Reply-level `tried` map shared across chunks: an engine that broke stays out of the rest of the reply and the switch reason comes from it"
    - "Flush per chunk inside one open context: chunk boundaries are known without lookahead, so no latency is added to the first sentence"
    - "Local mock WebSocket server (websockets serve on 127.0.0.1) plus httpx2.MockTransport for REST; fail closed"

key-files:
  created:
    - src/snow/voice/tts/cartesia.py
    - tests/voice/test_cartesia.py
  modified:
    - src/snow/voice/tts/router.py
    - src/snow/voice/tts/config.py
    - src/snow/voice/pipeline.py
    - src/snow/voice/__main__.py
    - config/tts.toml
    - src/snow/contracts/events.py
    - src/snow/brain/worker.py
    - contracts/events.schema.json
    - contracts/samples/events.json
    - contracts/samples/conversation-12.jsonl
    - hud/src/generated/contracts.d.ts
    - tests/voice/test_tts_failover.py
    - tests/voice/test_tts_router.py
    - tests/brain/test_persona.py

key-decisions:
  - "Cartesia has NO remaining-balance endpoint. GET /usage/credits reports credits USED and needs an admin key (sk_car_admin_...); a normal key is rejected. So credits_url stays empty, credits_remaining is None and the HUD shows 'Unavailable' with 'Cartesia did not report a balance.' The daily budget counts characters locally and never depends on it (UI-SPEC unresolved credits row: resolved as Unavailable)"
  - "WebSocket auth: both X-API-Key and Authorization: Bearer are sent (the plan and the current conventions page name different ones); GET /voices?limit=1 with this pair returned 200 with the real stored key"
  - "voice is sent as {id} (current AsyncAPI: 'object with a required id'), not {mode, id}; Cartesia-Version 2026-08-14 (the API reference default); model is the dated snapshot sonic-3.6-2026-08-27"
  - "Chunk end is found with an empty-transcript flush (flush_done), the context is closed with an empty transcript and continue false at the end of the reply; Cartesia says 'done' only for a whole context"
  - "A health of 'no_key' also covers a key Cartesia rejects (401/403); the probe notices a corrected key"
  - "cancel() (barge-in) drops the socket (a cancel message only stops requests not yet generating) and is not counted as a failure"
  - "Plain ws:// is refused unless the host is loopback (the key travels in a header)"

requirements-completed: [SPCH-03, SPCH-02]

coverage:
  - id: D1
    description: "A big moment with emotion excited sends one context (model, voice, pcm_f32le 24 kHz, generation_config.emotion, continue true then false on close); audio chunks reach playout in order; Pocket is not used"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_cartesia.py#test_a_big_moment_is_one_context_with_the_replys_emotion", status: pass}
    human_judgment: false
  - id: D2
    description: "A normal reply never opens a Cartesia context or connection; Cartesia is never used for everyday replies"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_cartesia.py#test_a_normal_reply_never_opens_a_cartesia_context", status: pass}
    human_judgment: false
  - id: D3
    description: "402 / 'credit' / quota_exceeded mark out_of_credits; this and the remaining chunks go to Pocket; voice.switch(cartesia to pocket_tts, out_of_credits) once; voice.status cartesia_available false with the reason"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_cartesia.py#test_out_of_credits_speaks_the_reply_in_pocket_and_says_why", status: pass}
    human_judgment: false
  - id: D4
    description: "Two consecutive connection failures mean unreachable; the free probe does nothing before 90 s and a 200 at 91 s restores ok and voice.status cartesia_available true; a refused probe keeps it down"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_cartesia.py#test_two_connection_failures_mean_unreachable_and_the_probe_restores_it", status: pass}
      - {kind: test, ref: "tests/voice/test_cartesia.py#test_a_probe_that_is_refused_keeps_cartesia_down", status: pass}
    human_judgment: false
  - id: D5
    description: "Daily budget: 640 used plus a 19-character chunk against 650 goes to Pocket with budget_reached; checked per chunk so it can run out mid-reply; a new day resets it"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_cartesia.py#test_the_daily_budget_sends_a_big_moment_to_pocket", status: pass}
      - {kind: test, ref: "tests/voice/test_cartesia.py#test_the_budget_is_checked_per_chunk_so_it_can_run_out_mid_reply", status: pass}
    human_judgment: false
  - id: D6
    description: "No stored key: Cartesia never contacted, voice.status reason no_key; no voice id: skipped quietly"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_cartesia.py#test_without_a_stored_key_cartesia_is_never_contacted", status: pass}
    human_judgment: false
  - id: D7
    description: "Cartesia dying after the first chunk: the finished chunk is not repeated or dropped, the rest of the reply is spoken in Pocket; deltas alone route a streamed big moment to Cartesia before any final event"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_tts_failover.py#test_cartesia_dying_after_the_first_chunk_finishes_the_reply_in_pocket", status: pass}
      - {kind: test, ref: "tests/voice/test_tts_failover.py#test_a_big_moment_streamed_by_the_brain_reaches_cartesia_from_its_first_word", status: pass}
    human_judgment: false
  - id: D8
    description: "Barge-in over a Cartesia reply drops its context and is not counted as an outage"
    status: tested
    verification:
      - {kind: test, ref: "tests/voice/test_cartesia.py#test_talking_over_cartesia_drops_its_context_without_counting_a_failure", status: pass}
    human_judgment: false
  - id: D9
    description: "Real Cartesia speech: a big moment (greeting, joke) is audibly expressive in the chosen voice; the Voice card shows Cartesia with the Big moment chip; credits row shows Unavailable"
    status: pending
    human_judgment: true
    rationale: "Needs a voice id in tts.toml (plan 01-32), real synthesis (spends the user's credits) and a listener. Not run by this agent. A network+slow test exists (tests/voice/test_cartesia.py#test_real_cartesia_speaks_a_short_big_moment)"
---

# Phase 1 Plan 31: Cartesia big-moment voice Summary

**Cartesia sonic-3.6 speaks the LLM's big moments with the reply's emotion over one warm WebSocket, inside a 650-character daily budget; no key, no voice id, no credits, no connection or an exhausted budget hand the rest of the reply to Pocket TTS, and a free `GET /voices?limit=1` probe every 90 s brings Cartesia back on its own.**

## What was built

- `src/snow/voice/tts/cartesia.py`: `CartesiaEngine`, `CartesiaHealth`, `classify`, `parse_balance`. One context per reply; each router chunk is sent with `continue: true` and followed by an empty-transcript flush so `flush_done` marks the chunk end; the reply closes with an empty transcript and `continue: false`. A connection that idled out gets one retry on the first send. Barge-in (`cancel()`) drops the socket; a socket dying because of that is turned into a cancellation, not a failure.
- Router: `_choose` takes the chunk text and asks the engine `unavailable_reason(len(text))` (no_key, health, budget_reached). The `tried` map is now per reply and carries the reason, so `voice.switch` is published at the moment of failover (it used to wait for the next chunk). `announce()` shows Cartesia on the Voice card while it has just spoken and carries credits / availability / reason. A 5 s upkeep task runs the probe, credits and warm-up.
- Pipeline: `ReplyDelta.emotion/big_moment` set the reply's voice from the first chunk; `on_snapshot` seeds the budget from `cartesia_chars_today`; `tts.spoken` is published per engine that spoke, also on barge-in for Cartesia (its credits were spent).
- `config/tts.toml` `[engines.cartesia]` filled in; `CartesiaConfig` typed with `extra="forbid"`; `voice_id` is empty until plan 01-32, so Cartesia is skipped quietly until then.

## Credits endpoint verdict (resolves the UI-SPEC unresolved row)

Cartesia exposes no remaining-balance endpoint. `GET /usage/credits` returns credits consumed per bucket and requires an admin key (`sk_car_admin_...`); the docs say a standard key is rejected there. `credits_url` is therefore empty by default, `credits_remaining` stays `None`, and the HUD shows "Unavailable" / "Cartesia did not report a balance." (copy already in the HUD). If the user ever stores an admin key and a balance endpoint appears, `credits_url` + `parse_balance` already handle a `credits_remaining` / `remaining_credits` / `remaining` / `balance` number. I did not call `/usage/credits` for real (the docs are explicit and it needs a key the user does not have).

## Real credit-free calls made (through the app's own probe path)

1 call: `GET https://api.cartesia.ai/voices?limit=1` with the stored key (headers `X-API-Key`, `Authorization: Bearer`, `Cartesia-Version: 2026-08-14`) returned `200`. Key never printed or logged. No synthesis, no WebSocket opened, no credits spent.

## Error payload shape

Cartesia 2026-03-01+ WebSocket error event (documented, mock server uses it): `{"type":"error","done":true,"status_code":429,"error_code":"quota_exceeded"|null,"title":"...","message":"...","request_id":"...","context_id":"..."}`. Known `error_code`s: `quota_exceeded`, `concurrency_limited`, `voice_not_found`, `voice_model_mismatch`. The first error payload (status, code, title, truncated message) is logged once per engine as `cartesia_error`. I did not trigger a real error, so the live payload for an exhausted free plan is documented, not observed (research A12 stays open: if it is a plain-text string instead of JSON the engine counts it as an unreachable failure, which still falls back safely; `classify` also looks for "credit" and "quota").

## Deviations from Plan

### Cross-boundary change (authorised by the orchestrator prompt)

**1. [Rule 3 - Blocker] ReplyDelta carried no emotion or big_moment**
- **Found during:** Task 1 (known gap from 01-26/01-28)
- **Issue:** chunks were spoken before the router knew a reply is a big moment, so the first sentence of a greeting would have gone to Pocket.
- **Fix:** additive, defaulted `emotion: str | None = None`, `big_moment: bool = False` on `ReplyDelta` (`src/snow/contracts/events.py`); `src/snow/brain/worker.py` sets them on every delta from the header parser (`apply_overrides(...)`, `parser.big`; the header always precedes the first visible text); pipeline uses them in `_speak`. Schemas, samples and `hud/src/generated/contracts.d.ts` regenerated with `snow.contracts.export` and `npm --prefix hud run gen:types`. HUD `typecheck` and `test` (190) pass. Nothing renamed or removed; no other hud source touched.
- **Commit:** 1f795f5 (contract + brain), 3fc7515 (pipeline use)

### Auto-fixed Issues

**2. [Rule 1 - Bug] voice.switch waited a chunk (or never came) on mid-reply failover**
- **Found during:** Task 1 (out_of_credits needs the switch published with the fallback)
- **Issue:** `_choose` skipped engines in `tried` before noting them as failed, so the switch was announced on the next chunk, and never for a one-chunk reply.
- **Fix:** `tried` is now a reply-level map engine to reason; `_choose` reports the first failed engine. Existing failover tests still pass unchanged.
- **Files:** src/snow/voice/tts/router.py

**3. [Rule 2 - Missing critical] tts.spoken attributed all characters to the last voice**
- **Issue:** with Cartesia for sentence 1 and Pocket for the rest, the hub's daily Cartesia count (the budget, T-01-49) would have lost sentence 1.
- **Fix:** router tracks characters per engine for the reply (`take_spoken`); pipeline emits one `tts.spoken` per engine, and one for Cartesia on barge-in.
- **Files:** src/snow/voice/tts/router.py, src/snow/voice/pipeline.py

**4. [Rule 1 - Test update] test_tts_router.py cartesia eligibility test**
- A big moment now needs a configured voice id; the existing test gives its fake Cartesia one. Behaviour otherwise unchanged.

### Plan details followed differently

- `voice` is `{"id": ...}` not `{mode: "id", id}` (current API reference); both auth headers sent; model is the dated snapshot. `CartesiaEngine` takes `set_base()` (called by the pipeline on each snapshot) instead of a `chars_today_provider` callable, which avoids building the engine before the pipeline exists.
- `respx` replaced by `httpx2.MockTransport` (known: respx does not intercept httpx2).
- The plan's `ErrorKind` for a rejected key is `no_key`; there is no separate "bad key" reason in the contract.

**Total deviations:** 1 authorised cross-boundary change, 3 auto-fixed, 1 test update. **Impact:** none beyond the plan's intent.

## Known limits (shortcuts)

- A socket that dies in the middle of a chunk makes that chunk repeat its first words in Pocket (documented in the module header; same shortcut as the router).
- The probe proves the key and the API are reachable, not that credits are back; if still out of credits, the next big moment fails once (free) and falls back again.
- Real message order after `flush` (audio then `flush_done`) and the live out-of-credits payload follow the docs and are not observed; a pending real-synthesis test covers the first.
- Opening a real WebSocket was not done by me (could not prove the header choice for the WebSocket handshake; REST accepted the same header pair).

## Pending for the user (not done by this agent)

1. Plan 01-32: pick a voice (or set any English stock voice id, e.g. Skylar `db6b0ed5-d5d3-463d-ae85-518a07d3c2b4` from the sonic-3.6 page) in `config/tts.toml` `[engines.cartesia] voice_id` / `voice_name`. Until then Cartesia is skipped and big moments use Pocket.
2. Human check (plan `<human-check>`): say "Hey Snow, good morning", ask for a joke; confirm those replies are in the Cartesia voice, the Voice card shows Cartesia with the Big moment chip, and record that the credits row reads "Unavailable".
3. Optional: `uv run pytest -m network tests/voice/test_cartesia.py` spends about 20 credits to confirm real synthesis.

## Threat surface

No new endpoints or ports. Outbound: `wss://api.cartesia.ai/tts/websocket` and `https://api.cartesia.ai` carrying only Snow's own big-moment reply text and the key in headers (T-01-48 accepted). T-01-49 mitigated: per-chunk daily budget seeded from the event log, failed requests cost no credits, local fallback, `ws://` refused off loopback. No audio written anywhere; `test_no_egress.py` and the no-disk proofs pass unchanged (no allow-list change was needed because the egress tests never register Cartesia). `test_no_scripts.py` passes.

## Self-Check

- Files exist: src/snow/voice/tts/cartesia.py, tests/voice/test_cartesia.py
- Commits exist: 1f795f5, 3fc7515
- Full suite: 376 passed (`uv run pytest -q`), ruff check/format, pyright (0 errors), `snow.contracts.export --check`, HUD typecheck and 190 tests all pass.

## Self-Check: PASSED
