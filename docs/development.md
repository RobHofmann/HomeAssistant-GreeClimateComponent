# Development

## Versions

- Python **3.14**. `.ruff.toml`, `mypy.ini` and `.pylintrc` all target 3.14.
- Home Assistant 2026.3 or newer. HA 2026.3 was the first release that requires Python 3.14. `hacs.json` states this floor for HACS installs. Keep it in line with the Python version the code needs; HA 2026.1 and 2026.2 still run Python 3.13.
- Python 3.14 syntax is used on purpose. Example: `except GreeConnectionError, GreeProtocolError:` without brackets is valid since PEP 758. Do not "fix" it.
- Check compile, lint and imports with a Python 3.14 interpreter. A local 3.13 gives false errors on the syntax above.

## Environment

Use the devcontainer. `CONTRIBUTING.md` has the steps. Inside it, the VS Code tasks do the work:

- `Run Home Assistant`: starts HA with this component. Restart it after every code change.
- `Ruff: check`, `Ruff: format`, `Pylint`, `Mypy`: run all of them before a PR. The configs match HA core.
- `HA: Check config`, `HA: Compile translations`.

## Testing

There is no unit test suite. Testing means running Home Assistant against a device. If you do not have a device, say so in the PR.

A fake device that speaks the UDP protocol is the best way to test failure paths without touching real hardware. The pattern that works:

- A small UDP server on `127.0.0.1` that answers `scan`, `bind` and `status`, using the component's own `CipherV1` for encryption.
- Build a `GreeDevice` and a `GreeUdpTransport` pointed at it, call `bind_with_transport()`, then assert on `_state.raw`, `_state.polled_properties` and the requests the fake saw.
- Give the fake a personality: cap the columns it answers, return an empty result, ignore some props, or stop answering part way. Those are the real failure modes.

Things worth a test when you touch the protocol layer: both encryption versions, a device that returns fewer columns than asked, a device that returns nothing, a device with a column limit, and a device that never answers a specific prop.

## Tools

`tools/` holds small command line scripts that use the protocol layer directly. They run outside Home Assistant, from the repo root, with any Python 3.14 that has `asyncio_dgram` and `cryptography` (the devcontainer does).

- `probe_status_limit.py --host <ip>`: finds the status request limits of one unit. It binds the unit, then sends `Pow` repeated N times (growing column count) and 10 padded columns (growing byte size), each as exactly one packet, and prints where each run first fails. Use it before you file or answer a report about a unit that shows only default values, and paste the output in the issue. Details on why this matters are in [protocol.md](protocol.md#requests-and-batching).

## Debug logs

```yaml
logger:
  logs:
    custom_components.gree_custom: debug
```

Inside Home Assistant the logger name is `custom_components.gree_custom.*`. If you import `aiogree` directly in a script, the logger name is `gree_custom.aiogree.*` instead.

Debug level logs every pack in both directions, about 50 lines a minute per device. Keys are redacted, but do not leave it on in a normal install.

## Secrets in logs

Never log an encryption key, cloud password or token in clear text.

- Use `redact_str()` from `aiogree/helpers.py` for single values.
- Use `async_redact_data()` with `encryption_key` and `password` for dicts. `__init__.py`, `config_flow.py` and `diagnostics.py` already do this. Follow the same pattern.
- Do not add new `_LOGGER` lines that print packs before redaction.

## Translations

- `translations/` holds files that ship. Only edit these when you change the flow or an entity name, and keep `en.json` complete.
- `translation-to-review/` holds files that are not checked yet. Do not move a file out of it unless a native speaker reviewed it.

## Versions and releases

- The version lives in `manifest.json` and nowhere else.
- The maintainers own the version. Releases are cut with the workflows in `.github/workflows/`, which bump `manifest.json` and publish the release. Do not change the version in a normal PR unless a maintainer asks for it.
- Pre-release versions look like `5.0.0-alpha.107`. They are not tags or GitHub releases, so an exact pre-release cannot always be checked out again later.

## CI

`validate.yaml` runs hassfest and HACS validation on every push and PR. Neither imports or compiles the Python. Run ruff, pylint and mypy yourself before you push.
