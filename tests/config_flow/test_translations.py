"""Every key the integration shows to a user has a text in every language.

A config flow error, an abort reason, a form step, a menu option and an
exception with a translation key all reach the user through the files in
`translations/`. A key without a text shows up raw in the UI, such as
`cannot_connect_mqtt` in the connection form or `bad_credentials` on the
entry card. These tests read the keys from the source, so a new key without
a text fails here instead of in a user's UI.
"""

import json
from pathlib import Path
import re

import pytest

COMPONENT = Path(__file__).parents[2] / "custom_components" / "gree_custom"
LANGUAGES = ("en", "nl", "pt")
CONFIG_FLOW = (COMPONENT / "config_flow.py").read_text(encoding="utf-8")
ALL_SOURCE = "".join(
    path.read_text(encoding="utf-8") for path in sorted(COMPONENT.glob("*.py"))
)


def translations(language: str) -> dict:
    """Return the translation file of one language."""
    path = COMPONENT / "translations" / f"{language}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def keys(pattern: str, source: str) -> set[str]:
    """Return every key the pattern finds in the source."""
    return set(re.findall(pattern, source))


ERRORS = keys(r'errors\[[^\]]+\]\s*=\s*"([^"]+)"', CONFIG_FLOW)
# Home Assistant aborts with these reasons itself: the reauth default of
# async_update_reload_and_abort, and the unique ID helpers of the flow.
IMPLICIT_ABORTS = {
    "reauth_successful",
    "already_configured",
    "already_in_progress",
    "unique_id_mismatch",
}
ABORTS = keys(r'reason="([^"]+)"', CONFIG_FLOW) | IMPLICIT_ABORTS
STEPS = keys(r'step_id="([^"]+)"', CONFIG_FLOW)
MENU_OPTIONS = {
    option
    for block in re.findall(r"menu_options = \[([^\]]+)\]", CONFIG_FLOW)
    for option in re.findall(r'"([^"]+)"', block)
}
EXCEPTIONS = keys(r'translation_domain=DOMAIN,\s*translation_key="([^"]+)"', ALL_SOURCE)


def test_the_source_has_keys() -> None:
    """The patterns still find keys, so the tests below check something."""
    assert {"cannot_connect_mqtt", "cloud_bad_login"} <= ERRORS
    assert {"yaml_managed", "reconfigure_successful"} <= ABORTS
    assert {"reconfigure", "edit_device", "no_new_devices"} <= STEPS
    assert {"edit_device", "rediscover", "remove_devices", "finish"} <= MENU_OPTIONS
    assert {"bad_credentials", "no_account_info", "device_bind_failed"} <= EXCEPTIONS


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_config_flow_key_has_a_text(language: str) -> None:
    """Errors, abort reasons, steps and menu options of the config flow."""
    config = translations(language)["config"]

    assert sorted(ERRORS - set(config["error"])) == []
    assert sorted(ABORTS - set(config["abort"])) == []
    assert sorted(STEPS - set(config["step"])) == []
    menu = config["step"]["reconfigure"]["menu_options"]
    assert sorted(MENU_OPTIONS - set(menu)) == []


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_exception_key_has_a_text(language: str) -> None:
    """Exceptions raised with a translation key, such as reauth reasons."""
    exceptions = translations(language)["exceptions"]

    assert sorted(EXCEPTIONS - set(exceptions)) == []
