[![HACS](https://img.shields.io/badge/HACS-Default-orange.svg)](https://hacs.xyz)
[![Home Assistant](https://img.shields.io/badge/Compatible-Home_Assistant_2026.3+-blue.svg)](https://www.home-assistant.io)

# HomeAssistant-GreeClimateComponent

Gree integration for Home Assistant. It controls Gree air conditioners and units that use the Gree protocol, over the local network (preferred) or through the Gree cloud.

The full documentation is in [docs/](docs/README.md).

## Quick start

1. Install with HACS: search for **Gree** in the HACS dashboard. See [Installation](docs/installation.md).
2. Go to **Settings** > **Devices & Services** > **Add Integration** and search for **Gree Climate**.
3. Choose local discovery, a Gree cloud account, or both. Pick the devices and set their options. See [Configuration](docs/configuration.md).

YAML configuration is also supported. See [YAML configuration](docs/configuration.md#yaml-configuration) and [`manual-configuration.yaml`](manual-configuration.yaml).

## Documentation

| Read | When |
|---|---|
| [Installation](docs/installation.md) | Install, update, or move from an older version. |
| [Configuration](docs/configuration.md) | The setup flow, every option, YAML, reconfigure. |
| [Connection methods](docs/connection-methods.md) | Local, cloud, or both, and how they are combined. |
| [Entities](docs/entities.md) | The climate entity, sensors, switches, selects and what each one does. |
| [Actions](docs/actions.md) | The `get_prop_values` and `get_prop_values_all` actions, and the diagnostics download. |
| [Encryption key](docs/encryption-key.md) | When the key is not found by itself, and how to get it. |
| [Troubleshooting](docs/troubleshooting.md) | Debug logging, repair issues, common errors, and how to report a bug. |
| [Supported devices](supported-devices.md) | Units that are known to work. |

Developer documentation starts at [docs/README.md](docs/README.md#developer-documentation). Coding agents start at [AGENTS.md](AGENTS.md).

## Issues

Due to the many issues being created revolving "TimeOut"/"Cannot connect" errors, I will be closing these. Feel free to make a PR fixing your TimeOut/Cannot connect error.
More information on the "why" can be found here: https://github.com/RobHofmann/HomeAssistant-GreeClimateComponent/issues/405#issuecomment-4300110823

Before you open any other issue, read [Troubleshooting](docs/troubleshooting.md). It says what to include.

## Credits

Portions of the code development, debugging, and documentation were performed by Large Language Models (LLMs)

This project is based on the work of several contributors and projects:

- [greeclimate-js](https://github.com/davo22/greeclimate-js) - TypeScript library for controlling Gree-based mini-split air conditioning systems
- [greeclimate](https://github.com/davo22/greeclimate) - A fully async Python3 based package for controlling Gree based ACs and heat pumps
- [gree-remote](https://github.com/tomikaa87/gree-remote) - Gree air conditioner remote control protocol
- [greeclimate](https://github.com/cmroche/greeclimate) - Python package for controlling Gree based minisplit systems
- [gree-api-client](https://github.com/luc10/gree-api-client) - Python client for the Gree API
- [Home Assistant Developer Documentation](https://developers.home-assistant.io) - Official development guidelines and best practices
