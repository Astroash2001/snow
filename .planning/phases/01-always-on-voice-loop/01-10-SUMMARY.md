---
phase: 01-always-on-voice-loop
plan: 10
subsystem: ci
tags: [ci, github-actions, gitleaks, pip-audit, npm-audit, pre-push, quality-gate]
status: complete

requires:
  - phase: 01-always-on-voice-loop/01-06
    provides: snow CLI and the test suite the gates run
  - phase: 01-always-on-voice-loop/01-07
    provides: hud/package.json and npm scripts lint/typecheck/test/gen:types
  - phase: 01-always-on-voice-loop/01-09
    provides: hud/playwright.config.ts and the Electron e2e suite
provides:
  - ".github/workflows/ci.yml: jobs python, hud (windows-latest) and security (ubuntu-latest)"
  - ".gitleaks.toml: default rules plus Snow's provider key prefixes"
  - "scripts/check.sh: the single local gate, run by .githooks/pre-push"
affects: [all later plans: every push runs these gates]

commits: 2
plan_head_before: 83f6a1c6e17db68115fd9fc9be63ea501ddb810b
plan_head_after: 64b6246

actuals:
  tokens: 4500
  tasks: 2
  commits: 2

tech-stack:
  added: [gitleaks 8.30.1 (CI binary, SHA-256 verified)]
  patterns:
    - "Every `uses:` pinned to a 40-char commit SHA with the release tag in a comment"
    - "pip-audit runs on `uv export --frozen` output (hashed lock), so `--strict` does not trip on the editable snow package"
    - "HUD job guard is a step output: `hashFiles()` is not allowed in a job-level `if`"

key-files:
  created:
    - .github/workflows/ci.yml
    - .gitleaks.toml
    - .githooks/pre-push
    - scripts/check.sh
    - .gitattributes
  modified: []

key-decisions:
  - "pip-audit was already in the dev group and uv.lock, so no dependency change; CI audits the exported lock (runtime + dev) with --strict --disable-pip"
  - "gitleaks runs from the official release tarball verified by SHA-256, not gitleaks-action (which downloads its binary unverified and wants extra PR permissions)"
  - "The gitleaks allowlist also covers .planning/ docs, AND-ed with an obviously-fake value pattern, because plan 01-11 quotes the test canaries and history cannot be rewritten"

metrics:
  duration: "~25 min"
  completed: 2026-10-19
---

# Phase 1 Plan 10: CI and local quality gate Summary

Windows CI workflow (python, hud, security jobs, every action SHA-pinned, read-only token), Snow-specific gitleaks rules, and a pre-push hook that runs the shared `scripts/check.sh`. Pushed to the private repo Astroash2001/snow on the user's "yes push" (2026-10-25); CI green.

## Status: complete (2026-10-25)

- `origin` is https://github.com/Astroash2001/snow (PRIVATE, verified with `gh repo view`); `core.hooksPath` is `.githooks`.
- First pushes found pre-existing CI failures, fixed before green: pip-audit flagged pillow, certifi, filelock and setuptools (52465a9: fixed releases let past the exclude-newer cutoff, Pillow 13 overrides pipecat-ai 1.12.0's <13 cap), and two HUD e2e races on the slower runner (52465a9, 65cd78f, 690c6b5).
- First green run: 40129871671 on 690c6b5 (python, hud, security).
- Human check, shown by real events instead of a throwaway branch: the pre-push hook refused a push on a ruff E501 failure, and runs 40125671072 and 40128969087 went red on main with the failures above.

## Pinned actions

| Action | Tag | Commit SHA |
|--------|-----|------------|
| actions/checkout | v7.0.1 | 3d3c42e5aac5ba805825da76410c181273ba90b1 |
| astral-sh/setup-uv | v10.3.0 | 1c37ad07a6a961277cf70c0d37d6f313000f5884 |
| actions/cache | v6.1.0 | 55cc8345863c7cc4c66a329aec7e433d2d1c52a9 |
| actions/setup-node | v7.1.0 | 949feb2413d6458794dcd2491c4babbbce0c15c1 |
| actions/upload-artifact | v7.0.2 | cf430e030ddbb5b0abf93d22962f4752f3646cd9 |
| gitleaks (binary) | v8.30.1 | linux_x64 tarball SHA-256 551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb |

Tags resolved with `gh api repos/<owner>/<repo>/commits/<tag>`; the gitleaks checksum comes from the release's `checksums.txt`. Inputs used were checked against each pinned `action.yml`.

## Local verification

- `bash scripts/check.sh`: exit 0. ruff clean, 128 files formatted, pyright 0 errors, pytest 512 passed / 13 deselected, contract drift clean, Biome/tsc clean, Vitest 190 passed; gitleaks not on PATH so the notice printed. (The first run failed at Biome only because this fresh worktree had no `hud/node_modules`; `npm --prefix hud ci` from the existing lock fixed it. The main clone already has them.)
- CI-only steps run locally: `scripts/make_audio_fixtures.py --check` all 13 PASS; `npm run gen:types` leaves `hud/src/generated` unchanged.
- `actionlint` 1.7.12 on ci.yml: clean. YAML parses (python yaml).
- gitleaks 8.30.1 with `.gitleaks.toml` over full history (140 commits): no leaks; a scratch file with five realistic fake keys (gsk_, sk_car_, xpl_, nvapi-, sk-or-) produced 5 findings, so the rules fire.
- `pip-audit --strict --disable-pip` over the exported lock (runtime + dev): no known vulnerabilities.
- `npm --prefix hud audit --omit=dev --audit-level=high`: 0 vulnerabilities.
- `git ls-files -s`: `.githooks/pre-push` and `scripts/check.sh` are mode 100755.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Job-level `hashFiles()` guard is invalid**
- **Issue:** `jobs.hud.if: hashFiles('hud/package.json') != ''` is rejected by GitHub (hashFiles is only available in steps).
- **Fix:** a first step writes `present=${{ hashFiles('hud/package.json') != '' }}` to `$GITHUB_OUTPUT`; every HUD step is guarded on it. The e2e step keeps its `hashFiles('hud/playwright.config.ts')` guard.
- **Commit:** c603d0f

**2. [Rule 1 - Bug] `pip-audit --strict` fails on the editable project**
- **Issue:** `uv run pip-audit --strict` exits 1 ("snow: distribution marked as editable"), with or without `--skip-editable`.
- **Fix:** audit the hashed lock instead: `uv export --frozen --no-emit-project` then `pip-audit --strict --disable-pip -r`. Same packages, exact pins, still strict.
- **Commit:** c603d0f

**3. [Rule 1 - Bug] Multi-line steps did not fail fast on Windows**
- **Issue:** pwsh only checks the last command's exit code, so a failing `gen:types` would be followed by a passing `git diff`.
- **Fix:** `shell: bash` (fail-fast `-e`) on the generated-types and pip-audit steps.
- **Commit:** c603d0f

**4. [Rule 3 - Blocking] CRLF would break the bash scripts**
- **Issue:** `core.autocrlf=true` checks `.sh` files out with CRLF, which bash rejects.
- **Fix:** root `.gitattributes` with `*.sh text eol=lf` and `.githooks/* text eol=lf`.
- **Commit:** 64b6246

**5. [Rule 3 - Blocking] Plan docs quote fake test keys**
- **Issue:** full-history gitleaks flagged `gsk_abc123...` and `gsk_CANARY...` in `01-11-PLAN.md` (fake test canaries).
- **Fix:** the allowlist path covers `^(tests|\.planning)/`, still AND-ed with the fake-value regex, so a real key in either place is still caught.
- **Commit:** 64b6246

### Notes

- `scripts/check.sh` uses the default pytest markers from `pyproject.toml` addopts (excludes hardware, gpu, slow, network). CI uses the plan's `-m "not hardware and not gpu and not network"`, which overrides addopts and also runs the `slow` real-model tests; the `models/` and Hugging Face cache (static key `models-v1`) keeps them from re-downloading. Locally that marker set gave 516 passed, 1 skipped, 8 deselected in 4 min 12 s.
- The Electron e2e suite (plan 01-09) was not run locally; its visual snapshots were recorded on this laptop and may differ on the hosted runner (fonts, GPU). Watch the first CI run.
- `test_hub_launches_workers_with_scrubbed_env` passed here; it can error in the main clone if the real Snow hub is running.
- `git config core.hooksPath .githooks` was NOT run here; the orchestrator runs it in the main clone after the merge (it is per-clone config).

## Steps left after the user approves a push

1. `gh auth status` (precondition).
2. `git remote get-url origin` fails, so: `gh repo view <account>/snow`; if free, `gh repo create snow --private --source . --remote origin`, otherwise use `snow-assistant`. Never public (D-41).
3. In the main clone: `git config core.hooksPath .githooks`.
4. `git push -u origin main` (the pre-push hook runs check.sh first).
5. `gh run list --workflow ci.yml --branch main --limit 1 --json conclusion --jq ".[0].conclusion"` must print `success`; `gh repo view --json visibility --jq .visibility` must print `PRIVATE`.
6. Human check: on a throwaway branch add a test file with a failing assertion, `git push -u origin <branch>` must be refused by the hook; `git push --no-verify -u origin <branch>` must give a red CI run; then delete the branch locally and on GitHub.

## Actions minutes

GitHub Free private repositories get 2,000 Actions minutes a month and Windows runners count double, so roughly 100 full CI runs a month fit; heavy CI usage may need the public-repo option or trimming jobs (for example running the slow real-model tests or e2e only on `main`).

## Threat Flags

None beyond the plan's threat model. T-01-10 (gitleaks in CI and hook), T-01-11 (SHA pins, `contents: read`, `persist-credentials: false`) and T-01-SC (pip-audit, npm audit, frozen lockfiles) are mitigated in the files; they take effect once the remote exists.

## Self-Check: PASSED

All five created files exist; commits c603d0f and 64b6246 are on HEAD; `git rev-list --count 83f6a1c..HEAD` = 2 before this SUMMARY commit.
