---
phase: 01-always-on-voice-loop
plan: 02
subsystem: supply-chain
tags: [package-legitimacy, pypi, gate]

requires: []
provides:
  - Human verdicts for pocket-tts, moonshine-voice, chatterbox-tts and livekit-wakeword, checked as a precondition by plans 01-22, 01-26, 01-30 and 01-33
affects: [01-22, 01-26, 01-30, 01-33]

commits: 1
actuals:
  tasks: 1
  commits: 1

key-files:
  created:
    - .planning/phases/01-always-on-voice-loop/01-02-SUMMARY.md
---

# Plan 01-02 Summary: Package legitimacy gate

The four voice-stack packages outside the research audit were checked against PyPI and their upstream GitHub repositories on 2026-10-16. The user reviewed the evidence below and approved all four. No package was installed by this plan.

## Package verdicts

User reply, verbatim: "continue", given directly after the evidence table and the recommendation "all four look genuine", in answer to the prompt to approve or reject. Recorded as approved for all four.

| Package | Version | Verdict | Unblocks |
|---------|---------|---------|----------|
| pocket-tts | 3.3.0 | approved | 01-26 |
| moonshine-voice | 0.1.5 | approved | 01-22 |
| chatterbox-tts | 0.1.7 | approved | 01-33 |
| livekit-wakeword | 0.3.0 | approved | 01-30 |

## Evidence

- **pocket-tts 3.3.0.** PyPI metadata has no repository link (summary "Kyutai's pocket-sized text-to-speech!"). The wheel carries a PyPI trusted-publisher attestation from GitHub `kyutai-labs/pocket-tts`, workflow `publish-package.yml`, which ties the upload to the Kyutai repository. PyPI owners `gabrieldemarmiesse` and `rfbr`; `gabrieldemarmiesse` is the top contributor to the repository. The upstream README says `pip install pocket-tts` and its `pyproject.toml` declares `name = "pocket-tts"`. 14 releases since 2026-01-13; the repository was created 2026-01-07.
- **moonshine-voice 0.1.5 (MIT).** PyPI links to `github.com/moonshine-ai/moonshine`, whose README says `pip install moonshine-voice`. PyPI owner `peteuseful`; no attestation. The link between that account and the contributor `petewarden` is not proven. 40 steady releases since 2025-12-31. A `win_amd64` wheel exists.
- **chatterbox-tts 0.1.7 (MIT).** PyPI links to `github.com/resemble-ai/chatterbox`, whose README says `pip install chatterbox-tts` and whose `pyproject.toml` declares `name = "chatterbox-tts"`. Owned by the PyPI organisation `resemble-ai`; no attestation. 8 releases since 2025-05-28.
- **livekit-wakeword 0.3.0 (Apache-2.0).** PyPI links to `github.com/livekit/livekit-wakeword`, whose README says `pip install livekit-wakeword`. Owned by the PyPI organisation `livekit`, author email at `livekit.io`. The wheel carries a trusted-publisher attestation from `livekit/livekit-wakeword`, workflow `publish.yml`. 0.3.0 was published the same day as the 0.2.2 and 0.2.3 back-port releases.

All four names match exactly and no release history shows a surprise new maintainer.

## Limits

- Package contents were not audited. Only pocket-tts and livekit-wakeword have trusted-publisher attestations.
- Installing plans must still pin exact versions in the hash-locked `uv.lock` (chatterbox-tts in its own environment).

## Self-Check: PASSED

- Four verdicts recorded under "Package verdicts".
- No package rejected, so no blocker added to STATE.md.
