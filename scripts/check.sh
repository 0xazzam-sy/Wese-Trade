#!/usr/bin/env bash
# Run every quality gate: backend lint/format/types/tests + frontend lint/format/types/tests/build.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/backend/.venv/bin"
[[ -d "$BIN" ]] || BIN="$ROOT/backend/.venv/Scripts"

step() { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }

cd "$ROOT/backend"
step "backend: ruff lint";        "$BIN/ruff" check .
step "backend: ruff format";      "$BIN/ruff" format --check .
step "backend: mypy (strict)";    "$BIN/mypy" app tests alembic
step "backend: pytest";           "$BIN/pytest" -q

cd "$ROOT/frontend"
step "frontend: eslint";          npm run lint
step "frontend: prettier";        npm run format:check
step "frontend: typecheck";       npm run typecheck
step "frontend: vitest";          npm test
step "frontend: build";           npm run build

printf '\n\033[1;32mAll checks passed.\033[0m\n'
