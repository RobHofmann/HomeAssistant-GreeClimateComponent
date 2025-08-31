"""Support for Gree switches."""

from __future__ import annotations

# Standard library imports
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Home Assistant imports
from homeassistant.components.climate import HVACMode
from homeassistant.components.switch import (
    SwitchEntity,
    SwitchEntityDescription,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

# Local imports
from .entity import GreeEntity, GreeEntityDescription

_LOGGER = logging.getLogger(__name__)


@dataclass
class GreeSwitchEntityDescription(GreeEntityDescription, SwitchEntityDescription):
    """Describes Gree Switch entity."""

    set_fn: Callable[[object, bool], None] = None
    restore_state: bool = False
    """Whether to restore the state of the switch on startup."""


SWITCHES: tuple[GreeSwitchEntityDescription, ...] = (
    GreeSwitchEntityDescription(
        property_key="xfan",
        icon="mdi:fan",
        value_fn=lambda device: device._acOptions.get("Blo") == 1,
        set_fn=lambda device, value: device.SyncState({"Blo": 1 if value else 0}),
    ),
    GreeSwitchEntityDescription(
        property_key="lights",
        icon="mdi:lightbulb",
        value_fn=lambda device: device._acOptions.get("Lig") == 1,
        set_fn=lambda device, value: device.SyncState({"Lig": 1 if value else 0}),
    ),
    GreeSwitchEntityDescription(
        property_key="health",
        icon="mdi:shield-check",
        value_fn=lambda device: device._acOptions.get("Health") == 1,
        set_fn=lambda device, value: device.SyncState({"Health": 1 if value else 0}),
    ),
    GreeSwitchEntityDescription(
        property_key="powersave",
        icon="mdi:leaf",
        value_fn=lambda device: device._acOptions.get("SvSt") == 1,
        set_fn=lambda device, value: device.SyncState({"SvSt": 1 if value else 0}),
        exists_fn=lambda description, device: HVACMode.COOL in device._hvac_modes,
        available_fn=lambda device: device._hvac_mode == HVACMode.COOL,
    ),
    GreeSwitchEntityDescription(
        property_key="eightdegheat",
        icon="mdi:thermometer-low",
        value_fn=lambda device: device._acOptions.get("StHt") == 1,
        set_fn=lambda device, value: device.SyncState({"StHt": 1 if value else 0}),
        exists_fn=lambda description, device: HVACMode.HEAT in device._hvac_modes,
        available_fn=lambda device: device._hvac_mode == HVACMode.HEAT,
    ),
    GreeSwitchEntityDescription(
        property_key="sleep",
        icon="mdi:sleep",
        value_fn=lambda device: device._acOptions.get("SwhSlp") == 1 and device._acOptions.get("SlpMod") == 1,
        set_fn=lambda device, value: device.SyncState({"SwhSlp": 1 if value else 0, "SlpMod": 1 if value else 0}),
        available_fn=lambda device: device._hvac_mode in (HVACMode.COOL, HVACMode.HEAT),
    ),
    GreeSwitchEntityDescription(
        property_key="air",
        icon="mdi:air-filter",
        value_fn=lambda device: device._acOptions.get("Air") == 1,
        set_fn=lambda device, value: device.SyncState({"Air": 1 if value else 0}),
    ),
    GreeSwitchEntityDescription(
        property_key="anti_direct_blow",
        icon="mdi:weather-windy",
        value_fn=lambda device: device._acOptions.get("AntiDirectBlow") == 1,
        set_fn=lambda device, value: device.SyncState({"AntiDirectBlow": 1 if value else 0}),
        available_fn=lambda device: getattr(device, "_has_anti_direct_blow", False),
    ),
    GreeSwitchEntityDescription(
        property_key="light_sensor",
        icon="mdi:lightbulb-on",
        value_fn=lambda device: device._acOptions.get("LigSen") == 0,  # LigSen=0 means sensor is active
        set_fn=lambda device, value: device.SyncState({"Lig": 1, "LigSen": 0} if value else {"LigSen": 1}),
        available_fn=lambda device: getattr(device, "_has_light_sensor", False),
    ),
    # These entities are not kept in the climate device
    GreeSwitchEntityDescription(
        property_key="auto_xfan",
        icon="mdi:fan-auto",
        value_fn=lambda device: getattr(device, "_auto_xfan", False),
        set_fn=lambda device, value: setattr(device, "_auto_xfan", value),
        restore_state=True,
        entity_category=EntityCategory.CONFIG,
    ),
    GreeSwitchEntityDescription(
        property_key="auto_light",
        icon="mdi:lightbulb-auto",
        value_fn=lambda device: getattr(device, "_auto_light", False),
        set_fn=lambda device, value: setattr(device, "_auto_light", value),
        restore_state=True,
        entity_category=EntityCategory.CONFIG,
    ),
    GreeSwitchEntityDescription(
        property_key="beeper",
        icon="mdi:volume-high",
        value_fn=lambda device: getattr(device, "_beeper_enabled", True),
        set_fn=lambda device, value: setattr(device, "_beeper_enabled", value),
        restore_state=True,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Gree switch based on a config entry."""
    async_add_entities(GreeSwitchEntity(hass, entry, description) for description in SWITCHES)


class GreeSwitchEntity(GreeEntity, SwitchEntity, RestoreEntity):
    """Defines a Gree Switch entity."""

    entity_description: GreeSwitchEntityDescription

    def __init__(
        self,
        hass,
        entry,
        description: GreeSwitchEntityDescription,
    ) -> None:
        super().__init__(hass, entry, description)
        self._attr_is_on = bool(self.native_value)
        self._restored = False

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        # Restore state if applicable
        if self.entity_description.restore_state:
            last_state = await self.async_get_last_state()
            if last_state is not None:
                value = last_state.state == "on"
                setattr(self._device, f"_{self.entity_description.property_key}", value)
                self._attr_is_on = value
                self._restored = True

    @property
    def native_value(self):
        if self.entity_description.restore_state:
            return getattr(self, "_attr_is_on", False)
        return super().native_value

    @property
    def is_on(self) -> bool:
        return bool(self.native_value)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the switch."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        if self.entity_description.set_fn:
            await self.hass.async_add_executor_job(self.entity_description.set_fn, self._device, True)
        if self.entity_description.restore_state:
            self._attr_is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the switch."""
        if not self.available:
            raise HomeAssistantError("Entity unavailable")

        if self.entity_description.set_fn:
            await self.hass.async_add_executor_job(self.entity_description.set_fn, self._device, False)
        if self.entity_description.restore_state:
            self._attr_is_on = False
        self.async_write_ha_state()
