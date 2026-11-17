#!/bin/sh
set -eu

cd -P -- "$(dirname "$0")"
export PATH="/opt/homebrew/bin:/usr/local/bin:$HOME/.docker/bin:$PATH"

if [ -x .venv/bin/python ]; then
    python=.venv/bin/python
else
    python=python3
fi

if ! command -v "$python" >/dev/null 2>&1; then
    echo "Install Python 3.10 or newer and see README.md." >&2
    exit 1
fi

exec "$python" injector.py serve --open
