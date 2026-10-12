# Project Research Summary

**Project:** Snow | **Domain:** always-on voice-first Windows desktop AI that drives coding agents, controls the PC, shows a glyph-rendered HUD, and hands off to Android | **Researched:** 2026-10-13 | **Confidence:** MEDIUM

## Executive Summary

Snow is a voice orchestrator: intent-level speech goes to coding agents and the PC, Snow asks back by voice when it needs a decision, and every step shows on a HUD. Experts split this into a latency-critical audio plane and a durable control plane, with every client a thin subscriber to one typed event stream. Nothing existing covers the full scope (wake word + agent-agnostic relay + presence-routed approvals + live audit HUD), so the differentiation is real but the scope is large for one developer.

Recommended approach: a Python 3.12 core (`snow-core`) owns mic, speakers, models, agents, secrets and policy; the HUD is a web client over loopback WebSocket with a per-launch token. Pipecat 1.12 is the voice pipeline; faster-whisper turbo (int8_float16) does STT; openWakeWord does "Hey Snow"; Cartesia sonic-3.6 is primary voice with kokoro-onnx fallback; ACP is the adapter contract for agents, with the Claude Agent SDK direct for Claude Code. LLM access is the plain `openai` SDK via `base_url` with model roles. Do not import `litellm` (PyPI releases compromised March 2026).

Key risks: the assistant hearing itself (echo, self-trigger, self-approval), prompt injection from everything Snow reads, over-permissive autonomy with full PC rights, and exposed remote access. Mitigate with a deterministic fail-closed policy gate and kill switch outside the LLM, speaker verification as a filter (not authentication), AEC before barge-in, Tailscale-only remote, and secrets the agent never sees raw. Build foundations and policy before any action-capable tool.

## Key Findings

**Stack (STACK.md):** Python-first for voice ML and Windows automation; TS/React/R3F HUD; uv-managed Python 3.12 (system is 3.10); Node 25 is non-LTS; Rust/MSVC not installed. Core choices: pipecat-ai 1.12.0, faster-whisper 1.2.1 + ctranslate2 4.8.2, openWakeWord 0.6.0, sherpa-onnx 1.13.8 (speaker embeddings), livekit 1.1.20 (AEC3 APM), kokoro-onnx 0.6.1, openai 3.29.0, mcp 2.3.0, agent-client-protocol 0.12.1, claude-agent-sdk 0.2.165, uiautomation 2.0.29, Playwright 1.63 (dedicated Snow Chrome profile), FastAPI/uvicorn/websockets, SQLite WAL + FTS5, keyring, structlog, python-telegram-bot 22.8, Tailscale Serve. Run Snow as a per-user Task Scheduler logon process with watchdog, not a Windows Service (Session 0). Pinned: onnxruntime CPU only in core (Pipecat pins ~=1.24.3).

**Decision: language split and shell (STACK vs ARCHITECTURE disagree).**
- Option A (STACK): Python core + TS HUD + thin shell (Tauri, Electron fallback).
- Option B (ARCHITECTURE): TypeScript daemon `snowd` as control plane, Python voice sidecar, Python MCP PC server, Electron shell.
- Recommendation: Option A with Electron (not Tauri) as the v1 shell. Reasons: voice ML, UIA automation, audio/volume libs and the Claude SDK's richest permission hooks are Python-first, so a TS control plane adds a language boundary through the hot path and policy; this machine has Node and Python but no Rust/MSVC, so Tauri adds a multi-GB install to Phase 1 for an unmeasured RAM gain; the HUD is a WebSocket client, so moving to Tauri later only swaps the shell. ARCHITECTURE's patterns (ports and adapters, durable event log, snapshot-plus-delta, single command funnel, Job Object children) apply unchanged. Revisit if the Python core misses the latency gate in Phase 2. Flag as a user/roadmap decision.

**Features (FEATURES.md):**
- Table stakes: local "Hey Snow" with ack within 100 ms; PTT and visible hard mute; streaming STT with barge-in, AEC, semantic end-of-turn, backchannel tolerance, project-vocabulary biasing, self-correction cleanup; show raw transcript; never lose utterances; spoken reply ~1 s, short; typed fallback; start/steer/stop agents by voice; relay questions and permissions fail-closed; deterministic fast-path PC control; tool order API/CLI, then UIA/DOM, then pixels; risk tiers with deterministic tier 3; kill switch outside LLM; take-over for secrets; speaker verification; secrets in OS store; injection posture; live activity stream and states; walk-away execution; phone push and authenticated answers; autostart and recovery.
- Differentiators: one voice for any agent with switch on failure; glass-box HUD as audit surface; presence-aware approval routing (fail closed when unknown); unified approval inbox; reason shown on every notice; worktree isolation and undo; LLM speech with emotion constrained by structured facts; quota/credit alerts.
- Defer: GUI screen control, logged-in web tasks, multi-step cross-app (v1.x); full ASCII 3D body (staged); backchannel classifier, free-text phone replies, voiced return brief (v1.x); background non-focus GUI control (v2+); proactive engine, native Android app, multi-user, learning, job hunting, smart home (out of scope).
- Anti-features: Talon-style syntax, reading diffs aloud, narrating every action, bypass/auto-approve for remote, LLM-only safety gate, voice passwords, public ntfy approval content, Claude /voice or Wispr as voice layer, heavy HUD effects that starve STT.

**Architecture (ARCHITECTURE.md):** Audio plane (wake, VAD, turn, speaker verify, STT, TTS, playout, local barge-in) isolated from the control plane (orchestrator, task runner, policy, tools, adapters, memory, notifications, remote gateway). Durable facts written to SQLite with seq and projections in the same transaction; ephemeral signals broadcast only; big payloads as hashed artifacts; raw audio never crosses IPC; turn_id with one cancellation token fanned out to LLM, tools, TTS and playout; barge-in truncates history to what was heard. Adapters normalize to AgentEvent (message delta, plan, tool call, diff, terminal, permission request, question, done, error); ACP first, Claude SDK direct, OpenCode HTTP/SSE and PTY only if needed. Policy is deterministic; LLM can raise tiers only; approvals are durable objects resolved from any channel, default-deny. T3 approvals need a second factor beyond voice.

**Pitfalls (PITFALLS.md), top items with prevention:**
1. Echo and self-trigger: AEC with loopback reference before VAD/wake/STT; barge-in needs verified speech held ~150–300 ms; nothing Snow produced counts as approval; separate headphones and speaker modes.
2. Latency blown: per-stage timestamps from day one; stream everything; fast model for acks; semantic endpointing; pre-warm connections; HUD feedback local.
3. Prompt injection (lethal trifecta): tag tools by private-data, untrusted-input, exfiltration; escalate when all three; separate action-validator call; separate browser profile; source badge on plan steps.
4. Over-permissive autonomy: code-based tiers; LLM only raises; recycle bin, worktrees, read-back of resolved targets; no elevated Snow; presence unknown means away.
5. Unreliable agent permission relay: structured protocols only; request-ID binding and read-back; escalate on timeout, never auto-approve; know each agent's headless permission mode.
6. Exposed remote: loopback or Tailscale only; no Funnel; Host/Origin checks; app-layer tokens; tier-3 second factor; Telegram allow-list by numeric ID; ntfy minimal text (verify CVE-2026-39087 fixed version via NVD).
7. Secrets leaking: Credential Manager/DPAPI; secret references resolved at call time; redaction on every egress; screenshot blocklist; block .env/.ssh reads; canary test; gitleaks.
8. Wake and speaker verification as security: treat verifier as a filter; measure false accepts per hour (target under 1/h) on real audio; hard negatives; reject audio correlated with system loopback.
9. Cost runaway: central gateway with per-feature counters and budgets; loop guards; routing by task.
10. Solo-builder scope creep: thin vertical slice first; dogfood; time-box HUD art; hold out-of-scope list.
Also: STT mangles identifiers (hotwords, LLM normalization); VRAM budget on 6 GB; HUD GPU/battery (render on demand, iGPU); UIPI/DPI/focus; speech vs display split; WhatsApp ban risk (keep out of v1); adapter sprawl and borrowed-account terms.

## Implications for Roadmap

- **Phase 0 Foundations:** repo and CI (uv, Python 3.12, windows-latest with fake transports); protocol schemas with event envelope (source, reason, risk, user_id); model-role config; Credential Manager; redaction; gateway with counters and budget; injection test scaffold; gitleaks and pip-audit; hash-locked deps. Gateway spike here. Avoids 4, 7, 9, 25.
- **Phase 1 Glass-box skeleton:** loopback WebSocket with token; event bus and SQLite log; supervisor; DOM HUD event viewer; Task Scheduler autostart with watchdog; shell spike (Electron recommended); iGPU ASCII shader perf spike. Avoids 12, 15, 20.
- **Phase 2 Voice plane:** sounddevice transport; AEC (livekit APM); openWakeWord trained on real negatives; VAD; Smart Turn; faster-whisper turbo with partials and hotwords; speaker verification in parallel; Cartesia plus kokoro fallback with credit meter; local barge-in with confirmation. GATE: measured time-to-first-audio p50/p95, false wakes per hour, barge-in accuracy on speakers and headphones. Avoids 1, 2, 8, 10, 11, 19.
- **Phase 3 Brain:** LLM role routing; orchestrator with turn_id cancellation; sentence chunker; validated emotion enum; persona golden tests; spoken-offset truncation; minimal memory with FTS5; speech/display split; structured-facts layer. Avoids 16, 19, 23.
- **Phase 4 Policy, tools, kill switch, fast-path PC control:** deterministic tiers T0–T3; durable approval objects, fail-closed; presence service (at-PC first); kill switch via separate listener, hotkey and HUD, wired to supervisor; tool registry with risk metadata; secret take-over; built-in apps, windows, volume, brightness, media, files. Avoids 4, 3, 13, 7.
- **Phase 5 Coding-agent adapters:** ACP client with Gemini CLI, OpenCode ACP, Claude via Agent SDK (can_use_tool, AskUserQuestion, defer), Antigravity spike; normalized AgentEvent; voice relay with request-ID binding and read-back; steer and cancel; session persistence; health and failover that never silently moves half-done tasks; worktrees; contract tests with recorded transcripts. Avoids 5, 18, 3. Research flag.
- **Phase 6 Hand-off, notifications, remote:** durable task runner with leases and reconciler; away policy; task board; Telegram sink with allow-list and minimal text; ntfy as fallback behind same interface; Tailscale Serve with pairing and ACLs; notification budget and expiry; single-use approval tokens bound to action hash; revoke-all-devices. Avoids 6, 8, 24.
- **Phase 7 Screen-understanding and multi-step PC control:** UIA-first (uiautomation, Windows-MCP with PowerShell and Registry excluded); screenshot plus vision fallback with step budgets and postconditions; dedicated Snow Chrome profile for logged-in web (Playwright MCP pinned); multi-step with checkpoints; automation test bed. Avoids 13, 14, 7, 17. Research flag.
- **Phase 8 HUD ASCII 3D and panels (parallel track from Phase 3):** state visuals; custom ASCII Effect with glyph atlas and glow; live panels; history and approvals; silent mode; corner and phone layouts; reduced-motion and low-power fallbacks. Avoids 15, 25.
- **Phase 9 Hardening and packaging:** installer; uv-managed core with frozen sync; CUDA wheel handling; signed auto-update; soak across sleep, lock, Bluetooth; port-scan release gate; red-team injection suite; canary-secret test; idle power budget. Avoids 6, 7, 12, 20, 21. Research flag on packaging.

**Ordering rationale:** foundations first (most expensive to retrofit); visible skeleton before voice; voice measured on real hardware before the brain; speaker verification before any action tool; policy before agents and PC control; agents before hand-off (owned, resumable sessions); PC control last among capabilities; HUD art runs in parallel behind the state interface.

**Research flags (run /gsd-plan-phase --research-phase):** Phase 2 (AEC on speakers, wake-word training on 3.12, short-utterance speaker verification, STT latency and VRAM, Cartesia timestamps); Phase 3 (gateway tool calling and latency); Phase 5 (Antigravity ACP and headless behaviour, Claude subscription-login terms, OpenCode API generation); Phase 7 (UIPI and elevated windows, vision model choice, injection defence for screen-reading); Phase 9 (CUDA packaging).
**Standard patterns (skip research):** Phase 0, Phase 1 (shell spike bounded), Phase 6 (Tailscale and Telegram well documented), Phase 8 (time-boxed).

## Confidence Assessment

| Area | Confidence | Notes |
|---|---|---|
| Stack | MEDIUM-HIGH | Versions verified against registries; hardware behaviour (STT latency/VRAM, Tauri under GPU load, AEC, wake accuracy) unmeasured; language split unresolved between files |
| Features | MEDIUM | Adjacent-product sources; table stakes well corroborated; differentiators are judgement |
| Architecture | MEDIUM | Shape corroborated by Pipecat, LiveKit, ACP, MCP docs; many specifics [L]; control-plane language is a judgement call |
| Pitfalls | MEDIUM | Structural risks well established; numbers from vendor/academic/hobbyist sources; WhatsApp policy LOW-MEDIUM |

**Gaps to address:**
- Gateway capabilities (streaming tool calls, tool_choice, vision, rate limits) for GPT-5.6 Luna, DeepSeek V4 Flash, Qwen3.8 27B: confirm in Phase 0 spike.
- English vs Hindi/Hinglish: **resolved 2026-10-13 — English only for v1**; Hinglish may be added later (keep faster-whisper multilingual-capable).
- Headphones vs laptop-speaker barge-in: **resolved 2026-10-13 — headphones for v1**; speaker-mode AEC becomes a later enhancement.
- Cartesia free tier (~25 min/month; 20K credits, 1 credit per char): local voice is primary; build meter and fallback in Phase 2; ask about Cartesia Pro (~$5/mo, 100K credits) once usage is measured.
- Telegram vs ntfy: Telegram recommended for two-way replies; not end-to-end encrypted; keep messages minimal.
- WhatsApp (user decision): keep out of v1; if built later, feature-flagged, off by default, spare number, verify Meta terms.
- Claude subscription login in SDK products: Snow spawns only the user's own `claude`, never reads its tokens; confirm policy before Phase 5.
- Antigravity (MEDIUM-LOW): young ACP server; soft-denies approvals headless; user decision whether v1 adapter.
- Measured numbers not yet available: each is a time-boxed spike in its phase; no figure here is measured.
- ntfy CVE-2026-39087: sources conflict; verify via NVD; prefer Telegram v1.

## Sources

Aggregated from the four research files (accessed 2026-10-13). Primary (HIGH): PyPI/npm registries; Claude Agent SDK and headless docs; Pipecat repo and docs; Cartesia docs and pricing; Chrome remote-debugging blog; Tauri v2 docs; Tailscale Serve, ntfy, Telegram API changelog; postprocessing ASCIIEffect source; Microsoft Learn agentic security; Microsoft UIPI/UIAccess docs; Willison lethal trifecta post; LiteLLM security update. Secondary (MEDIUM): ACP site; OpenCode docs; Antigravity headless docs; faster-whisper and openWakeWord repos; CAM++ and ECAPA papers; Windows-MCP repo; claude-remote-approver README; LiveKit docs; AssemblyAI article; Claude Code voice/mobile docs; speaker-spoofing papers; Göttingen wake-word study. Tertiary (LOW): hobbyist wake-word reports; Picovoice AccessKey end date (forum); WhatsApp vendor blogs; CSA auto-mode note (contested); Tauri vs Electron footprint blogs; JarvisAi repo; Parakeet/Moonshine vendor figures; Windows platform behaviours not re-verified.

*Research completed: 2026-10-13. Ready for roadmap: yes.*
