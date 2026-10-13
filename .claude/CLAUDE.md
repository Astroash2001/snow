<!-- GSD:project-start source:PROJECT.md -->

## Project

**Snow**

Snow is an always-on, Jarvis-style personal AI that runs on the user's Windows laptop and reaches them on their Android phone. The user speaks ("Hey Snow…") instead of typing, and Snow does the work: it drives coding agents (Claude Code, Antigravity, OpenCode and others), operates the PC and any app on it, and shows everything it is doing on a living ASCII-rendered HUD. It is built for one user now, engineered so others could install it later, and held to the polish bar of a product shipped by a top-tier company.

**Core Value:** The user can do real, tangible work by voice alone: Snow understands the request, carries it out through coding agents and the PC, asks back by voice when it needs a decision, and visibly shows what it did — fully replacing the keyboard for the user's current way of working.

### Constraints

- **Budget:** free for now — runs on gateway credits; the user plans to pay for an API later — so the LLM layer must be swappable by configuration, not code
- **Provider independence:** no hard dependency on Claude, the Claude app, or any single account/provider — agent and model access come and go
- **Hardware:** 6 GB VRAM — local models limited to small ones (wake word, speech-to-text, speaker verification); large LLMs stay remote
- **Platform:** Windows 11 primary host; Android for mobile
- **Voice:** Cartesia TTS (free tier credits) with a local fallback voice when credits run out
- **Speech-to-text:** local (faster-whisper on GPU) for privacy and cost
- **Wake word:** local (openWakeWord, trainable on "Hey Snow")
- **Latency:** HUD feedback < 100 ms; spoken reply starts in roughly 1 second or Snow stops feeling human
- **Security:** voice + always-on + remote access + full permissions is a high-risk combination — speaker verification, approval tiers, authenticated tunnel and secret isolation are mandatory, not optional
- **Quality bar:** production-grade, "built by a multi-billion-dollar company" polish — clean, maintained, documented, tested

<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->

## Technology Stack

## Headline Decisions (read this first)

**User decisions on 2026-10-13 override the research text below wherever they conflict:**

- **Shell:** Electron is the v1 HUD shell, not Tauri. The Python 3.12 core and the TS/React HUD talk over a loopback WebSocket. Ignore the Tauri, Rust and MSVC install steps below unless the user later reopens this decision.
- **LLM gateway:** Experiential Labs, base URL `https://api.experientiallabs.ai/v1`, `Authorization: Bearer` key kept in local `.env` / Credential Manager, never committed. Roles: `gpt-5.6-luna` main brain and vision (do not send `temperature`), `deepseek-v4-flash` fast, `qwen3.8-27b` cheap vision.
- **Dogfooding:** from Phase 2, Snow drives Claude Code to build Snow. Snow runs from a pinned copy and never edits its running copy (CORE-06). Self-upgrade happens only on user approval, with rollback (CORE-07).

## Recommended Stack

### Runtime and Language Baseline

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| Python (uv-managed) | 3.12.x | `snow-core` runtime | Machine has 3.10.9. 3.12 is the sweet spot: Pipecat requires >=3.11, `onnxruntime` 1.31 requires >=3.11, `kokoro-onnx` requires <3.14, PyAudio 0.2.14 has Windows wheels through cp313, `ctranslate2` 4.8.2 has cp312 Windows wheels. Do not use the system 3.10. | HIGH |
| uv | 0.13.0 (reg; 0.11.8 installed) | Python/venv/lockfile manager | Installs and pins Python itself, hash-locked `uv.lock`, `uv sync --frozen`, workspaces. Replaces pip/venv/pip-tools/pyenv. Essential for the supply-chain posture below. | HIGH |
| Node.js | 25.x installed (use an LTS line for CI) | HUD build tooling | Already installed. Note Node 25 is a "Current" (odd) release, not LTS: pin CI to the active LTS and keep local on whatever builds cleanly. | MEDIUM |
| Rust (rustup, `stable-msvc`) + MSVC Build Tools | stable, >=1.90 for updater plugin | Tauri shell only | NOT installed on the machine (`rustc` not found). Tauri 2 needs "Desktop development with C++" Build Tools (multi-GB) and rustup. This is real onboarding cost; budget it in Phase 1. | HIGH |

### Process Topology (what runs where)

| Process | Language | Responsibility | Started by |
|---------|----------|----------------|------------|
| `snow-core` | Python 3.12 | Audio I/O, wake gate, VAD/turn, STT, speaker verify, LLM brain, tool/policy engine, agent adapters, memory, notifications, local WS/HTTP server | Task Scheduler "At log on" (restart on failure) + own watchdog |
| `snow-hud` | TS (React/R3F) in Tauri 2 | Rendering, activity stream, approvals UI, tray, global hotkey | Core launches/relaunches it; also autostart plugin as backup |
| Agent subprocesses | Node/Go/etc. (ACP servers, `claude` binary) | Actual coding work | Spawned by `snow-core` per session, env-scrubbed |
| Tool servers (MCP) | any | Playwright MCP, Windows-MCP, user-added | Spawned by `snow-core` via MCP client, always through the policy gate |

### Core Voice Pipeline

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| pipecat-ai | 1.12.0 (reg) | Real-time voice frame pipeline, interruption, turn-taking, LLM/TTS service wiring, RTVI events | De-facto open framework for voice agents in Python; 1.x is past the pre-1.0 churn; repo pushed daily. Verified in `pyproject.toml`: extras for `whisper` (faster-whisper ~=1.2.1), `kokoro` (kokoro-onnx), `mcp` (mcp>=2.1.1,<3), `local` (PyAudio), Silero VAD and Smart Turn v3.2 ONNX bundled. Interruptions on by default: a user-turn start cancels bot speech and in-flight work. Alternative LiveKit Agents (1.8.6) needs a LiveKit server/room model: overkill for a single local mic. | HIGH (existence), MEDIUM (fit; spike) |
| sounddevice | 0.5.6 (reg) | Own mic/speaker transport (WASAPI) | Pipecat's built-in local transport uses PyAudio (last release Nov 2023, but Windows wheels exist for cp312). Prefer a ~150-line custom `BaseInputTransport`/`BaseOutputTransport` on `sounddevice` for device selection, hot-plug handling, and feeding AEC reference audio. Fall back to the bundled PyAudio transport for the very first spike. | MEDIUM |
| livekit (rtc) | 1.1.20 (reg, Windows wheel) | `AudioProcessingModule`: WebRTC AEC3 + noise suppression + AGC | Only practical pip-installable WebRTC echo canceller on Windows. Needed so Snow does not hear itself (barge-in without self-interrupt). Frames must be exactly 10 ms; feed playback audio via the reverse stream. Known weakness: AEC3 silently gives ~0 dB if the echo path delay is >~500 ms or highly variable. Spike required (see Pitfalls). | MEDIUM |
| Silero VAD (bundled in Pipecat) | via pipecat-ai | Speech start/stop | Runs on CPU, <1 ms per 30 ms chunk. Pipecat pins `onnxruntime~=1.24.3`: keep this env on CPU onnxruntime. | HIGH |
| Smart Turn v3.2 (bundled ONNX, `LocalSmartTurnAnalyzerV3`) | via pipecat-ai | End-of-turn detection (semantic, not just silence) | Prevents cutting the user off mid-thought while keeping reply latency low; the default turn-stop strategy in Pipecat 1.x. Fallback: `SpeechTimeoutUserTurnStopStrategy(0.6)`. | HIGH |
| openWakeWord | 0.6.0 (reg; last release 2024-02-11, repo last push 2025-12-30) | Local "Hey Snow" wake word | The only maintained free, trainable, fully-local option. On Windows it runs on ONNX only (no tflite). Training uses synthetic TTS positives plus large negative sets; community reports the official Colab/auto-train is brittle on modern Python, so budget a dedicated "wake word training" task, pin the training env, and plan for a speaker-specific custom verifier (documented in `docs/custom_verifier_models.md`). Porcupine is out: Picovoice free tier AccessKeys ended 2026-06-30 (secondary source; confirm if you care). | MEDIUM |
| faster-whisper | 1.2.1 (reg, 2025-10-31; repo active 2026-10-12) with ctranslate2 4.8.2 | Local STT | User constraint and still the best-supported Whisper runtime on Windows+CUDA. Use model `turbo` (large-v3-turbo) with `compute_type="int8_float16"` (est. ~1.2-2 GB VRAM, derived from published large-v2 numbers: fp16 4.5 GB vs int8 2.9 GB; NOT measured on RTX 4050). It is not natively streaming: implement "VAD-segmented pseudo-streaming" (decode the growing utterance every ~300-500 ms for HUD partials, final decode at end-of-turn). Supports Hindi/Hinglish, which the English-only streaming models below do not. | HIGH (works), MEDIUM (latency; spike) |
| NVIDIA CUDA runtime wheels | `nvidia-cublas-cu12`, `nvidia-cudnn-cu12` (cuDNN 9) | GPU libs for ctranslate2 | ctranslate2 >=4.5 needs CUDA 12 + cuDNN 9. Install via pip wheels and `os.add_dll_directory(...)` rather than a system CUDA toolkit. Known Windows issues: driver 551/552 hang on CUDA model release (reported with int8_float16); test current driver. | MEDIUM |
| sherpa-onnx | 1.13.8 (reg) | Speaker embedding extraction (and optional keyword spotting / alternative ASR) | Pre-trained ONNX speaker-embedding models (3D-Speaker CAM++/ERes2Net, WeSpeaker ResNet) run on CPU with a tiny Python API and Windows wheels, avoiding the torch dependency of SpeechBrain. | MEDIUM |
| Speaker verification model | WeSpeaker ResNet34 (English VoxCeleb) or 3D-Speaker CAM++ via sherpa-onnx | "Only the user's voice commands Snow" | CAM++ reports 0.73% EER on VoxCeleb1-O with 7.2M params vs ECAPA-TDNN 0.89% with 14.7M (authors' numbers). Real accuracy depends on your mic and enrollment: calibrate the threshold on your own laptop-mic recordings plus TV/YouTube negatives. Short utterances (<1.5 s) are unreliable; verify the wake clip, then use a trust window across the follow-on turn. | MEDIUM |
| Cartesia TTS via Pipecat `CartesiaTTSService` (WebSocket) | model `sonic-3.6` (current; dated snapshot `sonic-3.6-2026-08-27` for stability) | Primary streaming voice | Current model per Cartesia docs. WebSocket endpoint supports contexts/continuations so LLM tokens stream in and `continue:false` finishes; one socket avoids per-turn TLS cost. Emotion is a per-request `generation_config.emotion` string (English only; best-supported: neutral, calm, angry, content, sad, scared; 60+ allowed values) plus inline SSML-style tags and `[laughter]`; speed 0.6-1.5, volume 0.5-2.0. Map the LLM's chosen emotion to this enum with validation, falling back to `neutral`. | HIGH |
| kokoro-onnx | 0.6.1 (reg) | Local fallback TTS | 82M-param model, best quality/size among permissively-licensed local options, runs on CPU in near real time, no VRAM contention with STT. Pipecat has a `kokoro` extra. Piper (`piper-tts` 1.8.0) is faster but is GPL (piper1-gpl): avoid if "others later" distribution matters. Chatterbox-Turbo needs ~6 GB VRAM: unusable alongside STT. | MEDIUM |

### LLM Orchestration and Tool Calling

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| openai (Python SDK) | 3.29.0 (reg) | OpenAI-compatible client for the gateway | Swappable by config: `base_url`, `model`, `api_key_ref` per role. Pipecat's `OpenAILLMService` accepts a custom base URL and handles streaming + function calls. Confirm gateway supports streaming tool calls, `tool_choice`, and image inputs (vision) before building on it. | HIGH |
| Model roles in config (`models.toml`) | n/a | brain (GPT-5.6 Luna), fast (DeepSeek V4 Flash), local-ish/other (Qwen3.8 27B), vision (TBD) | Never hard-code a model in code. Route: fast model for conversational turn + intent routing, brain model for planning/tool-heavy work, a vision-capable model for screen grounding. Treat vision support of every gateway model as unknown until tested. | MEDIUM |
| pydantic / pydantic-settings | 2.14.1 / 2.15.0 (reg) | Typed config, tool schemas, event contracts | Single source of truth for tool JSON-schemas and HUD event types. | HIGH |
| mcp (official Python SDK) | 2.3.0 (reg) | MCP client (tools) and Snow's own MCP server | v2 is stable and is what Pipecat's `mcp` extra pins (`>=2.1.1,<3`). Breaking v1->v2 changes: `FastMCP` renamed `MCPServer`, `McpError`->`MCPError`, `streamablehttp_client`->`streamable_http_client`, snake_case fields. Targets the 2026-07-28 stateless spec revision and still serves older clients. | HIGH |
| fastmcp | 4.1.0 (reg) | Ergonomic way to write Snow's own MCP tool servers | Built on SDK v2. Optional; use only if writing several custom servers. | MEDIUM |

### Driving Coding Agents (the adapter layer)

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| agent-client-protocol (Python) | 0.12.1 (reg) | ACP client: spawn agent over stdio, `session/new`, `session/prompt`, stream `session/update`, answer `session/request_permission` | One protocol for all agents. Permission prompts arrive as a typed request with options; Snow speaks the summary, takes the spoken answer, returns the selected option. TS SDK `@agentclientprotocol/sdk` 1.8.0 exists if an adapter ever moves to Node. | MEDIUM-HIGH |
| claude-agent-sdk (Python) | 0.2.165 (reg) | Claude Code, full-fidelity path | `can_use_tool` callback fires for tool approvals AND `AskUserQuestion` (questions array with 2-4 options; answer by returning `updated_input` with `answers`); callback may stay pending indefinitely; for long waits (user walked away) use a `PreToolUse` hook returning `defer` so the process can exit and resume from the persisted session. Python requires streaming-input prompts (async generator) for `can_use_tool`; docs show a dummy `PreToolUse` hook workaround to keep the stream open: re-check against 0.2.165 changelog. Allow-responses can carry `updated_permissions` ("always allow") from SDK suggestions. | HIGH |
| `claude` CLI (Claude Code) | 2.1.296 (reg `@anthropic-ai/claude-code`) | The binary the SDK drives | The SDK runs the Claude Code binary. CLI fallback: `claude -p --output-format stream-json --input-format stream-json --include-partial-messages --verbose`; approvals in CLI mode require `--permission-prompt-tool <mcp tool>`; use `--permission-prompts none` for unattended runs. `--bare` skips OAuth/keychain (API-key only), so it is NOT usable with a subscription login. | HIGH |
| `@agentclientprotocol/claude-agent-acp` | 0.89.1 (reg) | ACP adapter for Claude (alternative to direct SDK) | Same ACP surface as other agents; use if you want zero Claude-specific code. Prefer direct SDK when `AskUserQuestion`, hooks `defer`, or cost data are needed. Older names `@zed-industries/claude-code-acp` are superseded. | MEDIUM |
| OpenCode | `opencode-ai` / `@opencode-ai/sdk` 1.19.0 (reg); repo now `anomalyco/opencode` | OSS-model coding agent | Use `opencode acp` (native ACP over stdio JSON) as the contract. The HTTP server (`opencode serve`, basic auth via `OPENCODE_SERVER_PASSWORD`, OpenAPI at `/doc`, SSE at `/event`, permission reply at `POST /session/:id/permissions/:permissionID`) is documented but the repo shows a parallel `/api/session/:id/permission/...` v2 surface in development: the REST shape is moving. Pin the version and prefer ACP; if REST is needed, generate the client from `/doc`, never hand-write paths. `opencode run --format json` gives raw JSON events for one-shot jobs; `--auto` auto-approves non-denied permissions. | MEDIUM |
| Antigravity CLI (`agy`) | docs show 1.1.x-1.3.x; `antigravity-acp` 1.3.0 reported 2026-10-05 | Google's agent CLI (Gemini successor) | Two modes. (1) Headless `agy -p` with `--output-format stream-json` and `--input-format stream-json` for multi-turn: but it has NO interactive permission prompt: tools needing approval are soft-denied (exit 0) unless pre-allowed via `permissions.allow` rules in `~/.gemini/antigravity-cli/settings.json` or `--dangerously-skip-permissions`; also a reported hang on non-TTY in 1.0.6. (2) The ACP server (`agy_acp_server`, registry id `antigravity-acp`, reported working on Windows): requires calling ACP `authenticate`; the sandbox only allows paths under the `cwd` passed at `session/new`. Use ACP for anything interactive. Reported community concern that Antigravity's FAQ discourages third-party access: user's call. | MEDIUM-LOW |
| Gemini CLI | `@google/gemini-cli` 0.63.0 (reg) | Spare agent | `gemini --acp` native. Same adapter, zero extra code. | MEDIUM |

### Windows Automation and Computer Use

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| Windows UI Automation via `uiautomation` | 2.0.29 (reg) | Read UI tree, find/click/type in native, WPF, WinUI, many Electron apps | Lighter and faster tree walking than pywinauto; good for building a compact numbered "snapshot" of interactive elements for the LLM (avoid dumping the full tree: tokens). Declare per-monitor DPI awareness before any UI call. | MEDIUM-HIGH |
| pywinauto | 0.6.9 (reg, 2025-01; repo active 2026-10) with comtypes 1.4.17 | Higher-level actions, window/app launch and wait helpers | Use selectively (backend `"uia"`), not as the primary tree walker. | MEDIUM |
| Windows-MCP (CursorTouch) | pinned release; `uvx windows-mcp serve`; MIT; needs Python 3.13+ (own isolated env) | Ready-made UIA snapshot + click/type/shortcut/scroll/app/clipboard MCP server | Fastest path to "any app" control in v1: UIA-first (no vision model needed), optional `use_vision=True` screenshot. Run it as an MCP subprocess behind Snow's policy gate; set `ANONYMIZED_TELEMETRY=false`; exclude `PowerShell` and `Registry` tools (Snow provides its own audited shell tool). Its own docs say it has full system access and takeover is "best-effort, not a security boundary". Limits: custom-drawn UIs/games show as opaque regions; English UI recommended. | MEDIUM |
| pywin32 | 312 (reg) | Window management, DPAPI (`win32crypt`), shell integration, Task Scheduler COM | The standard Win32 binding. | HIGH |
| pycaw | 20260927 (reg) | Master/per-app volume | Core Audio wrapper. | MEDIUM-HIGH |
| screen-brightness-control | 0.27.2 (reg) | Brightness (laptop panel via WMI, external via DDC/CI) | Standard; works for laptop panel. | MEDIUM |
| winrt-* (e.g. `winrt-Windows.Media.Control`) | 3.2.x (reg `winrt-runtime` 3.2.1) | Media transport (play/pause/next) via System Media Transport Controls | Correct way to control "whatever is playing" without keystroke hacks. | MEDIUM |
| dxcam / mss | 0.3.0 / 10.2.0 (reg) | Screenshots for vision grounding | `mss` is simple and reliable (default); `dxcam` (DXGI) for fast repeated capture. | MEDIUM-HIGH |
| Vision grounding for apps without UIA | remote vision LLM via gateway first; OmniParser-class local detector optional later | Click targets on canvas/custom UIs | 6 GB VRAM is already taken by STT; 7B-class local GUI-grounding models (UI-Venus, UI-TARS, etc.) do not fit alongside it. Use UIA snapshot first, then screenshot + remote vision model, using Set-of-Marks overlays (numbered boxes from UIA bounds). No leaderboard-grade evidence gathered: LOW on specific model choice. | LOW |

### Browser Automation with Logged-in Sessions

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| Playwright MCP (`@playwright/mcp`) | 0.0.83 (reg) | LLM-friendly accessibility-snapshot browser control as an MCP tool | Standard pattern; reuse via the MCP client; pre-1.0, pin exactly. | MEDIUM |
| Playwright (Python) | 1.63.0 (reg; npm is 1.64.0) | In-process scripted flows (login keep-alive, form macros) | `launch_persistent_context(user_data_dir=<Snow profile>, channel="chrome", headless=False)`. | HIGH |
| Dedicated "Snow" Chrome profile | Chrome stable | Persistent logged-in sessions | **Chrome 136+ ignores `--remote-debugging-port`/`--remote-debugging-pipe` on the default user-data-dir** (official Chrome blog), so you cannot CDP-attach to the everyday profile. Use a separate `--user-data-dir`; user logs in once manually (Google may block "automated" first logins: sign in by hand in that window), sessions persist after. | HIGH |
| `chrome-devtools-mcp --autoConnect` | `chrome-devtools-mcp@latest` (pin) | Attach to the user's live, already-logged-in Chrome | Chrome 144+: enable at `chrome://inspect/#remote-debugging`; Chrome shows a per-session Allow dialog and an automation banner. Gives access to everything in the profile (cookies, tabs): treat as a Tier-2 approval feature, never default. Version requirements reported inconsistently (144/145/146+): verify at build time. | MEDIUM |

### Desktop HUD Shell and Rendering

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| Tauri | core 2.x; `@tauri-apps/cli` 2.12.2, `@tauri-apps/api` 2.12.3 (reg) | Windowed/overlay/tray shell, installer, signed updater | Uses the preinstalled WebView2 (Chromium engine, same WebGL as Electron), small installers, mandatory signed updates via GitHub Releases `latest.json`, NSIS/MSI bundlers, built-in sidecar support. Rust code stays at "tray + window + commands" level. **Gate in Phase 1 with a spike**: transparent always-on-top click-through window running the ASCII scene at 60 fps while faster-whisper uses the GPU. Known: transparent borderless windows on Windows can show residual border/shadow. If the spike fails, use Electron (below): the HUD code is identical because it talks to the core over WebSocket, not Tauri IPC. | MEDIUM |
| Tauri plugins | updater 2.13.3, autostart 2.7.0, shell 2.5.0, global-shortcut 2.4.1, notification 2.6.0 (reg); single-instance (Rust crate) | Updates, start-with-Windows, spawn core, push-to-talk hotkey, toasts | Updater: signing key is mandatory and cannot be lost; Windows installs in `passive` mode by default and the app exits during install; needs Rust >=1.90. | HIGH |
| React | 19.3.0 (reg) | HUD UI | Required by R3F 9. | HIGH |
| three | 0.186.1 (reg) | 3D engine | WebGL2 renderer. Stay on WebGL, not WebGPURenderer/TSL, for v1 (stability under WebView2 + GPU sharing). | HIGH |
| @react-three/fiber | 9.8.1 (reg; peer react >=19 <19.4) | React renderer for three | Declarative scene, state-driven animation (idle/listening/thinking/acting/speaking/alert). | HIGH |
| @react-three/drei | 10.7.9 (reg) | Helpers (Text/Instances/etc.) | Use sparingly; keep bundle lean. | HIGH |
| postprocessing + @react-three/postprocessing | 6.39.5 + 3.2.0 (reg) | Post-process pipeline incl. `ASCIIEffect` | `ASCIIEffect` exists in the library (character lookup texture, `cellSize`, optional fixed `color`, `inverted`; cannot merge with convolution effects). It maps scene to glyphs. Snow's look (color kept per glyph, glow, letters revealed on zoom, glyph atlas built from the user's code) needs a **custom `Effect` subclass** with a custom glyph atlas, bloom pass after the ASCII pass, and a LOD rule that swaps cell size on zoom. Treat as a dedicated HUD-render research phase. | MEDIUM |
| Vite | 8.3.4 (reg) | Build/dev server | Tauri-supported. | HIGH |
| TypeScript | 7.0.2 (reg; native-compiler line) | Types | New major: verify your lint/test toolchain supports it; fall back to latest 6.x if a tool blocks. | MEDIUM |
| zustand | 5.0.15 (reg) | HUD state store | Tiny, works outside React for the WebSocket event reducer. Keep the 3D render loop reading refs, not React state, to protect the 100 ms budget. | HIGH |
| motion | 14.1.0 (reg) | UI motion for 2D panels | Design-system motion tokens. | MEDIUM |
| Tailwind CSS | 4.3.3 (reg) | HUD design system tokens | One design system requirement; pair with CSS variables for theme. | MEDIUM-HIGH |
| Electron (fallback only) | 44.7.0 (reg) + electron-builder 26.15.3 | Alternative shell | Choose only if the Tauri spike fails or Rust onboarding blocks. Cost: ~150-300 MB idle RAM and a bundled Chromium; benefit: no Rust, consistent Chromium flags, one language. | MEDIUM |

### Local Server, Protocol, Persistence, Secrets

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| FastAPI + uvicorn + websockets | 0.143.0 / 0.54.0 / 17.2 (reg) | Local WS/HTTP API for HUD and phone | Bind `127.0.0.1` only; per-launch random bearer token handed to the HUD by the shell; phone access only through `tailscale serve` which proxies to localhost and adds identity headers. Contract = Pydantic models exported to JSON Schema, generated TS types, contract tests on both sides. | HIGH |
| SQLite (WAL, FTS5) via stdlib `sqlite3` + aiosqlite | aiosqlite 0.22.1 (reg) | Tasks, activity log, conversation memory, approvals audit | Zero-ops, single file, ideal for single-user. Add Alembic 1.20.0 (reg) only if schema migrations get non-trivial; start with a tiny numbered-SQL migrator. | HIGH |
| sqlite-vec | 0.1.9 (reg, pre-1.0) | Vector search over memory | Keeps vectors in the same SQLite file. Pre-1.0: wrap behind a `MemoryIndex` interface. Start with FTS5 only; add vectors when recall quality demands. | MEDIUM |
| fastembed | 0.9.0 (reg) | Local ONNX text embeddings (CPU) | Avoids torch and GPU contention. | MEDIUM |
| keyring | 25.7.0 (reg) | Windows Credential Manager access | Gateway keys, Cartesia key, Telegram token, ntfy token, agent API keys. Credential blob limit is ~2.5 KB: store only secrets, not data. For larger blobs use `win32crypt.CryptProtectData` (DPAPI, per-user) via pywin32. Rules: never write secrets to logs/env files; inject into agent subprocesses via minimal, scrubbed environments; add secret scanning in CI. | HIGH |
| structlog | 26.1.0 (reg) | Structured JSON logs | Include a redaction processor for keys/tokens and transcript-content policy ("privacy by default"). | HIGH |
| sentry-sdk (optional, off by default) | 2.72.0 (reg) | Crash reporting | Only if the user opts in; self-hosted or scrubbed. Local crash dumps + health endpoint are the default. | MEDIUM |

### Phone Hand-off and Remote Link

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| Telegram Bot API via python-telegram-bot | 22.8 (reg); Bot API 10.3 (2026-08-24) | v1 phone channel: notify, inline-keyboard approve/deny, free-text and voice-note replies | Two-way with no inbound port (long polling is outbound), FCM-grade delivery handled by Telegram, free, works on any Android. Fits "Snow's own channel, no dependency on Claude app": create a private bot, lock to the user's numeric chat ID. Content is not end-to-end encrypted: send minimal text; put detail in the HUD. `aiogram` 3.31.0 is a fine async alternative. | HIGH (capability), MEDIUM (privacy fit) |
| ntfy | server/app current; no pip dep (plain HTTPS publish via `httpx`) | Secondary one-way push channel behind the same `NotificationChannel` interface | Self-hosted ntfy delivers instantly via a foreground service without Firebase; `ntfy.sh` public uses FCM. Access tokens (`tk_...`) currently grant full account access. Action buttons that call back to the PC need the phone to reach the PC (Tailscale). Use as fallback, not primary. | MEDIUM |
| Tailscale (Serve, not Funnel) | current client | Authenticated private link phone<->PC | `tailscale serve` provides HTTPS with tailnet certs and injects `Tailscale-User-Login` headers (stripped from client input). Core verifies the header AND a token; ACL-restrict to the user's phone. Never use Funnel (public). Needed from the phone-HUD phase onward, not for Telegram. | HIGH |
| Web Push (PWA) via pywebpush | 2.5.0 (reg) | Later: installable phone HUD with push, no native app | Optional phase after Telegram: PWA served over Tailscale Serve, VAPID push. Do not start here: more moving parts. | LOW-MEDIUM |
| Firebase Cloud Messaging | n/a | Push to a native app | Requires own Android app and Firebase project. Defer with the native app (explicit out-of-scope). | HIGH |

### Packaging, Updates, CI

| Technology | Version | Purpose | Why Recommended | Confidence |
|------------|---------|---------|-----------------|------------|
| Tauri bundler (NSIS) + `tauri-action` | with Tauri 2.x | Installer + GitHub Releases + `latest.json` for updater | NSIS avoids the VBSCRIPT dependency that MSI needs. | HIGH |
| "Bootstrap" core distribution | uv-managed venv under `%LOCALAPPDATA%\Snow` | Ship Python core without freezing it | Installer ships the HUD + `snow-core` wheel + `uv.exe`; first run does `uv sync --frozen` from a bundled lock (downloads CUDA wheels ~1-2 GB). PyInstaller 6.22.3 / Nuitka 4.3 can freeze Python, but ctranslate2/onnxruntime/CUDA DLL bundling is fragile and huge. Decide in the packaging phase; treat as MEDIUM-LOW until prototyped. | MEDIUM-LOW |
| GitHub Actions `windows-latest` | n/a | CI | No GPU and no audio device on hosted runners: CI tests use recorded WAV fixtures and fake transports; GPU/mic tests are a local "hardware suite" run before release. | HIGH |
| Code signing | Azure Trusted Signing or SignPath (OSS) | Avoid SmartScreen warnings | Unsigned is acceptable for single-user v1; required before any public distribution. Updater signature (Tauri key) is separate and mandatory. | MEDIUM |

### Development and Quality Tools

| Tool | Version | Purpose | Notes |
|------|---------|---------|-------|
| ruff | 0.17.0 (reg) | Python lint + format | One tool for lint+format; enable `ASYNC`, `S` (bandit rules), `UP`. |
| pyright | 1.1.414 (reg) | Python type check (strict on `snow_core`) | Chosen over mypy 2.4.0 for speed and Pydantic ergonomics. `ty` 0.0.86 is still pre-beta: do not adopt. |
| pytest + pytest-asyncio | 9.1.1 / 1.4.0 (reg) | Python tests | Use recorded-audio golden tests for wake/VAD/STT/speaker thresholds; fake LLM server for tool-loop tests; fake ACP agent for adapter tests. |
| Vitest | 5.0.4 (reg) | HUD unit tests | Test reducers/state machine; snapshot the event contract. |
| Playwright Test | 1.64.0 (reg) | HUD e2e + visual regression | Drive the HUD in Chromium against a mock core; screenshot-diff the ASCII scene with a fixed seed. |
| Biome | 2.5.15 (reg) | TS lint + format | One config, avoids ESLint 10 plugin churn with TS 7. |
| clippy + rustfmt | with toolchain | Rust shell | Rust surface is tiny; enforce in CI anyway. |
| pip-audit / osv-scanner, gitleaks | current | Supply-chain and secret scanning in CI | Direct response to the 2026 LiteLLM incident. |
| `uv lock` with hashes, `uv sync --frozen`, `exclude-newer` | uv 0.13 | Reproducible, delayed-adoption dependency policy | Only upgrade deps deliberately; new releases wait N days. |

## Installation

# --- Python core (Python 3.12 via uv) ---

# NOTE: Pipecat pins onnxruntime~=1.24.3 (CPU). Do NOT add onnxruntime-gpu to this env.

# If a GPU-ONNX model (e.g. Parakeet via onnx-asr) is evaluated, run it in a separate process/venv.

# --- Agent binaries (user-level, not Snow dependencies) ---

# Antigravity: install per Google's installer; ACP server ships as agy_acp_server

# Optional ACP adapters (run via npx at spawn time, pin versions):

#   @agentclientprotocol/claude-agent-acp@0.89.1   @zed-industries/codex-acp@0.16.0

# --- HUD (TypeScript) ---

# --- Tauri shell (needs rustup + MSVC Build Tools first) ---

# Visual Studio Build Tools -> "Desktop development with C++"

# Rust side: tauri, tauri-plugin-updater, tauri-plugin-autostart, tauri-plugin-single-instance

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| Pipecat 1.12 | Custom asyncio pipeline | If Pipecat's frame model fights the HUD/policy needs after the Phase-1 spike. Keep every Snow component (wake gate, verifier, policy) as plain classes with a thin Pipecat wrapper so the framework is removable. |
| Pipecat 1.12 | LiveKit Agents 1.8.6 | If voice must later run over a network room (phone as a live voice client). Not for a local mic. |
| faster-whisper `turbo` int8_float16 | Parakeet TDT 0.6B v3 via `onnx-asr` 0.12.0 / sherpa-onnx | If you only speak English/European languages and Whisper latency is too high: Parakeet is far faster (leaderboard ~3,300x RTFx vs ~145x for Whisper large-v3, vendor-blog figure) but v3 covers 25 European languages and NOT Hindi. Needs `onnxruntime-gpu`, which conflicts with Pipecat's pin: run it as a separate STT process. |
| faster-whisper | Moonshine v2 streaming (`moonshine-voice` 0.1.5, MIT, CPU, Windows listed) | Genuinely incremental English streaming on CPU, leaving the GPU free; accuracy depends on size (medium ~10.7% avg WER). Evaluate in the STT spike as the "partials" engine. |
| faster-whisper | Nemotron streaming 0.6B / Voxtral Realtime 4B | Not on this hardware/OS: Nemotron wants the NVIDIA NeMo stack; Voxtral needs ~16 GB VRAM. |
| faster-whisper | whisper.cpp (repo very active) | If CUDA/cuDNN DLL management becomes a recurring Windows pain: whisper.cpp ships Windows builds (CUDA/Vulkan) with no cuDNN. Loses Pipecat's ready service. |
| openWakeWord | sherpa-onnx keyword spotting (open-vocabulary, no training) | If custom training stays brittle; expect lower precision/recall than a trained model. Good as a spike comparator. |
| openWakeWord | Porcupine | Free tier ended 2026-06-30; only if you pay Picovoice enterprise pricing. |
| Cartesia sonic-3.6 | Cartesia `sonic-3` / `sonic-turbo` (older models page) | If a snapshot's expressiveness regresses or latency matters more than quality. |
| kokoro-onnx fallback | Piper (`piper-tts` 1.8.0) | Lowest CPU cost, huge voice catalogue; GPL licence and lower quality. |
| Claude Agent SDK direct + ACP | ACP only | Simplest code; lose `AskUserQuestion` fidelity, `defer` hooks and cost telemetry. |
| Telegram | ntfy self-hosted | If you refuse any third-party cloud in the message path; one-way unless Tailscale-reachable. |
| Tauri 2 | Electron 44.7 | Spike failure (transparency, GPU contention) or Rust toolchain refusal. |
| `openai` SDK + config | `litellm` | Only run LiteLLM as an isolated, pinned proxy process (not imported into core) if you later need 100+ providers and non-OpenAI wire formats. The gateway is already OpenAI-compatible. |
| `openai` SDK + own loop | OpenAI Agents SDK 0.23.1, LangGraph 1.2.14 | Only for sub-workflows that truly need graph orchestration. The voice loop plus agent adapters do not. |
| Own thin UIA tools + Windows-MCP | Anthropic computer-use tool | Claude-only; violates provider independence. |
| uiautomation | pywinauto alone | If you need pywinauto's higher-level wait/launch ergonomics more than fast tree dumps. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Windows Service (NSSM/WinSW/pywin32 service) for the voice core | Session 0 isolation: no interactive desktop, unreliable user audio endpoints, no UI Automation/screenshots of the user's session | Per-user Task Scheduler "At log on" job + watchdog (and Tauri autostart for the HUD) |
| `litellm` imported in `snow-core` | Malicious versions 1.82.7 and 1.82.8 were published to PyPI on 2026-03-24 (credential stealer; 1.82.8 used a `.pth` that ran at interpreter start). Largest blast radius is a process holding every key | `openai` SDK + `base_url` config; hash-locked deps |
| Porcupine | Free tier keys stopped working after 2026-06-30 (secondary source) | openWakeWord |
| Attaching CDP to the default Chrome profile | Chrome 136+ ignores the debugging flags for the default user-data-dir | Dedicated Snow profile, or `chrome-devtools-mcp --autoConnect` with per-session consent |
| Running Chatterbox/XTTS-class GPU TTS locally | ~6 GB VRAM: starves STT and the HUD | kokoro-onnx on CPU |
| `onnxruntime-gpu` in the Pipecat env | Pipecat pins `onnxruntime~=1.24.3`; a GPU 1.31 install conflicts | CPU onnxruntime in core; separate process for any GPU-ONNX model |
| `--bare` with Claude subscription login | Bare mode never reads OAuth/keychain credentials (API key only) | Normal mode, with the user's own logged-in `claude` binary |
| Reading or storing Claude OAuth tokens in Snow | Anthropic: third parties may not offer claude.ai login or its rate limits through Agent-SDK products "unless previously approved". Snow must only spawn the user's own `claude`, which manages its own auth | Let the `claude` binary hold auth; keep Snow provider-neutral so Claude is optional |
| Hand-rolled OpenCode REST paths | API is mid-migration (`/session/...` documented vs `/api/session/...` in repo) | `opencode acp`, or a client generated from `/doc` for a pinned version |
| `agy -p` for interactive tasks | Soft-denies anything needing approval, no way to relay a question | Antigravity ACP server, or pre-scoped `permissions.allow` rules for unattended runs |
| Funnel / port-forwarding for phone access | Public exposure of a machine with shell and UI control | Tailscale Serve + ACLs |
| `pyautogui` (0.9.54, last release 2023) as the control layer | Coordinate-blind clicking, no DPI/UIA awareness | UIA-first via `uiautomation`/Windows-MCP, screenshots for fallback |
| Browser-side three-stdlib `AsciiEffect` (CPU canvas ASCII) | CPU readback per frame; cannot hit 60 fps at HUD resolution | GPU `ASCIIEffect`/custom `Effect` in `postprocessing` |
| Hard-coded spoken phrases (confirmations, errors) | Violates the "no scripts" requirement | LLM generates wording and emotion from persona + situation + memory; keep only a tiny non-speech earcon set for the LLM-unreachable case |
| `ty` type checker, `sqlite-vec` as an un-abstracted dependency, `@playwright/mcp` unpinned | Pre-1.0 / moving fast | Pin exact versions, wrap behind interfaces |

## Stack Patterns by Variant

- Swap the shell for Electron 44.7; keep HUD and core unchanged (WebSocket only).
- Because the HUD must not depend on Tauri IPC for anything except window chrome.
- Core router: Cartesia for short, high-value utterances (greetings, results, emotional lines), kokoro-onnx for long or routine ones, with a per-day budget and a visible "voice quota" meter in the HUD.
- Still generated by the LLM; only the synthesizer changes. Consider Cartesia Pro ($5/mo, 100K credits, includes commercial license) when the user decides to pay.
- Enable AEC (livekit APM) with playback reference and require speaker verification for any barge-in during TTS. The verifier doubles as an echo filter because Snow's own voice will not match the enrolled user. Recommend headphones/earbuds for the first release.
- Keep Whisper (multilingual) as primary STT; set Cartesia `language`/`locale` accordingly (Sonic 3.6 improved Hinglish); emotion tags are English-only. Confirm with the user; assumed English-primary here.
- Use SDK/ACP sessions with scoped allow rules, route ask-events to the Telegram channel, persist session IDs in SQLite, and use Claude SDK `PreToolUse` `defer` so the process can exit while waiting.
- STT ~1.5-2.5 GB, HUD WebGL ~0.3-1 GB, Windows compositor overhead; leave headroom. Never co-locate a local LLM or GPU TTS. Throttle HUD to ~15-30 fps when idle or hidden.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| pipecat-ai 1.12.0 | Python >=3.11; `onnxruntime~=1.24.3`; `mcp>=2.1.1,<3`; `faster-whisper~=1.2.1`; `kokoro-onnx>=0.5.0,<1` | Verified in Pipecat `pyproject.toml` (main). Do not install onnxruntime-gpu 1.31 in the same env. |
| ctranslate2 4.8.2 | CUDA 12 + cuDNN 9 | Older CUDA 12/cuDNN 8 needs ctranslate2 4.4.0; CUDA 11 needs 3.24.0. |
| kokoro-onnx 0.6.1 | Python <3.14 | Another reason for 3.12. |
| livekit-agents 1.8.6 (not used) | Python <3.15 | Noted for the LiveKit alternative only. |
| @react-three/fiber 9.8.1 | react >=19 <19.4, react-dom same | React 19.3.0 is inside range; do not move to 19.4 until R3F widens it. |
| @react-three/postprocessing 3.2.0 | react ^19, three >=0.156, postprocessing ^6.36, @react-three/fiber >=9.7 | OK with listed versions. |
| @tauri-apps/plugin-updater 2.13.3 | Rust >=1.90, Tauri 2.x | Signing key required; keep the private key backed up. |
| claude-agent-sdk (py) 0.2.165 vs @anthropic-ai/claude-agent-sdk (ts) 0.3.296 | Different numbering schemes per language | Features such as `suppressAlwaysAllowRule` are TS-only (>=0.3.268); Python `updated_permissions` needs >=0.1.80. |
| mcp 2.x | MCP spec 2026-07-28 (stateless), older clients still served | A project importing `mcp.server.fastmcp` breaks on 2.x (renamed `MCPServer`). |
| Windows-MCP | Python >=3.13 | Run in its own `uvx` env, not in the 3.12 core env. |

## Roadmap-Relevant Research Flags (for SUMMARY.md consumers)

| Topic | Why deeper phase research / a spike is needed | Confidence today |
|-------|-----------------------------------------------|------------------|
| STT latency and VRAM on RTX 4050 (turbo int8_float16 vs Moonshine v2 vs Parakeet) | No measured numbers; CUDA/cuDNN DLL handling on Windows; driver 551/552 hang report | MEDIUM |
| Wake word "Hey Snow" training pipeline | Upstream training notebook brittle; need a reproducible, pinned recipe; plus false-accept rate target with TV audio | MEDIUM |
| AEC and barge-in with laptop speakers | AEC3 fails silently with large/variable delay; Windows device latency; decide headphones-only v1 vs AEC | MEDIUM-LOW |
| Speaker verification thresholds | Short-utterance unreliability; needs enrollment UX and calibration on real mic + TV negatives | MEDIUM |
| Tauri transparent overlay + WebGL under GPU contention | No benchmark found; known border/shadow quirks on Windows | MEDIUM |
| ASCII-shader HUD (custom Effect, glyph atlas from code, glow, LOD) | Library effect is generic; target look is bespoke | MEDIUM |
| ACP coverage of `AskUserQuestion`, resume, cost data for Claude; Antigravity ACP stability and auth | Young protocol surfaces, auth quirks, ToS discouragement noted by users | MEDIUM-LOW |
| OpenCode API stability | Two API generations visible | MEDIUM |
| Vision grounding provider | Gateway models' vision support unknown; local grounding models do not fit | LOW |
| Packaging the Python core with CUDA wheels | Installer size, first-run download, PyInstaller fragility | MEDIUM-LOW |
| Gateway capabilities | Streaming tool calls, vision, rate limits unconfirmed (PROJECT.md says "still to confirm") | LOW |

## Sources

- PyPI JSON API and npm registry (`npm view`) for every version marked (reg): HIGH
- https://code.claude.com/docs/en/agent-sdk/user-input: `canUseTool`/`can_use_tool`, AskUserQuestion, `defer`: HIGH
- https://code.claude.com/docs/en/agent-sdk/overview: auth/third-party login policy, SDK runs the Claude Code binary: HIGH
- https://code.claude.com/docs/en/headless: `-p`, `stream-json`, `--bare`, `--permission-prompts`, SIGTERM behaviour: HIGH
- https://antigravity.google/docs/cli/headless: `agy -p`, output/input formats, soft-deny permissions: HIGH
- https://github.com/google-antigravity/antigravity-cli/issues/31: ACP server status and caveats (user reports): MEDIUM-LOW
- https://agentrq.com/blog/which-coding-agents-support-acp-agent-client-protocol: ACP support matrix: MEDIUM
- https://opencode.ai/docs/server/, /docs/cli/, /docs/sdk/ and the `anomalyco/opencode` repo tree (`packages/protocol/src/groups/permission.ts`): HIGH/MEDIUM
- https://docs.cartesia.ai/build-with-cartesia/tts-models/latest (sonic-3.6), /capability-guides/volume-speed-emotion.md, /use-the-api/compare-tts-endpoints.md, /use-the-api/tts-websocket/contexts.md, https://cartesia.ai/pricing: HIGH
- https://github.com/pipecat-ai/pipecat (`pyproject.toml`, `src/pipecat/...` tree), https://docs.pipecat.ai/pipecat/learn/speech-input.md: HIGH/MEDIUM
- https://github.com/dscripka/openWakeWord README; secondary reports on training brittleness: MEDIUM/LOW
- https://community.home-assistant.io/t/fyi-picovoice-confirmed-free-tier-accesskeys-will-stop-working-after-june-30-2026/1012744: LOW (forum quoting vendor)
- https://github.com/SYSTRAN/faster-whisper README; faster-whisper GitHub issues on Windows CUDA/cuDNN: MEDIUM
- https://github.com/moonshine-ai/moonshine, https://github.com/istupakov/onnx-asr, openwhispr/other blogs for Parakeet figures: MEDIUM/LOW
- https://arxiv.org/abs/2303.00332 (CAM++), https://arxiv.org/pdf/2005.07143 (ECAPA-TDNN): HIGH for the numbers as authors' claims
- https://docs.litellm.ai/blog/security-update-march-2026 and BleepingComputer/HelpNetSecurity coverage: HIGH/MEDIUM
- https://py.sdk.modelcontextprotocol.io/migration/ and FastMCP 4 release notes: MEDIUM
- https://developer.chrome.com/blog/remote-debugging-port, https://developer.chrome.com/docs/devtools/agents/use-cases/auto-connect: HIGH
- https://github.com/CursorTouch/Windows-MCP: MEDIUM
- https://v2.tauri.app/start/prerequisites/, /develop/sidecar/, /plugin/updater/: HIGH
- https://github.com/pmndrs/postprocessing (`src/effects/ASCIIEffect.js`): HIGH
- https://tailscale.com/kb/1312/serve; https://docs.ntfy.sh/config/; https://core.telegram.org/bots/api-changelog (Bot API 10.3): HIGH
- https://docs.livekit.io/reference/python/livekit/rtc/apm.html and LiveKit community thread on AEC3 delay limits: MEDIUM/LOW
- Windows Session 0 / audio / UIA behaviours, keyring blob limit, and Task Scheduler restart semantics are from general platform knowledge, not re-verified this session: MEDIUM

<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-fast` for a trivial task inline, with no subagents and no PLAN.md
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
