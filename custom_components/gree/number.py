"""Support for Gree number entities (e.g., target temperature step)."""

from __future__ import annotations

# Standard library imports
import logging
from collections.abc import Callable
from dataclasses import dataclass

# Home Assistant imports
from homeassistant.components.number import (
    NumberEntity,
    NumberEntityDescription,
    NumberMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

# Local imports
from .const import DEFAULT_TARGET_TEMP_STEP
from .entity import GreeEntity, GreeEntityDescription

_LOGGER = logging.getLogger(__name__)


@dataclass
class GreeNumberEntityDescription(GreeEntityDescription, NumberEntityDescription):
    set_fn: Callable[[object, float], None] = None
    restore_state: bool = False


NUMBERS: tuple[GreeNumberEntityDescription, ...] = (
    GreeNumberEntityDescription(
        property_key="target_temp_step",
        icon="mdi:arrow-expand-vertical",
        native_min_value=0.1,
        native_max_value=5.0,
        native_step=0.1,
        mode=NumberMode.SLIDER,
        value_fn=lambda device: getattr(device, "_target_temperature_step", DEFAULT_TARGET_TEMP_STEP),
        set_fn=lambda device, value: setattr(device, "_target_temperature_step", value),
        entity_category=EntityCategory.CONFIG,
        restore_state=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gree number entities based on a config entry."""
    async_add_entities(GreeNumberEntity(hass, entry, description) for description in NUMBERS)


class GreeNumberEntity(GreeEntity, NumberEntity, RestoreEntity):
    """Defines a Gree number entity."""

    entity_description: GreeNumberEntityDescription

    def __init__(self, hass, entry, description: GreeNumberEntityDescription) -> None:
        super().__init__(hass, entry, description)
        self._attr_native_value = self.native_value
        self._restored = False

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if self.entity_description.restore_state:
            last_state = await self.async_get_last_state()
            if last_state is not None and last_state.state not in ["unknown", "unavailable"]:
                try:
                    value = float(last_state.state)
                    # Validate the value is within the entity's range
                    if self.entity_description.native_min_value <= value <= self.entity_description.native_max_value:
                        setattr(self._device, f"_{self.entity_description.property_key}", value)
                        self._attr_native_value = value
                        self._restored = True
                except (ValueError, TypeError):
                    # If conversion fails, use default value
                    pass

    @property
    def native_value(self):
        if self.entity_description.restore_state:
            return getattr(self, "_attr_native_value", self.entity_description.value_fn(self._device))
        return self.entity_description.value_fn(self._device)

    async def async_set_native_value(self, value: float) -> None:
        if self.entity_description.set_fn:
            await self.hass.async_add_executor_job(self.entity_description.set_fn, self._device, value)
        if self.entity_description.restore_state:
            self._attr_native_value = value
        self.async_write_ha_state()
