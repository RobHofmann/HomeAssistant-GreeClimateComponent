#!/usr/bin/env bash
# Runs once when the devcontainer is created (or on "Rebuild Container").
set -euo pipefail

cd "$(dirname "$0")/.."   # repo root

# Requirements mirrored from official HA Devcontainer
echo "==> Installing system dependencies"
sudo apt-get update
sudo apt-get install -y --no-install-recommends bluez ffmpeg libudev-dev libavformat-dev libavcodec-dev libavdevice-dev libavutil-dev libswscale-dev libswresample-dev libavfilter-dev libpcap-dev libturbojpeg0 libyaml-dev libxml2 git cmake autoconf
sudo apt-get clean
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

echo "==> Ensuring Python virtual environment exists"

if [ -d ".venv" ]; then
    echo "==> Reusing existing virtual environment"
else
    echo "==> Creating new virtual environment"
    python3 -m venv .venv
fi

echo "==> Activate VENV"
source .venv/bin/activate

echo "==> Upgrading pip/setuptools/wheel"
python -m pip install --upgrade pip setuptools wheel


HA_SRC_DIR=".ha-core"

echo "==> Ensuring Home Assistant core is available"
./.devcontainer/setup-ha-repo.sh

echo "==> Installing Home Assistant"
./.devcontainer/setup-ha-core.sh

echo "==> Compiling Home Assistant translations"
(
    cd $HA_SRC_DIR || exit 1
    python -m script.translations develop --all
)

echo "==> Installing dev/lint tooling"
if [ -f requirements_dev.txt ]; then
  python -m pip install --upgrade -r requirements_dev.txt
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
  python -m homeassistant --script ensure_config --config config

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
