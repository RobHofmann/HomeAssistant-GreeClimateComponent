"""Support for Gree select entities (e.g., external temperature sensor selection)."""

from __future__ import annotations

# Standard library imports
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from inspect import isawaitable

# Home Assistant imports
from homeassistant.components.climate import HVACMode
from homeassistant.components.select import (
    SelectEntity,
    SelectEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

# Local imports
from .const import AUX_HEAT_MODES
from .entity import GreeEntity, GreeEntityDescription

_LOGGER = logging.getLogger(__name__)


@dataclass
class GreeSelectEntityDescription(GreeEntityDescription, SelectEntityDescription):
    """Describes Gree select entity."""

    set_fn: Callable[[object, str], Awaitable[None] | None] = None
    restore_state: bool = False
    options_fn: Callable[[object], list[str]] = None


def get_temperature_sensor_options(hass: HomeAssistant) -> list[str]:
    """Get list of available temperature sensor entities."""
    options = ["None"]  # Always include "None" as first option

    # Get all entities from the registry
    for state in hass.states.async_all():
        # Look for temperature sensors
        if state.entity_id.startswith("sensor."):
            # Check for explicit device_class
            if state.attributes.get("device_class") == "temperature":
                options.append(state.entity_id)
            # Also check for temperature units as fallback for helpers/combined sensors
            elif state.attributes.get("unit_of_measurement") in ["°C", "°F", "K"]:
                options.append(state.entity_id)

    return options


async def _set_auxiliary_heat(device, option: str) -> None:
    """Set the device's auxiliary electric heating mode."""
    await device.SyncState({"AssHt": AUX_HEAT_MODES[option]})


def _get_auxiliary_heat(device) -> str | None:
    """Return the mode reported by the device, or unknown if unsupported."""
    value = device._acOptions.get("AssHt")
    return next((mode for mode, code in AUX_HEAT_MODES.items() if value == code), None)


SELECTS: tuple[GreeSelectEntityDescription, ...] = (
    GreeSelectEntityDescription(
        property_key="auxiliary_heat",
        icon="mdi:heating-coil",
        options=list(AUX_HEAT_MODES),
        value_fn=_get_auxiliary_heat,
        set_fn=_set_auxiliary_heat,
        available_fn=lambda device: bool(device.available)
        and device._hvac_mode == HVACMode.HEAT
        and _get_auxiliary_heat(device) is not None,
    ),
    GreeSelectEntityDescription(
        property_key="external_temperature_sensor",
        icon="mdi:thermometer-lines",
        options=[],  # Will be populated dynamically
        value_fn=lambda device: getattr(device, "_external_temperature_sensor", None) or "None",
        set_fn=lambda device, value: setattr(device, "_external_temperature_sensor", None if value == "None" else value),
        entity_category=EntityCategory.CONFIG,
        restore_state=True,
        options_fn=lambda hass: get_temperature_sensor_options(hass),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gree select entities based on a config entry."""
    async_add_entities(GreeSelectEntity(hass, entry, description) for description in SELECTS)


class GreeSelectEntity(GreeEntity, SelectEntity, RestoreEntity):
    """Defines a Gree select entity."""

    entity_description: GreeSelectEntityDescription

    def __init__(self, hass: HomeAssistant, entry, description: GreeSelectEntityDescription) -> None:
        super().__init__(hass, entry, description)
        self._hass = hass
        # Initialize with no external sensor configured
        if description.property_key == "external_temperature_sensor":
            self._device._external_temperature_sensor = None
        # Set up options dynamically
        if description.options_fn:
            self._attr_options = description.options_fn(hass)
        else:
            self._attr_options = description.options or ["None"]

    async def async_added_to_hass(self) -> None:
        """Restore state when entity is added to hass."""
        await super().async_added_to_hass()

        # Refresh options when entity is added
        if self.entity_description.options_fn:
            self._attr_options = self.entity_description.options_fn(self._hass)

        # Restore the last selected state if available
        if self.entity_description.restore_state:
            restored = await self.async_get_last_state()
            if restored and self.entity_description.set_fn:
                await self._async_set_option(restored.state)
                _LOGGER.debug("Restored %s state: %s", self.entity_id, restored.state)

    @property
    def current_option(self) -> str | None:
        """Return the current selected option."""
        if self.entity_description.value_fn:
            return self.entity_description.value_fn(self._device)
        return None

    async def _async_set_option(self, option: str) -> None:
        """Handle both device commands and local configuration setters."""
        result = self.entity_description.set_fn(self._device, option)
        if isawaitable(result):
            await result

    async def async_select_option(self, option: str) -> None:
        """Select an option."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        if option not in self._attr_options:
            _LOGGER.error("Option %s not available in %s", option, self._attr_options)
            return

        if self.entity_description.set_fn:
            await self._async_set_option(option)
            self.async_write_ha_state()
            _LOGGER.info("Selected %s: %s", self.entity_description.property_key, option)

    async def async_update(self) -> None:
        """Update the entity."""
        # Refresh available temperature sensors periodically
        if self.entity_description.options_fn:
            new_options = self.entity_description.options_fn(self._hass)
            if new_options != self._attr_options:
                self._attr_options = new_options
                _LOGGER.debug("Updated temperature sensor options: %s", self._attr_options)

    @property
    def available(self) -> bool:
        """Return if entity is available."""
        return super().available
