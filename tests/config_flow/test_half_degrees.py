"""Tests for the option "Use half-degrees °C" (issue 569) in Home Assistant.

The option replaced the temperature step. These tests cover the form, the
climate step that follows from it, and every way an old step reaches the new
option: an entry of minor version 1, a YAML block and a 4.x migration.
"""

from typing import Any

from pytest_homeassistant_custom_component.common import MockConfigEntry

import custom_components.gree_custom as gree_component
from custom_components.gree_custom.config_schema import CONFIG_SCHEMA
from custom_components.gree_custom.const import (
    CONF_DEVICE_CONNECTION,
    CONF_DEVICE_CONNECTION_LOCAL,
    CONF_DEVICE_OPTIONS,
    CONF_DEVICES,
    CONF_EXTRA_SCAN_HOSTS,
    CONF_HALF_DEGREES,
    CONF_TEMPERATURE_STEP,
    CURRENT_CONF_MINOR_VERSION,
    CURRENT_CONF_VERSION,
    DOMAIN,
)
from custom_components.gree_custom.migration import (
    _normalize_device,
    _restored_option,
    convert_legacy_device,
)
from homeassistant.config_entries import SOURCE_USER, ConfigEntryState
from homeassistant.const import CONF_DISCOVERY, CONF_HOST, CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from tests.config_flow.conftest import MAC_A, GreeEnv, form_input, submit

HALF_COLUMNS = {"TemRec", "StFahFlg", "Add0.5", "Add0.1"}


async def device_options_form(hass: HomeAssistant, gree: GreeEnv) -> dict[str, Any]:
    """Run the local user flow for unit A up to its device options form."""
    host = await gree.start_udp(gree.devices[MAC_A])
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_DISCOVERY: ["local"]}
    )
    result = await submit(hass, result, **{CONF_EXTRA_SCAN_HOSTS: [host]})
    result = await submit(hass, result, **{CONF_DEVICES: [MAC_A]})
    assert result["step_id"] == "connection_options"
    result = await submit(hass, result)
    assert result["step_id"] == "device_options"
    return result


def device_step(entry: Any) -> float:
    """Return the target temperature step of unit A of a loaded entry.

    The climate entity takes its step from here. The entity itself needs the
    native climate API of Home Assistant 2026.11, and the test pin is older.
    """
    return entry.runtime_data[MAC_A].device.target_temperature_step


async def test_the_option_sets_the_climate_step(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """The unit answers TemRec, so the form offers the option, off by default."""
    result = await device_options_form(hass, gree)

    assert form_input(result)[CONF_HALF_DEGREES] is False
    assert CONF_TEMPERATURE_STEP not in form_input(result)

    result = await submit(hass, result, **{CONF_HALF_DEGREES: True})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    await hass.async_block_till_done()

    entry = result["result"]
    assert entry.state is ConfigEntryState.LOADED
    assert entry.minor_version == CURRENT_CONF_MINOR_VERSION
    options = entry.data[CONF_DEVICES][MAC_A][CONF_DEVICE_OPTIONS]
    assert options[CONF_HALF_DEGREES] is True
    assert device_step(entry) == 0.5
    gree.assert_only_entry_connections()


async def test_a_unit_without_a_half_column_gets_no_option(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """No TemRec, StFahFlg, Add0.5 or Add0.1: whole degrees, nothing to choose."""
    gree.devices[MAC_A].unsupported_props = set(HALF_COLUMNS)

    result = await device_options_form(hass, gree)
    assert CONF_HALF_DEGREES not in form_input(result)

    result = await submit(hass, result)
    await hass.async_block_till_done()

    assert device_step(result["result"]) == 1.0
    gree.assert_only_entry_connections()


#
# An entry of minor version 1
#


def old_device(options: dict[str, Any]) -> dict[str, Any]:
    """One device of an entry, with these options."""
    return {
        CONF_DEVICE_CONNECTION: {CONF_DEVICE_CONNECTION_LOCAL: {CONF_HOST: "x"}},
        CONF_DEVICE_OPTIONS: {CONF_NAME: "Unit", **options},
    }


async def test_an_old_entry_gets_half_degrees_from_its_step(
    hass: HomeAssistant,
) -> None:
    """A step that is not whole means half degrees. The step itself goes."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=CURRENT_CONF_VERSION,
        minor_version=1,
        data={
            CONF_DEVICES: {
                "aa0000000001": old_device({CONF_TEMPERATURE_STEP: 0.5}),
                "aa0000000002": old_device({CONF_TEMPERATURE_STEP: 1}),
                "aa0000000003": old_device({CONF_TEMPERATURE_STEP: 2.0}),
                "aa0000000004": old_device({}),
            }
        },
    )
    entry.add_to_hass(hass)

    assert await gree_component.async_migrate_entry(hass, entry)

    assert entry.minor_version == CURRENT_CONF_MINOR_VERSION
    options = {
        mac: device[CONF_DEVICE_OPTIONS]
        for mac, device in entry.data[CONF_DEVICES].items()
    }
    assert options["aa0000000001"] == {CONF_NAME: "Unit", CONF_HALF_DEGREES: True}
    assert options["aa0000000002"] == {CONF_NAME: "Unit"}
    assert options["aa0000000003"] == {CONF_NAME: "Unit"}
    assert options["aa0000000004"] == {CONF_NAME: "Unit"}


async def test_an_entry_of_another_major_version_is_refused(
    hass: HomeAssistant,
) -> None:
    """Home Assistant refused these before there was a migration, and still does."""
    entry = MockConfigEntry(domain=DOMAIN, version=2, data={CONF_DEVICES: {}})
    entry.add_to_hass(hass)

    assert not await gree_component.async_migrate_entry(hass, entry)


#
# YAML
#


def yaml_options(**options: Any) -> dict[str, Any]:
    """Validate one YAML device with these options and return its options."""
    config = CONFIG_SCHEMA(
        {
            DOMAIN: [
                {
                    CONF_DEVICES: {
                        "aa0000000001": {
                            CONF_DEVICE_CONNECTION: {
                                CONF_DEVICE_CONNECTION_LOCAL: {CONF_HOST: "x"}
                            },
                            CONF_DEVICE_OPTIONS: {CONF_NAME: "Unit", **options},
                        }
                    }
                }
            ]
        }
    )
    return config[DOMAIN][0][CONF_DEVICES]["aa0000000001"][CONF_DEVICE_OPTIONS]


def test_yaml_takes_half_degrees() -> None:
    """The new key, as a user writes it."""
    assert yaml_options(**{CONF_HALF_DEGREES: True})[CONF_HALF_DEGREES] is True


def test_yaml_still_takes_the_old_step() -> None:
    """The import runs at every start, so an old key must not break the block."""
    options = yaml_options(**{CONF_TEMPERATURE_STEP: 0.5})
    assert options[CONF_HALF_DEGREES] is True
    assert CONF_TEMPERATURE_STEP not in options

    assert CONF_HALF_DEGREES not in yaml_options(**{CONF_TEMPERATURE_STEP: 1})


def test_yaml_half_degrees_wins_over_the_old_step() -> None:
    """When both are written, the new key is what the user meant."""
    options = yaml_options(**{CONF_TEMPERATURE_STEP: 0.5, CONF_HALF_DEGREES: False})
    assert options[CONF_HALF_DEGREES] is False


#
# Migration from 4.x
#


def test_a_4x_step_or_switch_turns_half_degrees_on() -> None:
    """The step number and the Add0.5 switch of 4.x both map to the new option."""
    assert _restored_option(CONF_TEMPERATURE_STEP, "0.5") == {CONF_HALF_DEGREES: True}
    assert _restored_option(CONF_TEMPERATURE_STEP, "1.0") == {}
    assert _restored_option(CONF_TEMPERATURE_STEP, "2.0") == {}
    assert _restored_option(CONF_HALF_DEGREES, "on") == {CONF_HALF_DEGREES: True}
    assert _restored_option(CONF_HALF_DEGREES, "off") == {}


def test_a_converted_4x_device_keeps_half_degrees() -> None:
    """The converted device passes the YAML schema with the option."""
    key, device = convert_legacy_device(
        {CONF_NAME: "Unit", CONF_MAC: "aa:00:00:00:00:01", CONF_HOST: "x"},
        {CONF_HALF_DEGREES: True},
    )
    normalized = _normalize_device(key, device)

    assert normalized is not None
    assert normalized[1][CONF_DEVICE_OPTIONS][CONF_HALF_DEGREES] is True
