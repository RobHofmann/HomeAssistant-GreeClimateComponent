#!/usr/bin/env bash
# Runs once when the devcontainer is created (or on "Rebuild Container").
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root

echo "==> Ensuring Python virtual environment exists"

if [ -d ".venv" ]; then
    echo "==> Reusing existing virtual environment"
else
    echo "==> Creating new virtual environment"
    python3 -m venv .venv
fi

echo "==> Upgrading pip/setuptools/wheel"
.venv/bin/python -m pip install --upgrade pip setuptools wheel

# echo "==> Installing Home Assistant core from the 'dev' branch"
# # pip's own "git+..." install clones with --quiet and a blobless partial
# # filter, which on a repo this size can sit silent for minutes looking
# # frozen. Clone it ourselves first (shallow, --progress forced on even
# # though this isn't an interactive terminal) so there's visible feedback,
# # then install from the local path.
# HA_SRC_DIR="$(mktemp -d)"
# git clone --progress --depth 1 --branch dev \
#   https://github.com/home-assistant/core.git "$HA_SRC_DIR"
# .venv/bin/python -m pip install --upgrade "$HA_SRC_DIR"
# rm -rf "$HA_SRC_DIR"

echo "==> Cloning Home Assistant core from the 'dev' branch"

HA_SRC_DIR=".ha-core"

if [ -d "$HA_SRC_DIR/.git" ]; then
    echo "==> Home Assistant core already cloned, updating"
    git -C "$HA_SRC_DIR" fetch --depth 1 origin dev
    git -C "$HA_SRC_DIR" checkout dev
    git -C "$HA_SRC_DIR" reset --hard origin/dev
else
    git clone --progress --depth 1 --branch dev \
      https://github.com/home-assistant/core.git "$HA_SRC_DIR"
fi

echo "==> Installing Home Assistant core"
.venv/bin/python -m pip install --upgrade --no-cache-dir --editable "$HA_SRC_DIR" --config-settings editable_mode=compat

echo "==> Installing colorlog for colored console logs"
# Not a declared dependency of the homeassistant package itself - HA's own
# official dev setup docs install it as a separate explicit package
# alongside the core install for exactly this reason. Without it,
# async_enable_logging's "from colorlog import ColoredFormatter" silently
# fails (bare except ImportError: pass) and falls back to plain text.
.venv/bin/python -m pip install --upgrade colorlog

echo "==> Installing system dependencies for default_config: (ffmpeg, libturbojpeg, libpcap)"
sudo apt-get update
sudo apt-get install -y --no-install-recommends ffmpeg libturbojpeg0 libpcap-dev
sudo rm -rf /var/lib/apt/lists/*

echo "==> Installing go2rtc binary (needed by default_config:, not available via apt)"
GO2RTC_ARCH="$(dpkg --print-architecture)"   # amd64 | arm64
case "$GO2RTC_ARCH" in
  amd64) GO2RTC_ASSET="go2rtc_linux_amd64" ;;
  arm64) GO2RTC_ASSET="go2rtc_linux_arm64" ;;
  *) echo "    (unrecognized arch '$GO2RTC_ARCH', skipping go2rtc install)"; GO2RTC_ASSET="" ;;
esac
if [ -n "$GO2RTC_ASSET" ]; then
  sudo curl -fL "https://github.com/AlexxIT/go2rtc/releases/latest/download/${GO2RTC_ASSET}" \
    -o /usr/local/bin/go2rtc
  sudo chmod +x /usr/local/bin/go2rtc
fi

echo "==> Installing dev/lint tooling"
if [ -f requirements_dev.txt ]; then
  .venv/bin/python -m pip install --upgrade -r requirements_dev.txt
fi


echo "==> Wiring up config/custom_components -> ../custom_components"
mkdir -p config
if [ ! -e config/custom_components ]; then
  ln -s ../custom_components config/custom_components
fi

echo "==> Ensuring config/configuration.yaml exists"
if [ ! -f config/configuration.yaml ]; then
  # Let Home Assistant itself generate the default config directory/files -
  # this is what "hass --script ensure_config" is for, and it's what
  # integration_blueprint's own setup script does too. Beats hand-writing
  # a configuration.yaml that can drift from what core actually defaults to.
  .venv/bin/python -m homeassistant --script ensure_config --config config

  # Add debug logging for custom_components on top of the generated default.
  cat >> config/configuration.yaml <<'YAML'

# Added by postCreate.sh
logger:
  default: info
  logs:
    custom_components: debug
YAML
fi

echo "==> Done. Run the 'Run Home Assistant' task, or press F5, to start."
