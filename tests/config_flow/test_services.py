"""The get_prop_values services, inside a real Home Assistant.

A service call names a device. The service finds the config entry of that
device through DeviceEntry.config_entry_id, because DeviceEntry.config_entries
is deprecated and stops working in Home Assistant 2027.10.
"""

import logging

import pytest

from custom_components.gree_custom.const import ATTR_SVC_PROPS, DOMAIN
from custom_components.gree_custom.services import SVC_GET_PROPS, SVC_GET_PROPS_ALL
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import ATTR_DEVICE_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from tests.config_flow.conftest import MAC_A, GreeEnv, add_entry, registry_device


async def test_get_prop_values_reads_the_named_device(
    hass: HomeAssistant, gree: GreeEnv, caplog: pytest.LogCaptureFixture
) -> None:
    """Both services answer for a device of a loaded entry, without a deprecation."""
    host = await gree.start_udp(gree.devices[MAC_A])
    entry = await add_entry(hass, ["local"], [MAC_A], [host])
    device = registry_device(hass, entry, MAC_A)
    assert device is not None
    caplog.set_level(logging.WARNING)

    response = await hass.services.async_call(
        DOMAIN,
        SVC_GET_PROPS,
        {ATTR_DEVICE_ID: device.id, ATTR_SVC_PROPS: ["Pow"]},
        blocking=True,
        return_response=True,
    )
    assert response is not None
    assert "Pow" in response["states"]

    response = await hass.services.async_call(
        DOMAIN,
        SVC_GET_PROPS_ALL,
        {ATTR_DEVICE_ID: device.id},
        blocking=True,
        return_response=True,
    )
    assert response is not None
    assert "Pow" in response["states"]

    assert "config_entries" not in caplog.text


async def test_a_device_of_an_unloaded_entry_is_refused(
    hass: HomeAssistant, gree: GreeEnv
) -> None:
    """The entry is there, but not loaded, so the service cannot reach the unit."""
    host = await gree.start_udp(gree.devices[MAC_A])
    entry = await add_entry(hass, ["local"], [MAC_A], [host])
    device = registry_device(hass, entry, MAC_A)
    assert device is not None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.NOT_LOADED

    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN,
            SVC_GET_PROPS_ALL,
            {ATTR_DEVICE_ID: device.id},
            blocking=True,
            return_response=True,
        )
    assert error.value.translation_key == "entry_not_loaded"


async def test_an_unknown_device_is_refused(hass: HomeAssistant, gree: GreeEnv) -> None:
    """A device ID that is not in the registry gives a clear error."""
    host = await gree.start_udp(gree.devices[MAC_A])
    await add_entry(hass, ["local"], [MAC_A], [host])

    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN,
            SVC_GET_PROPS_ALL,
            {ATTR_DEVICE_ID: "not-a-device"},
            blocking=True,
            return_response=True,
        )
    assert error.value.translation_key == "invalid_device_id"
