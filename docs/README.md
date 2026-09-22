# Documentation

Two sets of documents live here. The first is for people who use the integration. The second is for people and coding agents who work on the code.

All docs follow the writing rules in `AGENTS.md`: plain English, short sentences, no filler.

## User documentation

| File | Read it when |
|---|---|
| [installation.md](installation.md) | You install or update the integration, or you come from a 4.x release. |
| [configuration.md](configuration.md) | You set the integration up in the UI or in YAML, or you want to know what an option does. |
| [connection-methods.md](connection-methods.md) | You want to know how local, cloud and mixed setups work, and which one a device uses. |
| [entities.md](entities.md) | You want to know which entities you get, what they do, and when they are available. |
| [actions.md](actions.md) | You want to read raw device properties, or download diagnostics. |
| [encryption-key.md](encryption-key.md) | The integration cannot get the device key by itself. |
| [troubleshooting.md](troubleshooting.md) | Something does not work. Debug logging, repair issues, common errors, and how to report a bug. |
| [../supported-devices.md](../supported-devices.md) | You want to know if your unit is known to work. |

## Developer documentation

| File | Read it when |
|---|---|
| [architecture.md](architecture.md) | You need to know where code lives, how a device is set up, or how state flows. |
| [protocol.md](protocol.md) | You touch anything that talks to a device: encryption, requests, discovery, MACs, cloud. |
| [config-entry.md](config-entry.md) | You read or change the config entry, or add a config option. |
| [development.md](development.md) | You set up the devcontainer, run lint, run the tests, test against a device, or debug logs. |
| `../tests/` | The pytest suite for the protocol layer, with the fake devices it runs against. Described in [development.md](development.md#testing). |
| `../tools/` | Command line scripts that use the protocol layer directly, such as `probe_status_limit.py` to measure a unit's request limits. Described in [development.md](development.md#tools). |

`AGENTS.md` in the repo root is the short entry point for coding agents. It links here for the details. `CONTRIBUTING.md` has the step by step setup of the development environment.

A change in behavior that a user can see needs a change in the user documentation too. The entity docs and the option tables are checked against the code, so keep them exact.
