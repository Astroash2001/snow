# API Coverage — Phase 1 external services

> Full coverage by default. Opt-outs are explicit, reasoned decisions.
> Services: OpenAI-compatible chat APIs of the five LLM providers (Experiential Labs, Groq, Google AI Studio, NVIDIA NIM, OpenRouter), Groq speech-to-text, Cartesia text-to-speech. Each provider in the chain starts from the same full-coverage baseline (no first-class/fallback asymmetry): every capability decision below applies to all five LLM providers alike.

| capability | decision | reason |
|---|---|---|
| llm.chat-completions-streaming | INTEGRATE | |
| llm.models-list | INTEGRATE | |
| llm.rate-limit-headers-and-error-codes | INTEGRATE | |
| llm.usage-reporting (stream_options include_usage) | INTEGRATE | |
| llm.reasoning-effort-param | INTEGRATE | |
| llm.tool-calling | OPT-OUT | not needed yet: Phase 1 executes no actions; support is only probed and recorded (plan 01-17), used from Phase 2 |
| llm.image-input (vision role) | OPT-OUT | not needed yet: vision role is configured and probed now, used in Phase 5 |
| llm.structured-outputs / response_format | OPT-OUT | not needed: replies are free speech with a validated emotion header |
| llm.embeddings | OPT-OUT | explicitly out of scope: memory and retrieval are not in Phase 1 |
| llm.non-streaming-completions | OPT-OUT | not needed: every call streams for latency |
| llm.provider-specific-extras (assistants, batches, files, fine-tuning) | OPT-OUT | explicitly out of scope: plain chat only, provider independence |
| groq.audio-transcriptions | INTEGRATE | |
| groq.audio-translations | OPT-OUT | not needed: English only in v1 |
| groq.text-to-speech | OPT-OUT | not needed: voice router decided in D-33 (Pocket TTS, Cartesia, Chatterbox, Kokoro) |
| cartesia.tts-websocket-contexts | INTEGRATE | |
| cartesia.generation-config-emotion | INTEGRATE | |
| cartesia.voices-list | INTEGRATE | |
| cartesia.usage-credits | INTEGRATE | |
| cartesia.word-timestamps | OPT-OUT | not needed yet: barge-in records spoken text at sentence granularity |
| cartesia.tts-bytes-and-sse-endpoints | OPT-OUT | not needed: the WebSocket endpoint covers streaming |
| cartesia.voice-cloning | OPT-OUT | not available on the Free plan (D-05) |
| cartesia.speech-to-text | OPT-OUT | not needed: STT is Groq plus local Moonshine (D-37, D-38) |
| cartesia.voice-changer-and-infill | OPT-OUT | not needed |
