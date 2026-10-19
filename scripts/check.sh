#!/usr/bin/env bash
# Local quality gate (QUAL-01), run by .githooks/pre-push. Mirrors .github/workflows/ci.yml.
# Run from anywhere: bash scripts/check.sh
set -euo pipefail

root="$(git rev-parse --show-toplevel)"
cd "$root"

step() { printf '\n==> %s\n' "$*"; "$@"; }

step uv run ruff check src tests
step uv run ruff format --check src tests
step uv run pyright
step uv run pytest -q
step uv run python -m snow.contracts.export --check

if [ -f hud/package.json ]; then
  step npm --prefix hud run lint
  step npm --prefix hud run typecheck
  step npm --prefix hud run test
fi

if command -v gitleaks >/dev/null 2>&1; then
  step gitleaks protect --staged --config .gitleaks.toml --redact --no-banner
else
  printf '\nnotice: gitleaks not on PATH, local secret scan skipped (CI still runs it)\n'
fi

printf '\nAll checks passed.\n'
