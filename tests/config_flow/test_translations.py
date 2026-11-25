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

from custom_components.gree_custom import binary_sensor, sensor
from custom_components.gree_custom.aiogree.api import AuxiliaryHeatMode

COMPONENT = Path(__file__).parents[2] / "custom_components" / "gree_custom"
LANGUAGES = tuple(
    sorted(path.stem for path in (COMPONENT / "translations").glob("*.json"))
)
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
# The entity names of the sensor platforms, per platform.
ENTITY_NAMES = {
    "sensor": {d.translation_key for d in sensor.SENSOR_TYPES},
    "binary_sensor": {d.translation_key for d in binary_sensor.SENSOR_TYPES},
}


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


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_auxiliary_heat_select_has_a_text_for_every_mode(language: str) -> None:
    """The feature picker and every option of the select have a text."""
    texts = translations(language)

    assert "auxiliary_heat" in texts["selector"]["features"]["options"]
    select = texts["entity"]["select"]["auxiliary_heat"]
    assert select["name"]
    assert sorted(select["state"]) == sorted(m.name for m in AuxiliaryHeatMode)


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_uv_lamp_switch_has_a_text(language: str) -> None:
    """The feature picker and the switch both have a text."""
    texts = translations(language)

    assert texts["selector"]["features"]["options"]["uv_lamp"]
    assert texts["entity"]["switch"]["uv_lamp"]["name"]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("platform", sorted(ENTITY_NAMES))
def test_every_sensor_name_has_a_text(language: str, platform: str) -> None:
    """The name of each sensor and binary sensor, such as Compressor Running."""
    names = translations(language)["entity"][platform]

    assert sorted(ENTITY_NAMES[platform] - set(names)) == []
    assert all("name" in names[key] for key in ENTITY_NAMES[platform])


def flat_texts(texts: dict, prefix: str = "") -> dict[str, str]:
    """Return every text in a translation file by its path, such as a/b/c."""
    flat = {}
    for key, value in texts.items():
        if isinstance(value, dict):
            flat |= flat_texts(value, f"{prefix}{key}/")
        else:
            flat[f"{prefix}{key}"] = value
    return flat


def key_paths(texts: dict) -> set[str]:
    """Return the path of every text in a translation file."""
    return set(flat_texts(texts))


@pytest.mark.parametrize("language", [lang for lang in LANGUAGES if lang != "en"])
def test_every_language_has_the_keys_of_english(language: str) -> None:
    """A key that is only in en.json shows in English to a user of this language.

    A key that is only in this language is a text that nothing uses any more.
    """
    english = key_paths(translations("en"))
    other = key_paths(translations(language))

    assert sorted(english - other) == []
    assert sorted(other - english) == []


def test_the_languages_are_found() -> None:
    """The language list comes from the files, so it must not be empty."""
    assert {"en", "nl", "pt", "de", "zh-Hans"} <= set(LANGUAGES)


@pytest.mark.parametrize("language", [lang for lang in LANGUAGES if lang != "en"])
def test_every_text_keeps_the_placeholders_of_english(language: str) -> None:
    """A placeholder such as {mac} that a translation drops or renames breaks the text."""
    english = flat_texts(translations("en"))
    other = flat_texts(translations(language))

    wrong = sorted(
        path
        for path, text in other.items()
        if path in english
        and sorted(re.findall(r"{(\w+)}", text))
        != sorted(re.findall(r"{(\w+)}", english[path]))
    )
    assert wrong == []
