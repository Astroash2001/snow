# Training the "Hey Snow" wake word

Snow listens for its wake phrase locally with a small ONNX model. This folder is the
pinned recipe that produces that model. Training needs a GPU and runs in Google Colab
under your own Google account; nothing here runs on the laptop except the two optional
steps marked "on this PC".

- Tool: **livekit-wakeword 0.3.0** (Apache-2.0), pinned as `livekit-wakeword==0.3.0`.
  Approved in plan 01-02. The YAML key names and the CLI stages below were checked
  against the 0.3.0 source release (`config.py`, `cli.py`).
- Config: `hey_snow.yaml` (conv-attention head, the default). `hey_snow_dnn.yaml` is the
  same recipe with the openWakeWord-style DNN head, used only if Snow cannot load the
  conv-attention export.
- Expected time: the recipe has not been timed yet. Plan for an afternoon: the `setup`
  step downloads about 16 GB of training features, then generate, augment and train run
  on the GPU. Keep the Colab tab open; a disconnected runtime loses everything under
  `/content` and must start again.

## 1. Optional, on this PC: record your room as negatives

Real room audio (TV, typing, talk that is not "Hey Snow") teaches the model what not to
wake on. With the TV and normal room noise on, and without saying "Hey Snow":

```powershell
uv run snow dev record-negatives --minutes 60 --out C:\SnowNegatives
```

It writes 10-minute 16 kHz WAV files. The folder must be outside this repository and
outside the Snow data folder; the command refuses anything else.

## 2. In Colab: train

1. Open https://colab.research.google.com, create a new notebook, then
   **Runtime > Change runtime type > GPU** (a free T4 works; L4 is faster).
2. In the **Files** panel (folder icon), upload `hey_snow.yaml` to `/content`.
   If you recorded negatives, create the folder `/content/negatives` and upload the WAV
   files into it.
3. Run these cells in order, one per cell:

```bash
!apt-get -qq install -y espeak-ng libsndfile1 ffmpeg sox
```

```bash
# Download the pinned wheel and check it is the exact file approved in plan 01-02.
!pip download --no-deps livekit-wakeword==0.3.0 -d /content/wheel
!echo "6bb00b832c21720ebb94410e005854740b2d36b20970c7cecc74b5e889d94f4b  /content/wheel/livekit_wakeword-0.3.0-py3-none-any.whl" | sha256sum -c
!pip install -q "/content/wheel/livekit_wakeword-0.3.0-py3-none-any.whl[train,eval,export]"
```

```bash
%cd /content
!livekit-wakeword setup --config hey_snow.yaml
```

```bash
!livekit-wakeword generate hey_snow.yaml
```

```bash
!livekit-wakeword augment hey_snow.yaml
```

```bash
!livekit-wakeword train hey_snow.yaml
```

```bash
!livekit-wakeword export hey_snow.yaml
```

```bash
!livekit-wakeword eval hey_snow.yaml
```

The stages are `setup` (downloads Piper voices, training features, room impulse
responses and background noise), `generate` (synthetic "hey snow" clips and the
look-alike phrases from the YAML), `augment` (noise, reverb, feature extraction),
`train`, `export` (ONNX) and `eval` (false positives per hour, recall, threshold).
`livekit-wakeword run hey_snow.yaml` does generate to eval in one go if you prefer.

4. Download the results from `/content/output/hey_snow/`:
   - `hey_snow.onnx` (the model)
   - `hey_snow_eval.json` (the numbers: AUT, FPPH, recall, threshold)
   - `hey_snow_det.png` (the DET curve)

```python
from google.colab import files
for name in ("hey_snow.onnx", "hey_snow_eval.json", "hey_snow_det.png"):
    files.download(f"/content/output/hey_snow/{name}")
```

## 3. On this PC: put the model in place

1. Save the model as `models/wakeword/hey_snow.onnx` in this repository folder. The
   `models/` folder is gitignored, so the model is never committed.
2. Record its SHA-256 (Snow refuses the file if it changes):

```powershell
certutil -hashfile models\wakeword\hey_snow.onnx SHA256
```

3. Hand the hash and the numbers from `hey_snow_eval.json` back to Claude. Plan 01-30
   Task 3 then sets `[wake] model`, `model_sha256` and `threshold` in
   `config/voice.toml` and runs the acceptance checks below.

## Fallback recipe

If livekit-wakeword fails in Colab, use the community notebook
`alfiedennen/openwakeword-colab-2026` (MIT), pinned to commit
`da4d92a64fadb803d67866075af870e5161fd9eb`:

https://colab.research.google.com/github/alfiedennen/openwakeword-colab-2026/blob/da4d92a64fadb803d67866075af870e5161fd9eb/train_wakeword.ipynb

In cell 10 set `TARGET_PHRASE = ['hey snow']` and `MODEL_NAME = 'hey_snow'`, then
**Runtime > Run all**. It produces an openWakeWord-format `hey_snow.onnx` in about
75-90 minutes on an L4 and about 2.5 hours on a free T4 (the notebook's own figures).
Place and hash it exactly as in section 3.

## Acceptance targets

Measured on this PC with the hardware wake test (`tests/hardware/test_wake_fp.py`),
Snow stopped so the test has the microphone:

- False accepts: **under 1 per hour** over at least 2 hours of real ambient and TV
  audio.
  `uv run pytest -m hardware tests/hardware/test_wake_fp.py -k false_accepts -s -q`
- Recall: **at least 90 %** of 50 "Hey Snow" said by you at three distances (arm's
  length, across the room, from the doorway).
  `uv run pytest -m hardware tests/hardware/test_wake_fp.py -k recall -s -q`

If a target is missed, adjust `[wake] threshold` once and re-run the failing check.

## Privacy

- The negatives are your own room recordings. They stay in the folder you chose and
  leave this PC only when you upload them to your own Colab session.
- Conversation audio is never used for training: Snow does not store it, and
  `record-negatives` is the only thing that writes training audio.
- The trained model runs locally; no audio is sent anywhere to detect the wake phrase.
