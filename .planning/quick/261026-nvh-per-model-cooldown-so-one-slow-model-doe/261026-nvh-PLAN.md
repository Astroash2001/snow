---
phase: quick-261026-nvh
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - src/snow/brain/limits.py
  - src/snow/brain/chain.py
  - tests/brain/test_cooldown.py
autonomous: true
requirements: [CORE-04, CORE-09, SAFE-12]

estimate:
  tokens: 45000
  raw_tokens: 45000
  tasks: 2
  confidence: low

must_haves:
  truths:
    - "When a model misses its first-token deadline, the next model of the same provider is tried in the same turn. With fast = groq-1, groq-2, experiential: if groq-1 times out, groq-2 serves the reply and groq is called twice (closes UAT gap G-01-16)"
    - "A timeout, a 5xx or an empty reply (switch reasons timeout and service_error) cools down only that provider+model pair, for the same duration as before (provider hint, else transient_s). The pair stays skipped on later turns until that time, then is tried again"
    - "A 429 (rate_limit or out_of_quota), a 401/403 (bad_key) or a connection failure (unreachable) still cools down the whole provider, so none of its models is called until the provider's cooldown ends"
    - "config_error (400/404/422) still sets no cooldown at all, as before. It never touched the provider's other models, and a 400 can be specific to one request"
    - "The health.provider row shows cooling_down only while the provider itself is cooling. A model-only cooldown leaves the provider row at failing (or active once another of its models serves). The health.role entries show cooling_down with cooling_until_ns on the cooled entry only"
    - "Cooling never promotes an untrusted provider: when every trusted model is cooling, a private request still raises PrivacyBlockedError and nothing is sent (SAFE-12)"
  artifacts:
    - path: "src/snow/brain/limits.py"
      provides: "RateLimiter.record_failure(provider, entry, reason, headers, body): the cooldown key is (provider, entry.model) for timeout and service_error, else the provider. cooling_until checks both keys. snapshot reports the provider-wide cooldown only"
      contains: "_MODEL_REASONS"
    - path: "src/snow/brain/chain.py"
      provides: "LLMChain._record_failure passes the entry to the limiter and marks the provider row cooling_down only when the provider itself is cooling"
      contains: "record_failure(entry.provider, entry"
    - path: "tests/brain/test_cooldown.py"
      provides: "End-to-end per-model timeout test, scope matrix, two-model 429 test, privacy check for both scopes"
      contains: "test_timeout_cools_only_that_model"
  key_links:
    - from: "src/snow/brain/chain.py LLMChain.stream"
      to: "RateLimiter.cooling_until(entry.provider, entry)"
      via: "the per-entry skip check that stays AFTER the privacy check"
      pattern: "cooling_until\\(entry.provider, entry\\)"
    - from: "src/snow/brain/chain.py LLMChain._record_failure"
      to: "RateLimiter.snapshot(entry.provider)"
      via: "the provider row is cooling_down only when the provider-wide cooldown exists"
      pattern: "snapshot\\(entry.provider\\)"
---

<objective>
Fix UAT gap G-01-16 ("A slow provider does not silence Snow"). Today a first-token timeout on groq gpt-oss-120b cools down all of Groq, so groq qwen3.8-27b is never tried. When experiential also times out, only the untrusted OpenRouter entry is left and the privacy gate holds the request back.

After this change, failures specific to one model (timeout, service_error) cool down only that provider+model pair, so the provider's other models are still tried in the same turn. Provider-wide failures (rate_limit, out_of_quota, bad_key, unreachable) still cool down the whole provider. Health rows stay correct, and the privacy rule is unchanged.

Purpose: one slow model no longer silences Snow while a healthy model of the same provider is available.
Output: per-model cooldown keys in RateLimiter, chain wiring, tests in tests/brain/test_cooldown.py.
</objective>

<execution_context>
@C:/Users/avina/Desktop/asssistant/.claude/gsd-core/workflows/execute-plan.md
@C:/Users/avina/Desktop/asssistant/.claude/gsd-core/templates/summary.md
</execution_context>

<context>
@.planning/STATE.md
@.claude/CLAUDE.md
@src/snow/brain/limits.py
@src/snow/brain/chain.py
@tests/brain/conftest.py
@tests/brain/test_cooldown.py

<interfaces>
Current signatures (src/snow/brain/limits.py, class RateLimiter):
- record_success(self, provider: str, entry: "ChainEntry", usage_tokens: int | None, text_len: int) -> None
- record_failure(self, provider: str, reason: str, headers: Mapping[str, str], body: object) -> datetime | None. It returns None for config_error. Otherwise it stores max(until, existing) in self._cool[provider] and returns the newly computed until
- cooling_until(self, provider: str, entry: "ChainEntry") -> datetime | None. It deletes an expired entry from self._cool, then applies entry.daily_request_cap (local midnight)
- snapshot(self, provider: str) -> tuple[int, int, datetime | None]. It returns (requests_today, tokens_today, live provider cooldown)
- self._cool: dict[str, datetime]

src/snow/brain/chain.py:
- SwitchReason = "rate_limit" | "out_of_quota" | "service_error" | "timeout" | "unreachable" | "bad_key" | "config_error"
- classify(): TimeoutError or APITimeoutError gives timeout. APIConnectionError gives unreachable. 429 gives out_of_quota or rate_limit. 401/403 give bad_key. 400/404/422 give config_error. Anything else (5xx, _EmptyReply) gives service_error
- LLMChain.stream line ~218: `if self._limiter and self._limiter.cooling_until(entry.provider, entry): continue`. This sits after the privacy check
- LLMChain._record_failure(entry, reason, exc) -> tuple[ProviderStatus, str | None]. Line ~318 calls `self._limiter.record_failure(entry.provider, reason, headers, body)` and returns ("cooling_down" if until else "failing", reason). The result is stored in self._board[entry.provider]
- _entry_status uses self._cooling(entry), which is cooling_until(entry.provider, entry). It gives cooling_down plus cooling_until_ns per role entry
- _publish_providers uses limiter.snapshot(name). A cooling_down board row with no live provider cooldown is shown as ready. A live provider cooldown is always shown as cooling_down

tests/brain/conftest.py helpers: MODELS (fast chain = groq groq-1, experiential exp-1, google gem-1 untrusted, nvidia nim-1; brain chain = experiential luna, google gem-1, nvidia nim-1, openrouter or-1; fast ttft_timeout_s 0.2), hang_route(routes, host), sse_route(routes, host, chunks), Routes.count(host), Events.of(type).
tests/brain/test_cooldown.py: Clock (datetime, advance(seconds)), limiter fixture, make(role, models=None) fixture building LLMChain with the limiter, limited(status, headers), ENTRY = ChainEntry(provider="groq", model="m"), and the cooldown_s helper. test_bad_key_costs_one_call_not_two already builds a two-groq fast chain by inserting {"provider": "groq", "model": "groq-2"} at index 1.
</interfaces>
</context>

<tasks>

<task type="tracer" tdd="true">
  <name>Task 1: A model timeout cools down only that model, end to end through LLMChain</name>
  <files>src/snow/brain/limits.py, src/snow/brain/chain.py, tests/brain/test_cooldown.py</files>
  <behavior>
    - test_timeout_cools_only_that_model: fast chain with groq-1 and groq-2 (two-groq config). The first groq request hangs (hang_route) and the second is an sse_route reply "via qwen". stream(MSG) returns provider groq and model groq-2, the text is "via qwen", and routes.count(groq) == 2
    - In the same turn, the last health.role event has status fallback. entries[0] is cooling_down with cooling_until_ns set and detail "timeout", and entries[1] is active. No health.provider event for groq has status cooling_down
    - Next turn (one queued groq reply): it is served by model groq-2, so groq-1 was skipped while cooling
    - After clock.advance(20.1) (transient_s default 20 plus margin), one queued groq reply is served by model groq-1 again
  </behavior>
  <action>
RED first. In tests/brain/test_cooldown.py, add a module helper two_groq() that returns ModelsConfig.model_validate on a deepcopy of MODELS with {"provider": "groq", "model": "groq-2"} inserted at index 1 of the fast chain. Switch test_bad_key_costs_one_call_not_two to use it, so the inline copy goes away. Import hang_route from tests.brain.conftest. Write test_timeout_cools_only_that_model exactly as described in behavior. Use the make fixture with two_groq(), and the clock fixture for advance. Run it and confirm it fails: today groq is called once, and experiential has no route, so the turn fails.

GREEN in src/snow/brain/limits.py:
- Add a module constant _MODEL_REASONS = frozenset({"timeout", "service_error"}), with a one-line comment: a slow or broken model, not a provider-wide limit (G-01-16).
- Change the type of self._cool to dict[str | tuple[str, str], datetime]. A str key cools the whole provider. A (provider, model) key cools one model.
- Change record_failure to record_failure(self, provider, entry: "ChainEntry", reason, headers, body). The entry goes second, matching record_success and cooling_until. Keep the config_error early return of None and keep every duration rule unchanged. Choose key = (provider, entry.model) when reason is in _MODEL_REASONS, else provider. Store max(until, existing) under that key and still return the newly computed until. Update the docstring: the cooldown is provider-wide for limits, auth and outages, and covers only entry's model for a timeout or a 5xx or empty reply. It returns the cooldown end, or None for config_error.
- Add a private helper _live(self, key) that returns the unexpired end for a key, deleting the key once it has expired. This moves the expiry logic that cooling_until and snapshot each have today into one place.
- cooling_until(provider, entry) takes the later of _live(provider) and _live((provider, entry.model)), ignoring None. Then it applies the daily_request_cap rule exactly as today.
- snapshot(provider) uses _live(provider) only, so the provider health row never shows a model-only cooldown. Say so in its docstring.
- Add one line to the module docstring about per-model cooldowns.

GREEN in src/snow/brain/chain.py, LLMChain._record_failure:
- Call self._limiter.record_failure(entry.provider, entry, reason, headers, body).
- Return ("cooling_down" if self._limiter.snapshot(entry.provider)[2] is not None else "failing", reason). This is enough because a provider that was already cooling would have been skipped before this call, so a live provider cooldown here means this failure caused it.
- Update the docstring: the cooldown is per CORE-09, and the provider row cools only when the whole provider does.
- Leave the stream loop as it is. The cooling check stays after the privacy check (SAFE-12). Its comment "cooling never promotes untrusted" stays true.

Update the existing test_cooldown.py call sites for the new signature by passing ENTRY as the second argument: the cooldown_s helper, test_config_error_is_not_a_provider_wide_cooldown, test_cooldown_ends_exactly_when_asked, test_only_untrusted_left_fails_closed_while_cooling and test_all_cooling_is_exhausted_not_hammered. Durations asserted by test_unknown_signals_use_defaults (timeout 20, service_error 20) stay the same, because the return value is unchanged.

Project rules: never cd. No new packages. Never log keys or error bodies (only the failure kind, T-01-20). Leave src/snow/voice/, tests/voice/, config/voice.toml and config/persona.toml alone, because quick task 261026-nui is editing them in parallel.
  </action>
  <verify>
    <automated>uv run pytest -q tests/brain/test_cooldown.py</automated>
  </verify>
  <done>test_timeout_cools_only_that_model passes, and every existing test in tests/brain/test_cooldown.py passes with the new record_failure(provider, entry, reason, headers, body) signature.</done>
</task>

<task type="auto">
  <name>Task 2: Guard the scope rules: 429 still cools the whole provider, health and privacy hold for both scopes</name>
  <files>tests/brain/test_cooldown.py</files>
  <action>
Add regression guards to tests/brain/test_cooldown.py. The Task 1 code should already make them pass. If one fails, fix the code in src/snow/brain/limits.py or src/snow/brain/chain.py. Do not weaken the test.

1. test_cooldown_scope (unit, parametrized on reason):
   - Model-scoped cases: timeout and service_error. After limiter.record_failure("groq", ENTRY, reason, {}, None), cooling_until("groq", ENTRY) is set. cooling_until("groq", ChainEntry(provider="groq", model="other")) is None, and snapshot("groq")[2] is None.
   - Provider-wide cases: rate_limit, out_of_quota, bad_key and unreachable. Both entries are cooling, and snapshot("groq")[2] is set.

2. test_rate_limit_still_cools_the_whole_provider: use the two_groq() config. Queue limited(429, {"retry-after": "12"}) on groq and an sse_route reply on experiential. Then check all of the following:
   - stream(MSG) is served by experiential, and routes.count(groq) == 1.
   - In the last health.role event, entries[0] and entries[1] are both cooling_down with cooling_until_ns set.
   - Some health.provider event for groq has status cooling_down with cooling_until_ns set.

3. Parametrize test_only_untrusted_left_fails_closed_while_cooling over reason in (rate_limit, timeout), per SAFE-12. Cool the brain chain's trusted entries with that reason, passing the matching entry each time: ChainEntry(provider="experiential", model="luna") and ChainEntry(provider="nvidia", model="nim-1"). A private stream(MSG) must still raise PrivacyBlockedError with routes.total == 0. This covers the G-01-16 symptom shape: per-model cooling never opens the untrusted google or openrouter entries.

4. In test_cooling_provider_is_skipped_then_returns, fix the stale comment above `assert routes.count(groq) == 2`. The conftest fast chain has only one groq entry, so that comment's claim about a second entry is false. Reword it to say groq was asked twice in all: the 429, then the reply after the cooldown. test_rate_limit_still_cools_the_whole_provider now covers the two-entry case.

Then run the full gate from the repo root. Never cd.
  </action>
  <verify>
    <automated>uv run ruff check src tests && uv run ruff format --check src tests && uv run pyright && uv run pytest -q tests/brain</automated>
  </verify>
  <done>The scope matrix, two-model 429 and both-scope privacy tests pass. ruff check, ruff format --check and pyright are clean, and all of tests/brain passes.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| brain -> remote LLM providers | Private user data (transcripts, memory) crosses here. Only trusted providers may receive it (SAFE-12) |
| provider error response -> RateLimiter | Headers and body from a remote provider set the cooldown durations |

## STRIDE Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation Plan |
|-----------|----------|-----------|----------|-------------|-----------------|
| T-nvh-01 | Information disclosure | LLMChain.stream entry selection | high | mitigate | The per-entry cooling check stays after the privacy check in the stream loop, unchanged. test_only_untrusted_left_fails_closed_while_cooling is parametrized over rate_limit and timeout, and asserts PrivacyBlockedError with zero requests sent |
| T-nvh-02 | Denial of service | Provider-wide hang | low | accept | A provider whose host hangs after connecting now costs one TTFT deadline per model (two groq models in fast = 2 x 4.0 s) before the next provider. A refused connection is still classified as unreachable, which is provider-wide. Per-model timeouts are the behavior the user asked for in G-01-16 |
| T-nvh-03 | Tampering | RateLimiter durations from provider headers and body | low | accept | Duration parsing and the _MAX_COOLDOWN_S one-day cap are unchanged. Only the cooldown key changes |
| T-nvh-04 | Information disclosure | Logs and events on failure | medium | mitigate | No new log or event fields. Only the failure kind is logged or emitted, never error bodies or keys (T-01-20) |
| T-nvh-SC | Tampering | pyproject.toml / uv.lock | low | mitigate | No package installs or lockfile changes in this plan |
</threat_model>

<verification>
- uv run ruff check src tests
- uv run ruff format --check src tests
- uv run pyright
- uv run pytest -q tests/brain
- Live check after merge (for the user, not the executor): if a groq gpt-oss-120b timeout appears in the event log, it should be followed by an llm.call for groq qwen/qwen3.8-27b in the same turn, and the groq health.provider row should not show cooling_down
</verification>

<success_criteria>
- A first-token timeout on one model leads to the provider's next model being tried in the same turn
- 429, auth and connection failures still skip the whole provider
- The provider health row cools only for provider-wide cooldowns. Role entries show per-entry cooling
- No private request reaches an untrusted provider under either cooldown scope
- All gates are green. No new packages. No edits under src/snow/voice/, tests/voice/, config/voice.toml or config/persona.toml
</success_criteria>

<output>
Create `.planning/quick/261026-nvh-per-model-cooldown-so-one-slow-model-doe/261026-nvh-SUMMARY.md` when done
</output>
