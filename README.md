# HomeAssistant-GreeClimateComponent

[![GitHub Release](https://img.shields.io/github/v/release/RobHofmann/HomeAssistant-GreeClimateComponent?sort=semver)](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/releases)
[![License](https://img.shields.io/github/license/RobHofmann/HomeAssistant-GreeClimateComponent)](LICENSE)
[![HACS](https://img.shields.io/badge/HACS-Default-orange.svg)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Compatible-Home_Assistant_2026.3+-blue.svg)](https://www.home-assistant.io)

[![Validate](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/actions/workflows/validate.yaml/badge.svg)](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/actions/workflows/validate.yaml)
[![Lint](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/actions/workflows/lint.yml/badge.svg)](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/actions/workflows/lint.yml)

Gree integration for Home Assistant. It controls Gree air conditioners, and the many brands that use the Gree protocol, over your local network or through the Gree cloud.

## 📖 Documentation

**[Complete documentation](docs/README.md)**, in the `docs/` folder of this repository:

- **[👤 User documentation](docs/README.md#user-documentation)**: installation, configuration, entities, actions, troubleshooting
- **[🔧 Developer documentation](docs/README.md#developer-documentation)**: architecture, protocol, config entry, development

**Quick links:**
[Installation](docs/installation.md) · [Configuration](docs/configuration.md) · [Entities](docs/entities.md) · [Automation examples](docs/automation-examples.md) · [Troubleshooting](docs/troubleshooting.md) · [Supported devices](supported-devices.md) · [Releases](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/releases)

## ✨ Why this integration?

Home Assistant ships a `gree` integration that works on the local network only. This one goes further.

- **Local first, cloud when you need it.** Devices are controlled over UDP on your own network. The Gree cloud is there for devices you cannot reach, and to fetch device names and encryption keys during setup. See [connection methods](docs/connection-methods.md).
- **Every feature the remote has.** X-Fan, Health, Sleep, 8°C Smart Heat, Power Save, Anti Direct Blow, Fresh Air, Humidity Control, display light and brightness, beeper, Turbo and Quiet. Each one is a switch, select or fan mode. See [entities](docs/entities.md).
- **Sensors.** Indoor and outdoor temperature, humidity and fault detection, when the unit has them. An external sensor can replace the unit's own room sensor in the climate entity.
- **Works across VLANs.** Add networks or hosts to the discovery, and they are probed with unicast. See [local discovery](docs/configuration.md#local-discovery).
- **VRF systems.** A controller with several indoor units is discovered and set up as separate devices.
- **Built for real firmware.** Both encryption versions, detected by itself. The request limit of each firmware is measured at bind time, so units that choke on large requests still work. A changed IP is picked up from DHCP or by rediscovery.
- **Set up your way.** A UI flow with reconfigure, or a `gree_custom:` block in YAML. See [configuration](docs/configuration.md).
- **Diagnostics.** A diagnostics download, repair issues, and two actions that read raw device properties. See [actions](docs/actions.md).

## 🚀 Quick start

### Step 1: install with HACS

[HACS](https://hacs.xyz/) must be installed. Then click the button, or search for **Gree** in HACS.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=RobHofmann&repository=HomeAssistant-GreeClimateComponent&category=integration)

1. Click **Download**.
2. Restart Home Assistant.

### Step 2: add the integration

[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=gree_custom)

Or by hand: **Settings** > **Devices & Services** > **Add Integration** > search for **Gree Climate**.

1. Pick **Local network**, **Gree Cloud account**, or both.
2. Pick the devices from the list.
3. Check the connection options and the features of each device. The defaults work for most units.

### Step 3: done

Your devices are under **Settings** > **Devices & Services** > **Gree Climate**. Each one has a climate entity, sensors and switches. See [entities](docs/entities.md) for what they do, and [automation examples](docs/automation-examples.md) for ideas.

📖 **[Full installation guide](docs/installation.md)** · **[Full configuration guide](docs/configuration.md)**

## ⚠️ Issues

Due to the many issues being created revolving "TimeOut"/"Cannot connect" errors, I will be closing these. Feel free to make a PR fixing your TimeOut/Cannot connect error.
More information on the "why" can be found here: https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/issues/405#issuecomment-4300110823

Before you open any other issue, read [Troubleshooting](docs/troubleshooting.md). It says what to include.

## ❓ Help and support

- 🔧 **[Troubleshooting](docs/troubleshooting.md)**: debug logging, repair issues, common errors, and how to report a bug
- 🔑 **[Encryption key](docs/encryption-key.md)**: when the integration cannot get the device key by itself
- 📋 **[Supported devices](supported-devices.md)**: units that are known to work, and how to add yours
- 🐛 **[Report an issue](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/issues/new/choose)**: read the Issues section above first

## 🤝 Contributing

Contributions are welcome. Start with the [contributing guidelines](CONTRIBUTING.md) and the [developer documentation](docs/README.md#developer-documentation).

- **[Development](docs/development.md)**: the devcontainer, lint, the test suite, debug logs, releases
- **[Architecture](docs/architecture.md)**: where the code lives and how a device comes to life
- **[Protocol notes](docs/protocol.md)**: what real units do on the wire
- **[AGENTS.md](AGENTS.md)**: the entry point for coding agents

## 🤖 Development note

Most of this integration was written by hand. Recent work uses AI coding tools more and more, with every change reviewed by the maintainers. Portions of the code, the debugging and the documentation were produced that way. AI helps us move faster, but it can miss an edge case, so if you hit one, [open an issue](https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/issues/new/choose).

Quality is guarded by Ruff, Pylint and Mypy, a pytest suite for the protocol layer, and tests against real units.

## 📄 License

This project is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE).

## 🙏 Credits

This project is based on the work of several contributors and projects:

- [greeclimate-js](https://github.com/davo22/greeclimate-js) - TypeScript library for controlling Gree-based mini-split air conditioning systems
- [greeclimate](https://github.com/davo22/greeclimate) - A fully async Python3 based package for controlling Gree based ACs and heat pumps
- [gree-remote](https://github.com/tomikaa87/gree-remote) - Gree air conditioner remote control protocol
- [greeclimate](https://github.com/cmroche/greeclimate) - Python package for controlling Gree based minisplit systems
- [gree-api-client](https://github.com/luc10/gree-api-client) - Python client for the Gree API
- [Home Assistant Developer Documentation](https://developers.home-assistant.io) - Official development guidelines and best practices
