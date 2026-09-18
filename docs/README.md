# Developer documentation

Documentation for people and coding agents who work on the code. User documentation is in the repo root `README.md`.

| File | Read it when |
|---|---|
| [architecture.md](architecture.md) | You need to know where code lives, how a device is set up, or how state flows. |
| [protocol.md](protocol.md) | You touch anything that talks to a device: encryption, requests, discovery, MACs, cloud. |
| [config-entry.md](config-entry.md) | You read or change the config entry, or add a config option. |
| [development.md](development.md) | You set up the devcontainer, run lint, test against a device, or debug logs. |
| `../tools/` | Command line scripts that use the protocol layer directly, such as `probe_status_limit.py` to measure a unit's request limits. Described in [development.md](development.md#tools). |

`AGENTS.md` in the repo root is the short entry point for coding agents. It links here for the details.

All docs follow the writing rules in `AGENTS.md`: plain English, short sentences, no filler.
