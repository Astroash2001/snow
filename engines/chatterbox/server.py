"""Isolated Chatterbox synthesis server (plan 01-33, D-33, D-39).

Runs in its own environment (engines/chatterbox/.venv): chatterbox-tts pins numpy 1 and
torch 2.6, which cannot share the core environment. Talks to snow-core over pipes only.

stdin  - one JSON object per line:
    {"op":"load","device":"cuda","reference":"C:/x.wav"|null}
    {"op":"speak","id":..,"text":..,"exaggeration":0.5,"cfg_weight":0.5}
    {"op":"vram"}
    {"op":"quit"}
stdout - binary frames, nothing else (stray prints are sent to stderr):
    audio:   uint32 LE byte count N (N > 0, bit 31 clear), then N bytes of float32 LE PCM
    end:     uint32 0, closing one `speak` reply
    control: uint32 LE (0x80000000 | N), then N bytes of JSON; the answer to `load`/`vram`,
             or {"error": ".."} inside a `speak` reply (an end frame still follows)
stderr - diagnostics only. Audio is never written to disk; this process gets no keys.
"""

import json
import os
import struct
import sys
import time
from typing import Any

# Keep stdout clean: libraries that print (or C code that writes to fd 1) go to stderr.
_out = os.fdopen(os.dup(1), "wb")
os.dup2(2, 1)
sys.stdout = sys.stderr

_CONTROL = 0x80000000
_FRAME_SAMPLES = 2400  # 100 ms at 24 kHz

model: Any = None


def _control(payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode()
    _out.write(struct.pack("<I", _CONTROL | len(body)) + body)
    _out.flush()


def _load(device: str, reference: str | None) -> dict[str, Any]:
    global model  # noqa: PLW0603
    import torch  # noqa: PLC0415 - slow import, only on load
    from chatterbox.tts import ChatterboxTTS  # noqa: PLC0415

    started = time.monotonic()
    model = ChatterboxTTS.from_pretrained(device=device)
    if reference:
        model.prepare_conditionals(reference, exaggeration=0.5)
    load_s = time.monotonic() - started
    started = time.monotonic()
    with torch.inference_mode():
        model.generate("Ready.", exaggeration=0.5, cfg_weight=0.5)  # warms the kernels
    warm_s = time.monotonic() - started
    return {"ok": True, "sr": int(model.sr), "load_s": load_s, "warm_s": warm_s}


def _speak(req: dict[str, Any]) -> None:
    import numpy as np  # noqa: PLC0415
    import torch  # noqa: PLC0415

    try:
        if model is None:
            raise RuntimeError("not loaded")
        with torch.inference_mode():
            wav = model.generate(
                str(req["text"]),
                exaggeration=float(req["exaggeration"]),
                cfg_weight=float(req["cfg_weight"]),
            )
        pcm = np.ascontiguousarray(wav.squeeze().float().cpu().numpy(), dtype="<f4")
        for i in range(0, len(pcm), _FRAME_SAMPLES):
            body = pcm[i : i + _FRAME_SAMPLES].tobytes()
            _out.write(struct.pack("<I", len(body)) + body)
    except Exception as e:  # noqa: BLE001 - reported to the client, which fails over
        print(f"speak failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        _control({"error": type(e).__name__})
    _out.write(struct.pack("<I", 0))
    _out.flush()


def main() -> None:
    for line in sys.stdin:
        req = json.loads(line)
        op = req.get("op")
        if op == "load":
            try:
                _control(_load(req.get("device", "cuda"), req.get("reference")))
            except Exception as e:  # noqa: BLE001
                print(f"load failed: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
                _control({"ok": False, "error": type(e).__name__})
        elif op == "speak":
            _speak(req)
        elif op == "vram":
            import torch  # noqa: PLC0415

            ok = torch.cuda.is_available()
            _control(
                {
                    "peak_mb": torch.cuda.max_memory_allocated() / 2**20 if ok else 0,
                    "reserved_mb": torch.cuda.memory_reserved() / 2**20 if ok else 0,
                }
            )
        elif op == "quit":
            return


if __name__ == "__main__":
    main()
