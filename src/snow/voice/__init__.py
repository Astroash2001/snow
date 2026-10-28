"""The voice worker: microphone, local wake gate, turns, cloud final transcript."""

# Three onnxruntime.dll builds can share one process (Moonshine 1.23, onnxruntime 1.24,
# sherpa-onnx 1.28) and Windows reuses the first one loaded by name. sherpa needs ORT
# API 28, which only its own DLL has; the others accept it. Loading it here, before any
# voice module, covers the worker, enroll-voice and the tests alike, or the process dies
# with an access violation when the speaker model loads (2026-10-27/28).
import sherpa_onnx  # noqa: F401  # pyright: ignore[reportMissingTypeStubs, reportUnusedImport]
