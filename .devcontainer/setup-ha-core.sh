#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export UV_CACHE_DIR="$PWD/.uv-cache"
HA_SRC_DIR="${HA_SRC_DIR:-.ha-core}"
VENV_DIR="${VENV_DIR:-.venv}"

PYTHON="$VENV_DIR/bin/python"

if [ ! -x "$PYTHON" ]; then
    echo "ERROR: Python virtual environment not found at $VENV_DIR"
    exit 1
fi

if [ ! -d "$HA_SRC_DIR" ]; then
    echo "ERROR: Home Assistant core directory '$HA_SRC_DIR' does not exist."
    exit 1
fi

echo "==> Installing Home Assistant core requirements"

"$PYTHON" -m pip install --no-cache-dir \
    "uv==$(awk -F'==' '/^uv==/{print $2}' "$HA_SRC_DIR/requirements.txt")"

"$PYTHON" -m uv pip install --upgrade colorlog

"$PYTHON" -m uv pip install -r "$HA_SRC_DIR/requirements.txt"
"$PYTHON" -m uv pip install -r "$HA_SRC_DIR/requirements_test.txt"
"$PYTHON" -m uv pip install -r "$HA_SRC_DIR/requirements_all.txt"

echo "==> Installing Home Assistant core"
"$PYTHON" -m uv pip install --upgrade --no-cache-dir --editable "$HA_SRC_DIR" --config-settings editable_mode=compat