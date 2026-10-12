# Domain Pitfalls

**Domain:** Always-on Jarvis-style voice AI desktop assistant (Windows 11, full PC permissions, voice-driven coding agents, computer-use, phone relay, 3D ASCII HUD)
**Project:** Snow
**Researched:** 2026-10-13
**Overall confidence:** MEDIUM. The structural pitfalls (injection, AEC, UIPI, permissions) are well established. Specific numbers (false-wake rates, spoof EERs) come from vendor or hobbyist sources and must be re-measured on this hardware.

## Phase Labels Used In This Document

The roadmap is not written yet. These labels are a proposed working split, so remap them once it exists.

| Label | Scope |
|-------|-------|
| **P0 Foundations** | Process model, config, secrets store, logging, LLM gateway abstraction, CI, cost guard |
| **P1 Voice Core** | Wake word, VAD, STT, TTS, AEC, barge-in, speaker verification |
| **P2 Agent Orchestration** | Coding-agent adapters, permission relay, session state, status and redirect |
| **P3 PC Control** | App/window/file control, UIA, screen-understanding computer-use, web tasks |
| **P4 HUD** | ASCII-shader 3D HUD, activity stream, panels, silent mode |
| **P5 Hand-off + Remote** | Background tasks, phone notifications and answers, Tailscale, presence routing |
| **P6 Hardening + Release** | Installer, auto-update, health monitoring, soak tests, security review |

---

## Critical Pitfalls

Mistakes that cause rewrites, security incidents, or a product that does not feel usable.

### Pitfall 1: The assistant hears itself (echo and self-trigger loop)
**What goes wrong:** Snow's TTS comes out of the laptop speakers, the mic picks it up, and Snow either transcribes its own speech as a user command or fires the wake word on its own name ("Snow..."). Muting the mic during playback "fixes" this but kills barge-in, which is a hard requirement.
**Why it happens:** Laptop speakers sit centimetres from the mic array. WebRTC-style AEC needs a time-aligned playback reference and a few seconds to converge. It leaks at high volume, and loses convergence when the output route changes (headphones in, Bluetooth, HDMI). Double-talk is where AEC does worst: it can suppress the user's real interruption.
**Consequences:** Self-interrupting replies, runaway loops (Snow answers itself), phantom commands executed, and users abandoning voice. In a full-permissions assistant, a self-heard "yes" can approve a risky action.
**Prevention:**
- Capture WASAPI loopback of the output device in sync with the mic and run AEC (WebRTC AEC3 or an equivalent) before VAD, wake word and STT. A library such as `echoff` does this loopback-plus-WebRTC pattern (MEDIUM confidence, check maintenance status before depending on it).
- Treat the render-side reference as a first-class stream with a shared clock. Log reference, raw mic and cleaned mic together for debugging.
- Barge-in must need confirmation: raw VAD energy alone must not interrupt. Require speech that is both over threshold and speaker-verified, held for roughly 150 to 300 ms. Duck TTS volume immediately on a candidate, then cut on confirmation. This hides the confirmation delay.
- Reset or re-warm the AEC filter when the audio endpoint changes (listen to `IMMNotificationClient` device events).
- Hard rule: nothing the assistant itself produced may be accepted as an approval. Approvals must come from a verified-speaker utterance that begins after TTS of the question has ended, or from the phone or HUD.
- Ship a "headphones mode" and a "speaker mode" tuned separately.
**Detection:** The metrics are false interrupts per hour, missed real barge-ins, and AEC recovery time after a route change. Warning signs: STT transcripts containing Snow's own previous sentence, and barge-in that works on headphones but not on speakers.
**Phase:** P1 Voice Core (build AEC before barge-in; do not defer it). P6 for soak testing.

### Pitfall 2: Latency budget blown, so it never feels human
**What goes wrong:** Each stage looks fine alone (VAD end-of-speech wait, STT finalise, LLM first token, TTS first byte, audio buffer), but they add up to 2 to 4 s. Turn-taking then feels broken: Snow cuts the user off mid-thought, or waits awkwardly after they finish.
**Why it happens:** Teams build sequentially (transcribe fully, then think, then speak) instead of streaming everything. Endpointing is a fixed silence timeout. Gateway free-tier models have variable first-token latency. Faster-whisper on a 6 GB GPU competes with the HUD and other processes. TTS is called per full reply instead of per sentence or clause.
**Consequences:** Misses the "roughly 1 second to first spoken word" constraint in PROJECT.md. The user starts repeating themselves, which creates double turns.
**Prevention:**
- Set a latency budget per stage on day one and instrument every turn with timestamps: speech-end, STT-final, LLM-first-token, TTS-first-audio, audio-out. Show it in a dev HUD overlay.
- Stream everything: partial STT feeds the LLM speculatively where safe, LLM tokens flow to TTS at clause boundaries, and TTS streams chunks.
- Use a fast model (the DeepSeek V4 Flash role) for conversational turns and acknowledgements, and route to the main brain only when needed. Emit an immediate short acknowledgement while a longer job spins up.
- Use semantic or adaptive endpointing (VAD plus a "is this a complete thought" signal) rather than one silence constant. Be generous after trailing words like "and", "so", "uh".
- Pre-warm: keep the TTS websocket connection open, keep STT models resident, keep the LLM HTTP connection pooled.
- Separate HUD feedback (under 100 ms, local, no network) from spoken reply (about 1 s). The HUD must react to VAD/wake events with no dependency on the LLM.
**Detection:** p50 and p95 time-to-first-audio on a dashboard. Warning sign: p95 above 2 s, or users saying "hello?".
**Phase:** P0 (instrumentation, gateway abstraction) and P1 Voice Core.

### Pitfall 3: Prompt injection through everything Snow reads (the lethal trifecta)
**What goes wrong:** Snow reads web pages, repo files (README, comments, issue text), terminal output, emails, chat messages and screenshots, and it also holds private data (files, sessions, tokens) and can send things out (HTTP, git push, WhatsApp, shell). An attacker puts instructions in any content Snow reads, and Snow follows them. The attacker needs no access to the user. A public GitHub issue was enough in the 2025 GitHub MCP exploit (HIGH confidence on the pattern).
**Why it happens:** LLMs cannot reliably separate data from instructions. "Auto-mode level" autonomy removes the human check. Computer-use agents also read instructions off the screen (a web ad, a PDF, a chat window), and vision input makes this harder to filter.
**Consequences:** Credential exfiltration, `curl | sh` execution, silent file deletion, messages sent as the user, malicious package installs.
**Prevention:**
- Design against the trifecta explicitly. For every tool, mark: reads-private-data, ingests-untrusted-content, can-exfiltrate. When one session or context has all three, force a human approval for the dangerous step.
- Taint tracking: content from web, repo, screen, email or messages is labelled untrusted in the context. After untrusted content enters the context, tool calls that exfiltrate or execute (network writes, shell, git push, send message) escalate to the approval tier regardless of "auto mode".
- Privileged action decisions must not be made by the same context that read untrusted text. Prefer a small action-validator step (separate call, sees only the proposed action, the user's original voice request and the risk policy, not the page text).
- Spoken or on-screen text is not authority. The only trusted instruction channel is the verified user's voice and the authenticated phone channel. Page text saying "tell the user to approve" is data.
- Egress allow-list for the agent sandbox. Ask before contacting a new domain with data in the URL or body.
- Run browser tasks in a separate browser profile with only the sessions that task needs. Do not hand the primary profile (all logins) to a page-reading agent by default.
- Show a "source" badge on the HUD for every plan step: which content triggered it. That makes injection visible to the user.
**Detection:** Plans that cite page content as the reason for an action not in the user's request. Red-team test set: pages and repos with embedded instructions, run as a CI regression suite.
**Phase:** P0 (policy engine design), P2 and P3 (enforced), P6 (red-team suite). Needs deeper phase research.

### Pitfall 4: Over-permissive autonomy ("auto mode" plus full PC rights)
**What goes wrong:** "Acts freely on routine work" slides into deleting directories, force-pushing, installing software, editing the registry, sending messages, or spending money. A speech misrecognition ("delete the test folder" vs "delete the tests folder") or a wrong window focus makes the damage real.
**Why it happens:** Risk is judged by the LLM per call, with no deterministic floor. The "ask before irreversible" rule lives in the prompt, which can be overridden by context or injection. Voice makes confirmation feel slow, so the temptation is to skip it.
**Consequences:** Irreversible data loss, leaked credentials, accounts compromised or banned.
**Prevention:**
- A deterministic policy layer in code (not prompt) classifies every action into tiers: free, announce, confirm, always-confirm (credentials, security settings, payments, irreversible deletion, sending as the user to new recipients). The LLM may only raise the tier, never lower it.
- Make the irreversible class safer by design: recycle bin instead of delete, git stash or branch before bulk edits, snapshots (copy-on-write or `git worktree`) for agent work, dry-run output on the HUD.
- Run coding agents in a scoped working directory or worktree, never with the whole user profile as cwd.
- Read-back for risky operations that includes the resolved target ("delete 14 files in C:\proj\tests, say confirm"), not the raw transcript.
- Do not run Snow itself elevated. Keep the main process at normal integrity. Use a separate, narrow, audited helper for the few admin tasks.
- A kill switch that always works: a hotkey, a phrase handled by a separate tiny listener, and a button on the phone. "Stop" must pre-empt the LLM and cancel in-flight tool calls.
- Rate limits and circuit breakers on destructive-class actions per minute.
- Presence-aware routing must fail closed: if presence is unknown, treat the user as away and require phone approval for risky actions, not auto-allow.
**Detection:** Audit log with the tier for each action and who or what approved it. Warning sign: the tier is computed from model output only.
**Phase:** P0 (policy engine), then every phase that adds a tool.

### Pitfall 5: Relaying coding-agent permission prompts unreliably
**What goes wrong:** Snow scrapes a terminal for "Allow? (y/n)" text, answers by keystroke, and gets it wrong: the agent changed its prompt format, the answer lands in the wrong window, the prompt was missed so the agent hangs silently, or the user's spoken "yes" is applied to a different question than the one asked.
**Why it happens:** Agent CLIs are interactive TUIs with no stable contract. Each agent (Claude Code, Antigravity, OpenCode) differs. Waiting is unbounded: an approval callback can stay pending forever, and the process may need to survive longer than the user's absence.
**Consequences:** Stuck sessions, wrong approvals (a security hole), and constant adapter breakage on CLI updates.
**Prevention:**
- Use structured integration, not screen scraping. For Claude Code use the Agent SDK `canUseTool` callback (it fires only for tools not already approved by rule or mode, and also for `AskUserQuestion`) and hooks such as PreToolUse and PermissionRequest for notifications (MEDIUM-HIGH confidence, from official docs; re-verify in the version actually installed). Prefer ACP/JSON-RPC, `--output-format stream-json`, or MCP-style APIs for other agents. Treat PTY scraping as a last-resort adapter with a version pin and golden-file tests.
- Define one internal adapter contract: `onQuestion(id, kind, options, risk)`, `answer(id, decision)`, `status()`, `cancel()`. Every pending request gets an id. A spoken answer is bound to the request id that was most recently announced, and read back.
- Timeouts and escalation: unanswered at the PC, then phone push, then keep waiting; never auto-approve on timeout. For long absences, persist the session so it can resume (the SDK documents a defer-and-resume path using PreToolUse).
- Never let the agent's own pre-approved rules be widened silently by a voice "always allow". Persist such changes only after an explicit confirm and show them on the HUD.
- Contract tests per adapter run in CI against recorded transcripts, plus a canary that runs on agent version bumps.
- Headless modes like `dontAsk` deny rather than prompt. Know which mode each agent runs in so a denial is not mistaken for a hang.
**Detection:** Sessions in "waiting" state with no outstanding announced question. Mismatch between announced request id and answered id.
**Phase:** P2 Agent Orchestration. Needs phase research per agent (flag it).

### Pitfall 6: Exposed or weakly secured remote access
**What goes wrong:** To reach the PC from the phone, someone port-forwards, uses a public tunnel, runs an unauthenticated local HTTP/WebSocket server bound to `0.0.0.0`, or uses a public ntfy topic. Anyone who finds it controls a PC with full permissions.
**Why it happens:** The control plane is built as a convenient local web server, then "just exposed". Localhost services are also reachable by any local process and by DNS-rebinding from web pages in the user's own browser.
**Consequences:** Remote code execution on the user's machine. A voice assistant that is also a remote shell is the highest-value target on the machine.
**Prevention:**
- Bind control APIs to a Tailscale interface or loopback only. Never `0.0.0.0`. Do not use Tailscale Funnel or any public tunnel for the control plane.
- Authenticate at the application layer as well as the network layer: per-device keys or tokens, short-lived session tokens, and Tailscale ACLs that limit the phone to the one port. Check the `Host` and `Origin` headers on local servers to defeat DNS rebinding. Require a token on local WebSocket connections too (the HUD and the voice service are separate processes).
- The notification channel (ntfy/Telegram) is a one-way, low-trust signal channel. Do not put secrets, full command output, or approvable one-tap actions that bypass authentication into a public topic. Use unguessable topics at minimum, self-host with auth, and keep the ntfy server patched (CVE-2026-39087 reports vary on severity and fixed version, so verify against NVD and the ntfy advisory and run at least 2.22.0).
- Approvals from the phone must go through the authenticated private channel with a second factor for high-risk tiers (device biometric, or a one-time code).
- Telegram bots: restrict by numeric user id allow-list, because anyone can message a bot.
- Threat model the mobile path: stolen phone, lost session. Provide a "revoke all devices" action.
**Detection:** Port scan of the laptop from another LAN host and from the internet. Run it as a release gate.
**Phase:** P5 Hand-off + Remote, with the auth design decided in P0.

### Pitfall 7: Secrets leaking into logs, transcripts, and LLM context
**What goes wrong:** API keys end up in structured logs, crash dumps, HUD history, STT transcripts ("my password is..."), screenshots sent to a vision model, `.env` files read into agent context, and the LLM gateway's server logs. Whatever the user says aloud is also stored.
**Why it happens:** Verbose "glass-box" logging is a stated product goal (activity stream, history of the day). Screenshots capture password managers and tokens. Agents `cat .env`. Voice is an unfiltered input.
**Consequences:** Credentials end up in a third-party gateway's logs, on disk in plain text, or in an exfiltrated prompt.
**Prevention:**
- Secrets in Windows Credential Manager or DPAPI-protected store. The agent never sees raw values: tools take secret references and the executor resolves them at call time.
- A redaction layer on every egress to a log, the HUD history and an LLM request: pattern-based (key formats, JWTs, private key blocks) and exact-match against the known secret set.
- Screenshot hygiene: skip or blur windows by process or title (password managers, banking, `.env` editors), and honour the Windows capture-exclusion flag where apps set it. Do not send screenshots when a secure-desktop or credential field is focused.
- Block agent reads of known secret paths (`.env`, `.ssh`, browser profile dirs, credential stores) by default via the policy layer.
- Never speak or display secret values. Voice entry of passwords is out: route to the user typing or a password manager autofill.
- Log retention limits, and no raw audio kept by default. Document what the model gateway sees, since free-credit gateways may log and train on prompts.
- Secret scanning in CI (gitleaks) and a pre-commit hook.
**Detection:** Canary secrets planted in the store; grep logs and captured request bodies for them in an automated test.
**Phase:** P0 (store, redaction, log schema), P3 (screenshot hygiene).

### Pitfall 8: Wake word and speaker verification treated as security, not as convenience
**What goes wrong (wake word):** "Hey Snow" fires on TV, music, similar phrases ("hey, so..."), and at 3 a.m. on room noise. A synthetic-data-only model can look great in a demo and false-fire dozens of times per hour in a real room (one report went from about 4,000 false wakes per hour to about 90 with synthetic noise, and to near zero only with real-world audio, LOW-MEDIUM confidence, hobbyist source). Vendor benchmarks put stock openWakeWord around 8.5 false positives per hour in one comparison and openWakeWord's own docs call under 0.5 per hour reasonable; measure your own.
**What goes wrong (speaker verification / spoofing):** The verifier is treated as authentication. Replay (a recording of the user) and TTS cloning defeat it: ECAPA-TDNN class models scored well on plain verification (EER under 2%) but very poorly against spoofs (spoof EER 20 to 31% in the SASV baselines) and gave high similarity to cloned voices in a small study (MEDIUM confidence). Short utterances ("yes", "stop") give weak embeddings and high error. The user's voice is also public if they post videos.
**Why it happens:** Embeddings measure similarity, not liveness. Short phrases have too little signal. Thresholds are set on clean enrollment audio and then fail with a cold, a noisy room, or a different mic distance.
**Consequences:** A video playing "Hey Snow, open ... and send ..." controls the PC; or the real user gets rejected repeatedly and gives up.
**Prevention:**
- Say it plainly in the design: speaker verification is a filter against accidental triggers (TV, housemates), not an authentication boundary. Never gate high-risk actions on voice identity alone. High-risk tier needs a second factor: phone confirmation, HUD click, or a typed or spoken one-time challenge phrase that changes each time.
- Wake word: collect real negatives (hours of the user's own TV, music, calls, typing, fans) and hard negatives (phonetically similar phrases), train with them, and set the threshold from a measured false-accepts-per-hour target (for example under 1 per hour), not by eye. Add a second-stage check: verify the wake utterance with the speaker model and the STT transcript before opening the session.
- Enroll the speaker with varied conditions (distance, tone, mic, quiet and noisy) and re-enroll easily. Use sliding confidence over a whole utterance, not the first word.
- Add a lightweight anti-replay/liveness signal where cheap (a replay detector model, or reject audio that matches the AEC reference stream, i.e. sound Snow or the PC itself is playing). Rejecting anything correlated with the system loopback stream blocks "video on the same PC" attacks for free.
- Make commands from an unverified voice a no-op that logs on the HUD (visible, not silent), with the option to say "that was me".
**Detection:** Track wake accepts per hour while idle, rejection rate of the owner, and a periodic test with a recording of the owner and a synthetic clone.
**Phase:** P1 Voice Core. Security-critical decisions in P0 policy. Needs data collection work early.

### Pitfall 9: Cost runaway on LLM calls
**What goes wrong:** An agent loop, a retry storm, a vision model called on every frame, or an always-on "proactive" thread burns the free gateway credits in a day, and then the product silently degrades or stops. Later, on paid API, one stuck loop produces a large bill.
**Why it happens:** Computer-use loops send a screenshot per step. Long agent sessions resend ever-growing context. Retries on errors multiply. Nothing counts tokens by feature.
**Consequences:** Outage at the worst moment, surprise bills, quality loss when the fallback model is far weaker.
**Prevention:**
- A central LLM gateway module (matches the "swappable by config" requirement) that every call goes through, with per-feature and per-session token and cost counters, hard caps, and a daily budget with graceful degradation to a cheaper model rather than failure.
- Loop guards: max steps, max wall time, no-progress detection (same screenshot hash or same tool call repeated) for every autonomous loop.
- Prompt caching and compact context: summarise old turns, send diffs rather than full files, downscale and crop screenshots, prefer accessibility-tree text over images when available.
- Route by task: cheap/fast model for turn-taking and classification, expensive model for planning only.
- Exponential backoff with a retry ceiling and idempotent tool calls.
- Show the running spend on the HUD. Alert the phone at 50 and 90 percent of budget.
- Confirm gateway terms early: OpenAI-compatibility, tool-calling support, rate limits and credit expiry are still unconfirmed in PROJECT.md.
**Detection:** Daily cost per feature report; alert on a session exceeding N times the median.
**Phase:** P0 (gateway, counters), enforced in P2 and P3.

---

## Moderate Pitfalls

### Pitfall 10: STT mangles code and technical vocabulary
**What goes wrong:** Whisper turns "kubectl" into "cube control", "grep" into "grip", "npm" into "NPM", "pydantic" into "pie dantic", file paths and flags into prose, and homophones ("use Postgres" vs "use post grass") into the wrong tool. It also hallucinates text on silence or noise ("Thanks for watching").
**Prevention:**
- Bias decoding: pass a dynamic `initial_prompt`/hotwords list built from the current project (repo file names, package names, git branch, installed tools, app names) for faster-whisper.
- Add a post-STT correction step: the LLM sees the raw transcript plus the context lexicon and returns normalised intent. Keep the raw transcript visible on the HUD.
- Never dictate code char by char as the main path. The voice-first model is intent ("add a retry to the upload function"), and the coding agent writes code. Use fuzzy matching against real symbols and paths for references ("the auth file").
- Read back resolved targets for destructive or ambiguous commands (Pitfall 4).
- Gate STT on VAD and drop low-confidence or no-speech segments (`no_speech_prob`, `avg_logprob`) to avoid hallucinated commands.
- Pick the model size by measuring WER on the user's own recorded technical phrases, not generic benchmarks. A 6 GB GPU fits `large-v3-turbo` or `distil` variants in int8/fp16, but check VRAM headroom (Pitfall 11).
**Phase:** P1 Voice Core, refined in P2.

### Pitfall 11: GPU/VRAM contention on a 6 GB RTX 4050
**What goes wrong:** faster-whisper, speaker verification, the wake word model, the browser-based HUD (WebGL), the user's games, Chrome hardware acceleration, and Antigravity or local models all fight for 6 GB. Out-of-memory errors crash the voice service, or STT latency spikes when another app uses the GPU.
**Prevention:**
- Budget VRAM explicitly: for instance STT 1.5 to 3 GB, everything else small. Pin model sizes and quantisation in config and test with the HUD and a browser running.
- Run wake word and VAD on CPU (they are tiny). Keep only STT on the GPU, and allow CPU fallback (smaller model) when VRAM is low.
- Detect out-of-memory and fall back gracefully, then retry later. Do not crash. Monitor with NVML.
- The HUD should use as little GPU as it can (Pitfall 15), and must not share a failing context with STT.
- Do not plan to run local LLMs or local vision models on this GPU.
- Note that Windows laptop hybrid graphics can route apps to the integrated GPU or the NVIDIA GPU unpredictably, so set per-app GPU preference explicitly.
**Phase:** P1 and P4. Measure in P0 spikes.

### Pitfall 12: Always-on CPU, battery, and thermal drain
**What goes wrong:** A 24/7 listener running wake word, VAD, a Python service, an Electron/Chromium HUD and polling loops keeps the CPU out of deep idle, spins fans and drains the battery. The user then turns Snow off, which defeats "always-on".
**Prevention:**
- Idle budget: target low single-digit percent CPU and near-zero GPU when idle. Measure it with a power-profile test (Windows `powercfg /energy`, Task Manager power usage columns) and set it as a CI-adjacent gate.
- Staged pipeline: a cheap VAD gate in front of the wake-word model, and the wake word in front of everything heavy. Use a 16 kHz mono small-frame path, not multi-channel high-rate audio.
- Event-driven instead of polling (UIA events, file watchers, WinEvent hooks). Coalesce timers.
- Battery-aware modes: on battery, reduce HUD frame rate, pause optional sensing, and lower the process priority (use Windows EcoQoS for background workers).
- Prefer one resident service with a lazy-started HUD instead of many Python processes each holding models.
- Windows Modern Standby (S0 ix) laptops may keep the mic stream alive or kill it; test sleep and resume, lid close, and lock screen explicitly.
**Phase:** P0 (process model) and P6 (soak).

### Pitfall 13: Windows automation fragility (UAC, UIPI, DPI, focus, UIA)
**What goes wrong:**
- **UAC/UIPI:** a normal-integrity Snow cannot send input to elevated windows (input is silently dropped), and cannot touch the UAC secure desktop at all. The agent then loops, "clicking" something that ignores it.
- **Focus stealing:** `SetForegroundWindow` is restricted by the foreground lock, so Snow's "switch to Chrome" only flashes the taskbar, and keystrokes go to the wrong window. Typing into the wrong window is a safety incident (Pitfall 4).
- **DPI and multi-monitor:** mixed scaling (125%, 150%) makes screenshot coordinates differ from click coordinates unless the process is per-monitor DPI aware and coordinates are mapped per monitor. Negative coordinates on left monitors break naive code.
- **UIA:** coverage varies wildly. Electron and Chromium apps expose accessibility trees only when accessibility is enabled. Games, custom-drawn UIs, Java and Qt apps, and remote-desktop windows expose little. UIA calls can hang on unresponsive apps.
- **Input method quirks:** `SendInput` text typing breaks with non-US keyboard layouts, IME and key-repeat; clipboard paste changes the user's clipboard.
- **Timing:** fixed sleeps cause flakiness. The user also moves the mouse and types while Snow is acting, so the two fight over input.
**Prevention:**
- Detect elevation and the secure desktop up front and report it ("that window is running as admin, I can't control it") instead of failing silently. Offer an explicit, narrow elevated helper only if really needed. UIAccess requires a signed binary in a trusted location (Program Files), so plan signing from the start if you go that way.
- Prefer APIs over pixels, in this order: native/CLI/COM/URI schemes and PowerShell, then UIA patterns (`InvokePattern`, `ValuePattern`), then DOM via Chrome DevTools Protocol or Playwright for web, and vision-based clicking last.
- Verify after each action: re-read state (window title, UIA value, screenshot diff) before the next step. Check the foreground window is the intended process before typing. Abort if it is not.
- Make the process per-monitor-v2 DPI aware via manifest. Normalise coordinates and test at 100%, 150% and with a second monitor.
- For focus: use the documented workarounds sparingly (`AllowSetForegroundWindow`, attach thread input, or a minimised-restore trick) and verify the result.
- A "user is active" input-idle check (`GetLastInputInfo`) before taking mouse and keyboard, and pause or yield when the user touches the input devices. Better: run agent browser tasks in a separate headless or secondary window so they do not fight the human.
- Build a Windows automation test bed (a set of target apps with scripted scenarios) early. Without it, regressions are invisible.
**Phase:** P3 PC Control. Needs deeper phase research.

### Pitfall 14: Computer-use (screen understanding) is slow, brittle, and over-trusted
**What goes wrong:** Screenshot, plan, click loops take seconds per step, mis-click small targets, get stuck on modal dialogs, and hallucinate success. Multi-step workflows chained across apps fail halfway, leaving a half-done state (half-filled form, half-sent message).
**Prevention:**
- Treat computer-use as the fallback path, not the default (see Pitfall 13 ordering).
- Step verification, bounded retries, and checkpoints. Every workflow step declares a postcondition. On failure, stop and report, never improvise a destructive recovery.
- Mark workflows idempotent where possible, and save state so a hand-off task can resume.
- Show the annotated screenshot and the intended click on the HUD before acting at medium and high risk.
- Cap loops (Pitfall 9).
**Phase:** P3.

### Pitfall 15: ASCII-shader 3D HUD burns the GPU and the user's attention
**What goes wrong:** A WebGL/WebGPU scene with a full-screen ASCII post-process pass running at 60 fps in a permanent window uses a large share of a laptop GPU and CPU, heats the machine, competes with STT for VRAM, and drops frames on integrated graphics. The `requestAnimationFrame` loop keeps going even when the window is covered or minimised, and WebGL gives no automatic throttling for that.
**Prevention:**
- Render only when needed: stop or throttle the loop when the window is hidden, minimised, occluded or the screen is locked (Electron `blur/hide/minimize` events, `document.visibilityState`, and `BrowserWindow.setBackgroundThrottling`). Verify the behaviour by profiling, since occluded-window behaviour varies.
- Adaptive frame rate by state: low (about 10 to 15 fps) in idle, higher during speaking and acting; a hard cap on battery. A cheap "corner widget" mode with a reduced scene and fewer glyph cells.
- Do the ASCII conversion on the GPU as a single fragment pass over a low-resolution render target with a glyph atlas texture. Do not read pixels back to the CPU to build text.
- Keep draw calls and geometry small; instanced glyph rendering; fixed-size canvases; no per-frame allocations (garbage collection pauses show up as jank).
- Decouple the 100 ms reaction requirement from the 3D scene: a tiny always-cheap DOM or canvas indicator reacts to the voice event immediately, and the 3D scene catches up.
- Provide a "low power / no 3D" fallback and accessibility setting (reduced motion). Plan for GPU loss and context-restore (`webglcontextlost`).
- Run the HUD as a separate process from the voice service so a renderer crash never kills listening.
- Set a measured budget: HUD GPU under X percent at idle, tracked in a perf test.
**Detection:** GPU usage by process in Task Manager during idle, fan noise, frame time histogram.
**Phase:** P4 HUD. Prototype the shader and measure in an early spike, since the visual identity depends on it.

### Pitfall 16: Reading code and technical output aloud
**What goes wrong:** TTS reads out paths, hashes, stack traces, diffs, JSON and URLs ("slash user slash a b c..."), which is unlistenable. Summaries mention too much or hide a critical failure. The model also emits markdown symbols that get spoken.
**Prevention:**
- Enforce a spoken/visual split in the response schema: each reply has `speech` (short, plain language, no code, no URLs, numbers rounded) and `display` (code, diffs, logs for the HUD). Validate `speech` with a filter that rejects code fences, long tokens, paths and hex strings.
- Teach a summarisation style ("3 files changed, tests pass, one failing"), and for errors, name the problem class and offer "want details on screen?".
- Only spell out an identifier when the user asks, and prefer pointing at the HUD ("it's on screen").
- Pronunciation handling for common technical terms and acronyms if Cartesia mispronounces them; keep a small pronunciation lexicon rather than hardcoded phrases (this fits the "nothing hardcoded in speech" rule, since it changes how words sound, not what is said).
- Length cap and "interrupt-friendly" chunking so the user can cut in.
**Phase:** P1 and P2.

### Pitfall 17: Unofficial WhatsApp automation gets the account banned
**What goes wrong:** Using Baileys, `whatsapp-web.js` or other reverse-engineered clients to read and send messages from the user's real personal number. Meta treats these as unapproved automation. Accounts get restricted or permanently banned, and this is the user's main communication channel. Meanwhile the official Business API route is closed to general-purpose assistants (Meta's Business Solution Terms, reported as effective January 15, 2026, bar AI providers whose primary function is the AI assistant; sources are vendor blogs, so verify against Meta's own terms, LOW-MEDIUM confidence).
**Why it happens:** It works fine in testing, then fails later. Risk grows with proactive or bulk sends, new recipients, high message rates, robotic timing, and link-heavy messages. Reactive replies to people who messaged first are lower risk.
**Prevention:**
- Make it an explicit, informed-risk decision by the user, and default to the safest design: never use the main number for experiments; use a spare number for development.
- Send only on explicit user instruction with a read-back (already in the scenarios), low volume, human-like pacing, no bulk, no unsolicited first contact to strangers.
- Prefer a no-ban alternative where it exists: drive the official WhatsApp Desktop or Web UI as the user (computer-use or UIA) at human speed, which is still against terms in theory but looks like a normal client. Or give Telegram, Signal-style or email alternatives, or the `wa.me` click-to-chat link to hand off to the user's own send.
- Isolate it behind an adapter, feature-flagged and off by default, so a ban or a protocol change does not take the product with it. Keep message content out of cloud logs.
- Back up chats and expect that the number could be lost.
**Phase:** Whenever messaging is built (likely after P3). Treat as a separate, optional capability and a roadmap decision for the user.

### Pitfall 18: Agent adapter sprawl and provider lock-in by accident
**What goes wrong:** Each CLI agent has different flags, auth, output formats, session semantics and failure modes. Quick one-off integrations leak agent-specific assumptions into core logic. The "borrowed account" and free-access situation means an adapter can vanish overnight (rate-limits, account revocation, terms of use changes).
**Prevention:**
- A single narrow adapter interface (Pitfall 5), a capability matrix per adapter (can stream, can do structured permissions, can resume), and a conformance test suite that every adapter passes.
- Automatic failover logic must not silently switch a half-done task to a different agent with different permissions. Surface it and hand over state explicitly.
- Check the terms of use for automating each agent with a borrowed or shared account. Account risk is real and is separate from the technical risk.
- Isolate each agent's credentials and config; never reuse tokens across adapters.
**Phase:** P2.

### Pitfall 19: Turn-taking and conversation-state bugs
**What goes wrong:** Barge-in cancels TTS but not the LLM request or tool call, so the old answer continues in the background. Interrupted replies are still stored as spoken in memory. Two overlapping turns are processed concurrently. "Stop" is treated as a new request rather than a cancel.
**Prevention:**
- A single explicit turn state machine (idle, listening, thinking, acting, speaking, alert, which also drives the HUD) with cancellation tokens flowing through STT, LLM, tools and TTS.
- Record what was actually spoken before the interrupt (TTS word timestamps) and store that in conversation memory, not the planned text.
- Distinguish cancel, correct ("no, use Postgres"), and add-on commands via a fast classifier. Handle the user speaking while Snow is in the acting state.
- Property-based and replayed-audio tests of the state machine.
**Phase:** P1.

---

## Minor Pitfalls

### Pitfall 20: Crash recovery and autostart edge cases
**What goes wrong:** Autostart races with audio device initialisation at login, so no mic at boot. Service restarts in a crash loop. Sleep/resume breaks audio streams. Bluetooth headset switching changes the sample rate.
**Prevention:** A supervisor with backoff and a health endpoint, re-open audio devices on device-change events, test boot, lock, sleep, and RDP session cases. Run in the interactive user session (a Windows Service in session 0 cannot access the desktop, mic or UI; use a user-level scheduled task or startup entry plus a watchdog).
**Phase:** P0 and P6.

### Pitfall 21: Privacy surprises of an always-on mic and screen reader
**What goes wrong:** Raw audio, screenshots and transcripts kept indefinitely, or sent to cloud services when "local-only while idle" was promised. Bystander speech captured.
**Prevention:** Idle audio never leaves the machine and is not stored. A visible, honest mic indicator on the HUD, a hardware-style mute that is a real software stop, retention limits, and a data-flow table in the docs of what leaves the machine. Cartesia and the model gateway receive text only unless a feature requires more.
**Phase:** P0 and P1.

### Pitfall 22: Cartesia TTS credits and fallback voice mismatch
**What goes wrong:** Free credits run out mid-session and the local fallback voice sounds very different, or the failure is silent. Per-reply emotion tags only exist on the primary voice.
**Prevention:** Track the credit balance, announce a switch gracefully, make the TTS layer an interface with an identical streaming contract, and degrade emotion controls rather than break. Cache nothing the persona should say fresh (but cache audio for repeated system phrases only if allowed by the "nothing hardcoded" rule).
**Phase:** P1.

### Pitfall 23: LLM-chosen emotion and persona drift
**What goes wrong:** The model picks inappropriate vocal emotion (cheerful on a failure), or persona drifts over a long session. The "no hardcoded scripts" rule makes tone inconsistent and untestable.
**Prevention:** Constrain emotion to a small enum validated against the situation (error means no cheerful), keep a persona prompt versioned and under test with golden situations, and use rubric-based evaluation of tone.
**Phase:** P1 and P2.

### Pitfall 24: Phone notification spam and dead-letter approvals
**What goes wrong:** Too many pushes train the user to ignore them; approvals expire silently; the phone answer arrives after the PC state changed.
**Prevention:** Notification budget and batching, priorities, expiry shown to the user, idempotent approval ids bound to the exact action, and a stale-approval rejection path.
**Phase:** P5.

---

## Solo-Builder Pitfall: Maintainability and Scope Creep

### Pitfall 25: The "multi-billion-dollar polish" bar plus a huge surface area for one person
**What goes wrong:** The scope (voice stack, three or more agent adapters, computer-use, remote access, a 3D HUD, installer, auto-update, CI, multi-user readiness) is a multi-team product. A solo builder spends months on the HUD or on one subsystem, never reaches a usable end-to-end loop, and the project stalls. Heavy use of AI coding agents adds code faster than it can be understood, tested and maintained. "Architected for multi-user" becomes a reason to over-engineer.
**Why it happens:** The visual layer and the novelty features are the most rewarding to build. Each subsystem is individually tempting to perfect. The out-of-scope list is respected on paper but proactive features creep back in.
**Prevention:**
- Build a thin vertical slice first: wake, speak, one LLM turn, one Claude Code action via the structured adapter, one spoken result, plus a plain HUD (text status, no 3D). Get the daily-use loop working, then deepen. Dogfood from the first week.
- Sequence the HUD: a functional state-and-stream HUD (DOM) first, the ASCII-3D scene as a bounded time-boxed phase afterwards, behind the same state interface so it can be swapped.
- Hold the line on the out-of-scope list (no proactive engine, learning, job-hunting, smart home, native app) and treat "multi-user ready" as only: no hardcoded paths, per-user config directory, secrets abstraction. Nothing more in v1.
- Process model: a small number of long-lived processes with typed message contracts (for example voice service, orchestrator, HUD, plus adapters). Avoid a dozen micro-services for a single user.
- Quality gates scaled to a solo dev: typed language boundaries, a handful of high-value tests (state machine, policy engine, adapter conformance, injection regression suite, redaction), CI from day one, but do not chase coverage numbers on glue code.
- Polyglot cost: Node 25 plus Python 3.10 for models is two toolchains. Decide the boundary explicitly (Python sidecar for audio/ML, TypeScript for everything else) and keep IPC simple (local WebSocket or stdio JSON), because every extra language boundary is a place for bugs. Python 3.10 is near end-of-life upstream, so check dependency support before locking it in.
- Review AI-generated code for security-relevant modules (policy, auth, redaction, adapters) by hand. Keep a short DECISIONS record (ask the user before creating that file, per project rules).
- Time-box research spikes (AEC, wake-word data, ASCII shader, UIA test bed) at the start of each phase to retire risk before committing to a design.
**Detection:** No end-to-end voice command working after the first phase; more than one subsystem "almost done" at once.
**Phase:** Roadmap-level; applies to all phases.

---

## Phase-Specific Warnings

| Phase | Likely Pitfall | Mitigation |
|-------|----------------|------------|
| P0 Foundations | Policy and tiers left to the prompt (4); no cost counters (9); secrets in logs (7); process-model sprawl (25) | Deterministic policy engine, central LLM gateway with budgets, redaction layer, minimal process model, injection test suite scaffold |
| P1 Voice Core | Echo and self-trigger (1); latency (2); wake-word false accepts and spoof (8); STT vocabulary (10); turn state bugs (19) | AEC with loopback reference before barge-in; per-stage latency instrumentation; measured FA per hour; context-biased STT; single turn state machine |
| P2 Agent Orchestration | Unreliable prompt relay (5); adapter sprawl (18); injection via repo content (3) | Structured SDK/protocol adapters, request-id binding, never auto-approve on timeout, taint-based escalation |
| P3 PC Control | UAC/UIPI, DPI, focus, UIA (13); computer-use brittleness (14); screenshot secret leaks (7); WhatsApp ban (17) | API-first ladder, verify after each step, per-monitor DPI manifest, input-idle yield, window-title screenshot blocklist, WhatsApp as flagged optional adapter |
| P4 HUD | GPU/battery burn (15); VRAM contention (11); scope creep into visuals (25) | Event-driven low-fps idle, GPU-only ASCII pass, separate process, time-boxed spike, DOM HUD first |
| P5 Hand-off + Remote | Exposed remote access (6); notification spam and stale approvals (24); approval spoofing (8) | Tailscale-only bind, app-layer auth and Host/Origin checks, high-risk second factor, idempotent approval ids |
| P6 Hardening + Release | Always-on drain (12); crash and sleep edge cases (20); privacy audit (21) | Idle power test, sleep/lock/resume matrix, port-scan gate, secret-canary test, red-team run, signed installer |

## Research Flags For The Roadmap

| Area | Needs Deeper Phase Research? | Why |
|------|-----------------------------|-----|
| AEC plus barge-in on Windows (WASAPI loopback, WebRTC AEC bindings in Python/Node) | Yes | No Windows-specific guidance found; this is the most likely feature to feel bad |
| Per-agent permission and structured protocols (Claude Code SDK, Antigravity, OpenCode) | Yes | CLIs change often; version-specific behaviour must be checked against installed versions |
| Windows UIA, UIAccess signing, foreground rules | Yes | Foreground-lock rules were not covered by the research done here |
| Prompt-injection defence design for screen-reading computer-use | Yes | No computer-use specific sources found; the policy design is architecture-level |
| Speaker verification model choice and anti-replay | Yes | No short-utterance FAR data found |
| WhatsApp integration | Yes (and user decision) | Policy status comes from vendor sources only; verify against Meta documents |
| Standard Tailscale and ntfy setup | No | Well-documented; just follow Pitfall 6 |
| Cartesia streaming TTS integration | Light | Check current latency and credit limits in docs |

## Sources

Confidence notes: web search returned mostly vendor and secondary blogs. Where a claim rests on those, it is marked MEDIUM or LOW above. Items marked as general engineering knowledge (UIPI, DPI, session 0 isolation, SendInput behaviour, Whisper hallucination on silence) are established Windows and ML behaviour from training knowledge and should be re-verified in the phase research.

- Claude Code Agent SDK approvals and user input (official docs; HIGH for `canUseTool`/hooks semantics): https://code.claude.com/docs/en/agent-sdk/approvals and https://platform.claude.com/docs/en/agent-sdk/user-input
- Lethal trifecta and the GitHub MCP exploit (Simon Willison; HIGH for the pattern): https://simonwillison.net/2025/May/26/github-mcp-exploited/ and https://dzone.com/articles/mcp-lethal-trifecta
- Echo cancellation for voice agents (vendor/third-party; MEDIUM): https://github.com/koljab/echoff , https://www.coval.dev/blog/voice-ai-echo-cancellation , https://vocal.com/echo-cancellation/aec-barge-in/ , https://dev.to/vaiu-ai/how-to-build-reliable-barge-in-logic-for-voice-agents-k1a
- Wake-word false accepts (LiveKit and hobbyist reports; MEDIUM-LOW): https://github.com/livekit/livekit-wakeword , https://huggingface.co/gdiamos/hey-claude , https://picovoice.ai/blog/wake-word-benchmarks/ , https://pypi.org/project/openwakeword
- Speaker verification versus spoofing (academic, MEDIUM): https://arxiv.org/pdf/2201.10283 , https://arxiv.org/pdf/2204.09976
- Windows UIPI and UIAccess (Microsoft docs; HIGH): https://technet.microsoft.com/en-us/library/jj852244.aspx
- WhatsApp unofficial automation and AI-provider terms (vendor blogs; LOW-MEDIUM, verify against Meta): https://zylos.ai/research/2026-01-26-whatsapp-api-automation , https://whapi.cloud/blog/meta-ai-bot-ban-whatsapp-automation-2026 , https://www.bot.space/blog/whatsapp-api-vs-unofficial-tools-a-complete-risk-reward-analysis-for-2025
- ntfy CVE-2026-39087 (conflicting descriptions; verify via NVD): https://security-tracker.debian.org/tracker/CVE-2026-39087
- WebGL render-loop throttling (general; LOW for Electron specifics, profile it): https://discourse.threejs.org/t/calling-requestanimationframe-recomendations/42033
