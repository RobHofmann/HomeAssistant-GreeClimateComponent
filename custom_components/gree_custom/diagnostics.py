"""Provide diagnostics support for entries and devices."""

import logging
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import CONF_DEVICES, CONF_ENCRYPTION_KEY, DOMAIN
from .coordinator import GreeConfigEntry, GreeCoordinator
from .helpers import get_vrf_controller_mac, get_vrf_sub_units

_LOGGER = logging.getLogger(__name__)


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: GreeConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    _LOGGER.debug("Getting entry diagnostics")

    coordinators: dict[str, GreeCoordinator] = entry.runtime_data

    data: dict[str, Any] = {}
    for i, c in coordinators.items():
        data[i] = c.get_coordinator_diagnostics()

    diagnostics = {"entry_data": dict(entry.data.copy()), "data": data}
    # redacted = diagnostics
    # redacted["entry_data"]["advanced"] = diagnostics["entry_data"]["advanced"].copy()
    # redacted["entry_data"]["advanced"]["encryption_key"] = redact_str(
    #     diagnostics["entry_data"]["advanced"]["encryption_key"]
    # )

    return async_redact_data(diagnostics, [CONF_ENCRYPTION_KEY, CONF_PASSWORD])


async def async_get_device_diagnostics(
    hass: HomeAssistant, entry: GreeConfigEntry, device: DeviceEntry
) -> dict[str, Any]:
    """Return diagnostics for a device."""
    _LOGGER.debug("Getting device diagnostics")

    # A VRF controller has no data of its own, return its sub-units
    controller_mac = get_vrf_controller_mac(device)
    if controller_mac is not None:
        sub_units = get_vrf_sub_units(entry.data.get(CONF_DEVICES, {}))
        sub_unit_data: dict[str, Any] = {}
        for sub_mac in sorted(sub_units.get(controller_mac, set())):
            sub_coordinator: GreeCoordinator | None = entry.runtime_data.get(sub_mac)
            sub_unit_data[sub_mac] = (
                sub_coordinator.get_coordinator_diagnostics() if sub_coordinator else ""
            )

        return {
            "device": device.dict_repr,
            "controller_mac": controller_mac,
            "sub_units": sub_unit_data,
        }

    # Find MAC address for this device (from identifiers)
    identifiers = device.identifiers
    mac: str | None = None
    for domain, identifier in identifiers:
        if domain == DOMAIN:
            mac = identifier
            break

    if not mac:
        raise RuntimeError(f"No MAC found for the device: {device.identifiers}")

    coordinator: GreeCoordinator | None = entry.runtime_data.get(mac, None)

    return {
        "device": device.dict_repr,
        "data": coordinator.get_coordinator_diagnostics() if coordinator else "",
    }
