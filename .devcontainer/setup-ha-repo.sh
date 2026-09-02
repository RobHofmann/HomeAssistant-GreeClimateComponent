#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

HA_SRC_DIR="${HA_SRC_DIR:-.ha-core}"

if [ -d "$HA_SRC_DIR/.git" ]; then
    echo "==> Home Assistant core already cloned, updating"
    git -C "$HA_SRC_DIR" fetch --depth 1 origin dev
    git -C "$HA_SRC_DIR" checkout dev
    git -C "$HA_SRC_DIR" reset --hard origin/dev
else
    echo "==> Cloning Home Assistant core from the 'dev' branch"
    git clone --progress --depth 1 --branch dev \
        https://github.com/home-assistant/core.git "$HA_SRC_DIR"
fi