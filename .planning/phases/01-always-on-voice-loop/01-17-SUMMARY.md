---
phase: 01-always-on-voice-loop
plan: 17
subsystem: brain
tags: [llm-gateway, model-probe, latency, models-toml, fast-role]
status: complete

requires:
  - phase: 01-always-on-voice-loop/01-08
    provides: ModelsConfig / ChainEntry (match glob), LLMChain, fail-closed MockTransport fixtures
  - phase: 01-always-on-voice-loop/01-11
    provides: get_secret, stored provider keys, redacting logger
provides:
  - "`snow dev probe-models [--json] [--latency N]` (src/snow/brain/probe.py: main, probe, rank_matches)"
  - "config/models.toml with every keyed entry resolved to an exact listed ID plus dated probe comments"
  - "Measured fast-role time to first token for Groq gpt-oss-120b and Experiential deepseek-v4-flash"
affects: [01-18, 01-29]

commits: 2
plan_head_before: a6661b264be7f3de4f010da2f9a5e79d0beb24a6
plan_head_after: 91dd375960cafd2c0526bbb4281682395eb49404

actuals:
  tokens: 36000
  tasks: 1
  commits: 2

tech-stack:
  added: []
  patterns:
    - "Probe checks pass entry params through extra_body (same as LLMChain) so per-model quirks are honoured"
    - "Glob entries rank candidates by the numbers in the ID, then try up to 3 until stream (and tools when required) pass; a 401/403 stops the search because it is account-wide"
    - "Reports carry only IDs, booleans, timings and the failure kind, never keys or error bodies (T-01-35)"

key-files:
  created:
    - src/snow/brain/probe.py
    - tests/brain/test_probe.py
    - tests/brain/test_probe_live.py
  modified:
    - config/models.toml

key-decisions:
  - "Fast chain order unchanged: Groq gpt-oss-120b (p50 0.456 s) is faster than Experiential deepseek-v4-flash (p50 1.111 s), so it stays first (D-30)"
  - "Gemini resolves to gemini-3.6-flash, not the newest 3.8: 3.7/3.8 stream timed out or took 11 s to first token while 3.6 streams in about 2.1 s with tools and vision working"
  - "NIM slots re-pointed: NIM lists no deepseek-v4-pro and no kimi-k3 (kimi-k2.6 returns 404), so the slots became deepseek-ai/deepseek-v4.1-flash and z-ai/glm-5.3"

patterns-established:
  - "Re-probe after any provider change: `uv run snow dev probe-models` then hand-edit models.toml; entries keep `match` so a newer ID can be found"

requirements-completed: [CORE-04, CORE-08, SPCH-04]

duration: ~45min
completed: 2026-10-17
---

# Phase 1 Plan 17: Gateway Probe and Fast-Role Latency Summary

**`snow dev probe-models` lists each keyed provider's models, resolves match globs to exact IDs, checks stream/tools/vision and measures time to first token; models.toml now holds probe-confirmed IDs and Groq gpt-oss-120b stays the fast primary (p50 0.456 s vs 1.111 s).**

## What was built

- `src/snow/brain/probe.py`: per keyed provider `models.list()` (Google's `models/` prefix stripped; Experiential's keyless catalog `/api/models` adds input modalities to the notes), glob resolution, then streaming, tool calling (`tool_choice="required"`) and image input (8x8 PNG, vision-role entries only) with synthetic prompts. `--latency N` (default 10 when the flag is given bare) runs N interleaved short prompts against Groq gpt-oss-120b and Experiential deepseek-v4-flash and prints TTFT p50/p95. Keyless providers print `skipped: no key`; the command exits 1 only when no provider has a key.
- `tests/brain/test_probe.py` (8 tests, fail-closed `httpx2.MockTransport`; respx cannot patch openai 3.29): version ranking, glob resolution, JSON shape, keyless skip, tool-call false detection, vision only for the vision role, latency p50/p95.
- `tests/brain/test_probe_live.py` (`network` marker): real probe, asserts every keyed provider lists models and that no placeholder string leaks. Ran once, passed (200 s, dominated by slow NIM/free-tier calls).

## Measured results (2026-10-17, this connection)

All five providers had stored keys. Model counts: Experiential 296, Groq 11, Google 63, NVIDIA NIM 81, OpenRouter 467.

Fast-role time to first token, 8 sequential runs each, 0 errors:

| Model | p50 | p95 |
|-------|-----|-----|
| Groq `openai/gpt-oss-120b` (reasoning_effort low) | 0.456 s | 0.886 s |
| Experiential `deepseek-v4-flash` | 1.111 s | 1.73 s |

Groq is first in the fast chain (already the configured order). Single probe runs showed Groq `qwen/qwen3.8-27b` at 0.12 to 0.49 s, which may beat gpt-oss-120b; it was not in the plan's comparison so it is not measured at n=8. Time to first audio is for plan 01-29's hardware suite.

Resolved entries (stream / tools / vision):

| Role | Provider | Model ID | Result |
|------|----------|----------|--------|
| brain, vision | experiential | gpt-5.6-luna | yes / yes / yes, TTFT 1.0-1.6 s |
| brain, vision | google | gemini-3.6-flash | yes / yes / yes, TTFT about 2.1 s |
| brain | nvidia | deepseek-ai/deepseek-v4.1-flash | listed; stream and tools timed out at 30 s |
| brain | nvidia | z-ai/glm-5.3 | stream yes but 29 s to first token; tools timed out at 30 s |
| brain | openrouter | nvidia/nemotron-3-super-120b-a12b:free | yes / yes, TTFT 1.2-2.0 s |
| fast | groq | openai/gpt-oss-120b | yes / yes |
| fast | groq | qwen/qwen3.8-27b | yes / yes |
| fast | experiential | deepseek-v4-flash | yes / yes (one tools call timed out once) |
| fast | openrouter | nvidia/nemotron-3.5-lightning:free | yes / yes, TTFT 18.7 s (free queue) |
| vision | experiential | qwen3.8-27b | stream yes; tools and image input rejected with 400 despite the catalog claiming image support |

Unresolved entries (`model = ""`): none. All five providers are keyed, so no entry was skipped for a missing key. Two NIM entries are resolved but unverified (timeouts); two OpenRouter and the Experiential qwen entries are last resorts.

## Findings the orchestrator should know

- The brain chain's `ttft_timeout_s = 6.0` will skip the two NIM entries today (29 s or more). They are effectively dead weight until NIM latency improves; the chain fails over past them.
- Gemini 3.7/3.8 flash looked slow or flaky today; `match = "gemini-[0-9]*-flash"` is kept so a re-probe can move up.
- `gpt-6-luna` and `gpt-6-luna-decisions` are listed on Experiential; the config still uses `gpt-5.6-luna`. Left alone (user decision).
- Experiential `qwen3.8-27b` fails tools and image input (400) on this gateway although the catalog claims support; Groq's copy of the same model passes tools.

## Deviations from Plan

### Auto-fixed / adjusted

**1. [Rule 1 - Bug] Version ranking let name words outrank version numbers**
- **Found during:** Task 1 live run
- **Issue:** the first sort key compared name text, so `gemini-omni-1.1-flash` could outrank `gemini-3.8-flash`, and `*:free` ranked an unrelated model first
- **Fix:** rank by the numbers in the ID, then by ID; `[0-9]` in the Gemini glob; unit test added
- **Commit:** 91dd375

**2. [Rule 1 - Bug] 64-token budget starved thinking models**
- **Issue:** Gemini 3.x spent the budget on reasoning and returned no visible text, so streaming looked broken
- **Fix:** `_MAX_TOKENS = 256`; the probe also now tries up to 3 ranked candidates for glob entries (stops early on 401/403) and records passed-over IDs in the note
- **Commit:** 91dd375

**3. [Rule 3 - Blocking] Match globs adjusted to what providers really list**
- `nemotron-3-super*:free` could never match `nvidia/nemotron-3-super-...` (provider prefix), so it became `*nemotron-3-super*:free`; NIM `deepseek-v4-pro` and `kimi-k3` do not exist (see key decisions); the fast OpenRouter glob `*:free` ranked arbitrary models first and was narrowed to `*nemotron-3.5-lightning:free`. These are config-only edits inside this plan's files.

**4. Probe checks use `max_tokens`/`extra_body` rather than the plan's "max 5 tokens"** because reasoning models need room before the first visible text.

None of the out-of-scope files (voice, hud, hub, contracts, config package, chain.py, limits.py, worker.py, conftest, pyproject, uv.lock) were touched. `src/snow/cli.py` already had the `dev probe-models` entry.

## Quota used

About 90 small calls in total across probing, diagnostics and one live-test run (OpenRouter free about 20, Google about 20). No Cartesia calls. Prompts were synthetic ("Reply with OK", a ping tool, an 8x8 red PNG).

## Known Stubs

None.

## Threat Flags

None. No new endpoints or storage; keys only via `get_secret`.

## Verification

`uv run pytest -m "not network"` 271 passed; `ruff check`, `ruff format --check`, `pyright` clean; `snow dev probe-models --json` returned valid JSON with exit 0; live test passed.

## Self-Check: PASSED

Files exist (probe.py, test_probe.py, test_probe_live.py, models.toml); commits 5cd9eca and 91dd375 are on the branch.
