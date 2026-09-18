# AGENTS.md

Short guide for coding agents working on this repository. Read this first. The details live in `docs/`; read those only when your task needs them.

## What this is

A custom Home Assistant integration for Gree air conditioners. Domain `gree_custom`, folder `custom_components/gree_custom/`. It talks to devices over local UDP and can also use the Gree Cloud over MQTT.

The domain is `gree_custom` and not `gree` because Home Assistant ships its own `gree` integration. Do not rename it.

Older releases (4.x) used the domain `gree` and a different code base. Their config entries are not compatible with this version and there is no migration.

## Versions

- Python 3.14. Home Assistant 2026.3 or newer.
- Python 3.14 syntax is used on purpose, for example `except A, B:` without brackets (PEP 758). Do not "fix" it. Check the code with a 3.14 interpreter, not an older one.

## Where to read more

| Task | Read |
|---|---|
| Find where code lives, how a device is set up, how state and availability work | [docs/architecture.md](docs/architecture.md) |
| Touch encryption, requests, batching, discovery, MACs or cloud | [docs/protocol.md](docs/protocol.md) |
| Read or change the config entry, add a config option | [docs/config-entry.md](docs/config-entry.md) |
| Set up the devcontainer, run lint, test against a device, read debug logs, translations, releases | [docs/development.md](docs/development.md) |
| Set up the environment step by step | `CONTRIBUTING.md` |

## Rules

Secrets:

- Never log an encryption key, cloud password or token in clear text. Use `redact_str()` for values and `async_redact_data()` for dicts, as the existing code does.

Code:

- Match the style of the code around you. Do not reformat lines you did not need to touch.
- The version in `manifest.json` belongs to the maintainers. Do not change it in a normal PR unless asked.
- There is no unit test suite. Test against a real device, or against a fake device that speaks the protocol, and say in the PR which one you did.

Writing, for everything you produce in this repo:

- English for all output: code, comments, docstrings, docs, commit messages, PR titles and PR descriptions. Chat with the user can follow the user's own language.
- Plain and simple English. No vague or padded text. Say what it is and stop.
- Sentence structure at B2 level or lower. Word choice at B1 level or lower. Technical terms are fine when there is no simpler word.
- Do not use em dashes.
- Do not mention AI tools in commits, PRs or branch names.
- Keep this file short. New knowledge goes into `docs/`, with a row in the table above if it is a new topic.

## Before you open a PR

- [ ] Ruff, Pylint and Mypy pass.
- [ ] Both encryption versions are covered by your reasoning if you touched keys, ciphers or transports.
- [ ] No new secret can reach a log line.
- [ ] You tested against a real device, or you said in the PR that you could not.
- [ ] `en.json` is complete if you changed the flow or entity names.
- [ ] `docs/` and the root docs are updated if behavior changed.
