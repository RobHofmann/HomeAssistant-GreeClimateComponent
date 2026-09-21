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

`tests/` holds a pytest suite for the protocol layer. Run it from the repo root:

```bash
pip install -r requirements_dev.txt
pytest
```

It takes about 30 seconds. `pytest -n auto` needs `pytest-xdist` and cuts that
to about 12 seconds.

### What it covers

| File | Covers |
|---|---|
| `test_cipher.py` | V1 and V2, round trips, recorded vectors, the tag check, the JSON trim |
| `test_payloads.py` | The pack builders, `gree_extract_macs`, `redact_str`, `chunked` |
| `test_transport_udp.py` | Retries, backoff, the split of a command when batching is off |
| `test_discovery_local.py` | Scan, silence, several devices, the listen window, broken replies |
| `test_discovery_vrf.py` | A gateway with sub-devices, in both reply shapes |

64 tests today. `cipher.py` is fully covered, `api.py` and the transports are
mostly covered.

### What is not covered yet

The suite covers the wire. It does not yet cover the layers above it. Run
`pytest --cov=aiogree --cov-report=term` (needs `pytest-cov`) for the numbers of
the day. About half of the protocol layer is covered, and none of the Home
Assistant layer.

| Not covered | Why it is worth doing |
|---|---|
| `device.py`, `device_api_client.py`, `device_state.py` | The bind, the column probe, the pruning of unsupported props and the poll loop. These are where the real device behaviour bites. The fakes in `tests/fakes/` already speak everything they need, so this is the cheapest next step. |
| The temperature and humidity math in `helpers.py`, and `TempOffsetResolver` | Pure functions with clamping and rounding. Fast to test, no socket needed. |
| `transport_mqtt.py` and `cloud_api.py` | The cloud paths. They need an MQTT fake and an HTTP fake. |
| Entities, the coordinator, the config flow | Needs [pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component), which extracts Home Assistant's own test plugins for custom integrations. It needs the `enable_custom_integrations` fixture and `asyncio_mode = auto`, which this repo already sets. |

So a green suite does not mean a change is safe. It means the wire still works.
Say in the PR what else you tested.

### How the fakes work

The fakes bind a real UDP socket on loopback and answer real packets. Nothing
about the transport is replaced, so retries, timeouts, the stream reset and the
decrypt path all run as they do in the field. A mocked transport would test
none of that.

- `tests/fakes/device.py` has `FakeGreeDevice`. It answers `scan`, `bind`,
  `status` and `cmd`, and it records every request.
- `tests/fakes/vrf.py` has `FakeVrfGateway`. It adds `subCnt` to the scan reply
  and answers the sub-device list, at the top level or inside a pack.

A new failure mode is a new keyword on `FakeGreeDevice`, not a new class. The
ones that exist are `answer_scan`, `answer_bind`, `scan_delay`, `reply_delay`,
`max_columns`, `unsupported_props`, `ignore_first`, `drop_after`, `raw_reply`,
`reply_key` and `scan_info`. There is also `rotate_key()`, for a device that
hands out a new session key.

The fake encrypts with the component's own cipher. That is a trade-off: it
keeps the fake short and gives V2 for free, but a bug in the cipher could
cancel itself out. `test_cipher.py` uses recorded vectors for that reason.

Failure modes worth covering when you touch the protocol layer: both encryption
versions, a device that returns fewer columns than asked, a device that returns
nothing, a device with a column limit, a device that never answers a specific
prop, and a device that goes quiet part way.

### Things that cost time

- **Ports.** Discovery has no port argument, so it always uses 7000. Tests that
  go through discovery bind their own address out of `127.0.0.0/8` instead,
  which is why they need Linux. The transport tests use an ephemeral port on
  `127.0.0.1` and run anywhere.
- **The listen window.** `async_udp_broadcast_request` sleeps for the whole
  timeout. Discovery does not stop early when it has heard from everyone, so a
  test with a 5 second window takes 5 seconds. Keep windows short.
- **Retries.** A full failure costs a few seconds. Pass `max_retries=1` in a
  test that is not about retrying.
- **Log assertions.** The `gree_logs` fixture records log lines and any line
  that cannot be formatted. Standard logging swallows a formatting error, so a
  test that only reads the text of a log line would miss it. The fixture is
  autouse, so every test checks it.

### Tests and Home Assistant's own rules

Home Assistant's [testing guidelines](https://developers.home-assistant.io/docs/development_testing)
are written for core integrations. What applies here:

- pytest with `asyncio_mode = auto`, which is what core and the custom
  component plugin both use.
- A pylint warning you cannot avoid gets a `# pylint: disable=` comment with a
  reason, not a change to the shared config.
- Assert through the public interface. Here that is the protocol functions in
  `aiogree/api.py`, not the private state of a transport.
- Snapshot tests with syrupy are not used. The replies are small and a plain
  assert says more.

One rule does not carry over. Core moves the clock instead of sleeping. These
tests drive a real socket, so the packet has to really arrive and the sleeps
are real. That is the cost of testing the transport as it ships.

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

`validate.yaml` runs three jobs on every push and PR:

- **Hassfest** and **HACS** validation. Neither imports or compiles the Python.
- **Tests**: `pytest` on Python 3.14, on an Ubuntu runner. This one does import
  the protocol layer, so a syntax error or a broken import fails the build.

CI does not run ruff, pylint or mypy. Pylint and mypy need the Home Assistant
core checkout in `.ha-core`, which only the devcontainer has. Run all three
yourself before you push.
