#!/usr/bin/env bash
# One command to set up and run the backend:  ./dev.sh
#
# Exists because two things bite people on a fresh Mac and both produce
# confusing errors:
#
#   1. Pasting a command with a trailing "# comment" into zsh. macOS zsh ships
#      with interactive_comments OFF, so the "#" is NOT a comment - it becomes an
#      argument, and `source .venv/bin/activate  # ... (.venv)` dies with
#      "zsh: unknown file attribute: v" because zsh parses (.venv) as a glob
#      qualifier. The venv silently never activates and every command after it
#      fails with "command not found".
#
#   2. Creating the venv with a Python newer than the pinned wheels support.
#      pip then tries to compile numpy and pydantic-core from source and fails
#      several screens later with a wall of C and Rust errors.
#
# This script checks for both, and is idempotent - run it as often as you like.

set -euo pipefail
cd "$(dirname "$0")/backend"

MIN_MINOR=10
MAX_MINOR=13

find_python() {
    # Prefer the newest supported interpreter that is actually installed.
    for minor in $(seq $MAX_MINOR -1 $MIN_MINOR); do
        if command -v "python3.$minor" >/dev/null 2>&1; then
            echo "python3.$minor"; return 0
        fi
    done
    # Fall back to bare python3 only if it is in range.
    if command -v python3 >/dev/null 2>&1; then
        local minor
        minor=$(python3 -c 'import sys; print(sys.version_info.minor)')
        if [ "$minor" -ge "$MIN_MINOR" ] && [ "$minor" -le "$MAX_MINOR" ]; then
            echo "python3"; return 0
        fi
    fi
    return 1
}

if [ ! -d .venv ]; then
    echo "==> No virtualenv yet. Looking for a supported Python..."
    if ! PY=$(find_python); then
        FOUND=$(python3 --version 2>&1 || echo "none")
        cat <<MSG

  Could not find a Python between 3.$MIN_MINOR and 3.$MAX_MINOR.
  Your default python3 is: $FOUND

  The pinned dependencies (numpy, pydantic-core, psycopg2-binary) publish
  wheels up to 3.$MAX_MINOR. On anything newer, pip has to compile them from
  source, which needs a full C and Rust toolchain and usually fails.

  Install a supported one:

      brew install python@3.13

  ...then run ./dev.sh again. Nothing else needs to change.

MSG
        exit 1
    fi
    echo "==> Using $PY ($($PY --version))"
    "$PY" -m venv .venv
else
    VENV_VER=$(.venv/bin/python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    VENV_MINOR=${VENV_VER#*.}
    if [ "$VENV_MINOR" -gt "$MAX_MINOR" ] || [ "$VENV_MINOR" -lt "$MIN_MINOR" ]; then
        cat <<MSG

  The existing .venv was built with Python $VENV_VER, which is outside the
  supported range 3.$MIN_MINOR - 3.$MAX_MINOR. Installing into it will fail
  when pip tries to compile numpy and pydantic-core from source.

  Delete it and re-run this script:

      rm -rf backend/.venv && ./dev.sh

MSG
        exit 1
    fi
fi

# shellcheck disable=SC1091
source .venv/bin/activate
echo "==> Virtualenv active: $(python --version)"

echo "==> Installing dependencies (quiet; first run takes a minute)..."
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements-dev.txt

[ -f .env ] || { cp .env.example .env; echo "==> Created backend/.env (SQLite, no database to install)"; }

echo "==> Running the test suite..."
python -m pytest -q

cat <<'MSG'

==> Tests pass. Starting the API on http://localhost:8000
    Interactive docs: http://localhost:8000/docs
    Stop with Ctrl+C.

    Now open a SECOND terminal and run:
        cd ~/BASE/02-projects/AlphaRiskIQ/frontend && npm run dev
    then browse to http://localhost:5173

MSG

exec uvicorn app.main:app --reload
