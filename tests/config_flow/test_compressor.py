"""Compressor telemetry and the HVAC action, inside a real Home Assistant.

A unit that reports the compressor columns gets four sensors and a binary
sensor, all disabled by default. A unit that does not report them gets none.
The climate entity shows what the unit does: with compressor data it tells
idle from cooling, without it the action follows the HVAC mode. The outdoor
temperature sensor is disabled for a new device, and keeps its state for a
device that already had it.
"""

import pytest

from custom_components.gree_custom.aiogree.api import GreeProp
from custom_components.gree_custom.climate import gree_hvac_action
from custom_components.gree_custom.const import DOMAIN
from homeassistant.components.climate import HVACAction, HVACMode  # pyright: ignore[reportPrivateImportUsage]
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from tests.config_flow.conftest import MAC_A, GreeEnv, add_entry

COMPRESSOR_KEYS = {
    "sensor": [
        "compressor_frequency",
        "compressor_temperature",
        "indoor_coil_temperature",
        "outdoor_coil_temperature",
    ],
    "binary_sensor": ["compressor_running"],
}

# Cool mode, compressor running. The temperatures carry the offset of 40.
COMPRESSOR_VALUES = {
    GreeProp.OP_MODE.value: 1,
    GreeProp.SENSOR_OUTSIDE_TEMPERATURE_1.value: 52,
    GreeProp.SENSOR_COMPRESSOR_FREQUENCY.value: 58,
    GreeProp.SENSOR_COMPRESSOR_TEMPERATURE.value: 115,
    GreeProp.SENSOR_INDOOR_COIL_TEMPERATURE.value: 48,
    GreeProp.SENSOR_OUTDOOR_COIL_TEMPERATURE.value: 85,
}


def registry_row(hass: HomeAssistant, platform: str, key: str) -> er.RegistryEntry:
    """Return the registry row of one entity of unit A."""
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(platform, DOMAIN, f"{MAC_A}_{key}")
    assert entity_id is not None, key
    row = registry.async_get(entity_id)
    assert row is not None
    return row


def hvac_action(hass: HomeAssistant) -> str | None:
    """Return the hvac_action attribute of the climate entity of unit A."""
    state = hass.states.get(registry_row(hass, "climate", "hvac").entity_id)
    assert state is not None
    return state.attributes.get("hvac_action")


async def test_a_unit_with_compressor_data_gets_disabled_sensors(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """Every compressor entity exists, and none is enabled until the user asks."""
    unit = gree.devices[MAC_A]
    unit.values.update(COMPRESSOR_VALUES)
    host = await gree.start_udp(unit)
    await add_entry(hass, ["local"], [MAC_A], [host])

    for platform, keys in COMPRESSOR_KEYS.items():
        for key in keys:
            row = registry_row(hass, platform, key)
            assert row.disabled_by is er.RegistryEntryDisabler.INTEGRATION, key
            assert row.entity_category is None, key

    outdoor = registry_row(hass, "sensor", "outdoor_temperature")
    assert outdoor.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert registry_row(hass, "sensor", "indoor_temperature").disabled_by is None

    assert hvac_action(hass) == HVACAction.COOLING


async def test_a_stopped_compressor_shows_idle(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """The unit is on in Cool, but its compressor rests."""
    unit = gree.devices[MAC_A]
    unit.values.update(COMPRESSOR_VALUES)
    unit.values[GreeProp.SENSOR_COMPRESSOR_FREQUENCY.value] = 0
    host = await gree.start_udp(unit)
    await add_entry(hass, ["local"], [MAC_A], [host])

    assert registry_row(hass, "binary_sensor", "compressor_running")
    assert hvac_action(hass) == HVACAction.IDLE


async def test_a_unit_without_compressor_data_gets_no_compressor_entities(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """The dev unit leaves the columns out. The action follows the mode."""
    unit = gree.devices[MAC_A]
    unit.values[GreeProp.OP_MODE.value] = 1
    unit.unsupported_props = {
        GreeProp.SENSOR_COMPRESSOR_FREQUENCY.value,
        GreeProp.SENSOR_COMPRESSOR_TEMPERATURE.value,
        GreeProp.SENSOR_INDOOR_COIL_TEMPERATURE.value,
        GreeProp.SENSOR_OUTDOOR_COIL_TEMPERATURE.value,
    }
    host = await gree.start_udp(unit)
    await add_entry(hass, ["local"], [MAC_A], [host])

    registry = er.async_get(hass)
    for platform, keys in COMPRESSOR_KEYS.items():
        for key in keys:
            assert (
                registry.async_get_entity_id(platform, DOMAIN, f"{MAC_A}_{key}") is None
            ), key

    assert hvac_action(hass) == HVACAction.COOLING


async def test_an_existing_outdoor_sensor_stays_enabled(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """Only a new device gets the outdoor sensor disabled."""
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "sensor", DOMAIN, f"{MAC_A}_outdoor_temperature", suggested_object_id="buiten"
    )

    unit = gree.devices[MAC_A]
    unit.values[GreeProp.SENSOR_OUTSIDE_TEMPERATURE_1.value] = 52
    host = await gree.start_udp(unit)
    await add_entry(hass, ["local"], [MAC_A], [host])

    row = registry_row(hass, "sensor", "outdoor_temperature")
    assert row.disabled_by is None
    assert hass.states.get(row.entity_id) is not None


@pytest.mark.parametrize(
    ("mode", "running", "action"),
    [
        (HVACMode.OFF, None, HVACAction.OFF),
        (HVACMode.OFF, True, HVACAction.OFF),
        (HVACMode.COOL, None, HVACAction.COOLING),
        (HVACMode.COOL, True, HVACAction.COOLING),
        (HVACMode.COOL, False, HVACAction.IDLE),
        (HVACMode.HEAT, None, HVACAction.HEATING),
        (HVACMode.HEAT, True, HVACAction.HEATING),
        (HVACMode.HEAT, False, HVACAction.IDLE),
        (HVACMode.DRY, None, HVACAction.DRYING),
        (HVACMode.DRY, True, HVACAction.DRYING),
        (HVACMode.DRY, False, HVACAction.IDLE),
        (HVACMode.FAN_ONLY, None, HVACAction.FAN),
        (HVACMode.FAN_ONLY, False, HVACAction.FAN),
        (HVACMode.AUTO, None, None),
        (HVACMode.AUTO, True, None),
        (HVACMode.AUTO, False, HVACAction.IDLE),
    ],
)
def test_hvac_action(
    mode: HVACMode, running: bool | None, action: HVACAction | None
) -> None:
    """Without compressor data the mode decides, with it idle is told apart."""
    assert gree_hvac_action(mode, running) == action
