---
name: run-tests
description: Run the full local check for this repository: the pytest suite, Ruff, Pylint and Mypy, on Python 3.14. Use before opening or updating a pull request, after any change under custom_components/gree_custom/, or when asked to run the tests, the checks or the linters.
---

# Run the checks

This repository needs **Python 3.14**. The code uses PEP 758 syntax
(`except A, B:` without brackets), which older interpreters report as a syntax
error. Do not "fix" that. If a check reports it, the interpreter is too old.

Run every step below and report the result of each one. Do not stop at the
first failure unless the failure blocks the rest.

## 1. Pick an environment

In order of preference.

**A. The devcontainer.** `.devcontainer/postCreate.sh` builds a `.venv` and
clones Home Assistant core into `.ha-core`. This is the only environment where
all four checks can run, because Pylint and Mypy need plugins from that
checkout. Inside it:

```bash
source .venv/bin/activate
```

**B. A plain Python 3.14.** Enough for pytest and Ruff:

```bash
python3.14 -m venv .venv && source .venv/bin/activate
pip install -r requirements_dev.txt
```

**C. A container**, when there is no local 3.14:

```bash
docker run --rm -v "$PWD:/src" -w /src python:3.14-slim sh -c \
  "python -m venv /venv && /venv/bin/pip install -q -r requirements_dev.txt && /venv/bin/pytest -q"
```

The tests bind addresses out of `127.0.0.0/8`, so discovery tests need Linux.
On Windows and macOS only `127.0.0.1` exists by default and those tests skip
themselves with a message that says so.

## 2. The test suite

```bash
pytest -q
```

About 30 seconds. Expect every test to pass; there are no expected failures in
the suite.

Useful while working:

```bash
pytest -q tests/test_device.py          # one file
pytest -q -k humidity                   # one subject
pytest -q --durations=10                # find the slow ones
pytest -q -n auto                       # parallel, needs pytest-xdist
```

Coverage, which needs `pytest-cov`:

```bash
pytest -q --cov=aiogree --cov-report=term-missing
```

The protocol layer sits around 94 percent. A drop means a new branch has no
test.

## 3. Ruff

Run it from the repo root so `.ruff.toml` applies.

```bash
ruff check .
ruff format --check .
```

`ruff check --fix` and `ruff format` fix most of it. Do not reformat files your
change did not touch.

## 4. Pylint and Mypy

These need the Home Assistant core checkout in `.ha-core`, so they only run in
the devcontainer. Say so in your report if you could not run them.

```bash
pylint --rcfile=.pylintrc custom_components tests
mypy --config-file mypy.ini custom_components tests
```

A Pylint warning you cannot avoid gets a `# pylint: disable=<name>` comment
with one line saying why, which is what Home Assistant's own guidelines ask
for. Do not widen the shared config.

## 5. What the suite does not cover

The suite covers the protocol layer, `custom_components/gree_custom/aiogree/`.
It does not cover the Home Assistant layer: the entities, the coordinator and
the config flow.

Those need
[pytest-homeassistant-custom-component](https://github.com/MatthewFlamm/pytest-homeassistant-custom-component),
which extracts Home Assistant's own test plugins for custom integrations. It
needs the `enable_custom_integrations` fixture and `asyncio_mode = auto`, which
`pytest.ini` already sets. It is not a dependency of this repository yet,
because it pulls in all of Home Assistant and CI does not need it for the
protocol tests.

So a green run does not mean a change is safe. For anything that touches an
entity, a service or the config flow, also run Home Assistant itself against a
device or a fake one, and say in the pull request which one you did.

## 6. Report

Give one line per check: the command, pass or fail, and the numbers. For a
failure, give the shortest output that identifies it. Do not paste the whole
log.

More detail is in [docs/development.md](../../../docs/development.md#testing):
what the suite covers, how the fake devices work, and how to add a new device
personality.
