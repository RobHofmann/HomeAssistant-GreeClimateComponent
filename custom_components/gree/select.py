"""Support for Gree select entities (e.g., external temperature sensor selection)."""

from collections.abc import Callable
import logging
from typing import Generic, TypeVar

from attr import dataclass

from config.custom_components.gree.gree_device import GreeDevice
from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.typing import UNDEFINED

from .const import GATTR_TEMP_UNITS
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription
from .gree_api import TemperatureUnits

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")  # T can be any type


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches from a config entry."""

    coordinator = entry.runtime_data
    descriptions: list[GreeSelectDescription] = []

    descriptions.append(
        GreeSelectDescription[GreeDevice](
            key=GATTR_TEMP_UNITS,
            translation_key=GATTR_TEMP_UNITS,
            entity_category=EntityCategory.CONFIG,
            options=[member.name for member in TemperatureUnits],
            available_func=lambda device: device.available,
            value_func=lambda device: device.target_temperature_unit.name,
            set_func=lambda device, value: device.set_target_temperature_unit(
                TemperatureUnits[value]
            ),
            updates_device=True,
        )
    )

    _LOGGER.debug("Adding Select Entities: %s", [desc.key for desc in descriptions])

    async_add_entities(
        [GreeSelectEntity(description, coordinator) for description in descriptions]
    )


@dataclass(frozen=True, kw_only=True)
class GreeSelectDescription(GreeEntityDescription, SelectEntityDescription, Generic[T]):
    """Description of a Gree switch."""

    device_class = None
    entity_category = None
    entity_registry_enabled_default = True
    entity_registry_visible_default = True
    force_update = False
    icon = None
    has_entity_name = True
    name = UNDEFINED
    translation_key = None
    translation_placeholders = None
    unit_of_measurement = None
    options_func: Callable[[], list[str]] | None = None
    value_func: Callable[[T], str | None]
    set_func: Callable[[T, str], None]
    updates_device: bool = True


class GreeSelectEntity(GreeEntity, SelectEntity, RestoreEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    """A Gree select entity."""

    entity_description: GreeSelectDescription

    def __init__(
        self,
        description: GreeSelectDescription,
        coordinator: GreeCoordinator,
        restore_state: bool = True,
    ) -> None:
        """Initialize select."""
        super().__init__(coordinator, restore_state)

        self.entity_description = description  # pyright: ignore[reportIncompatibleVariableOverride]
        self._attr_unique_id = f"{self._device.name}_{description.key}"

        # Set up options dynamically
        if description.options_func:
            self._attr_options = description.options_func()
        else:
            self._attr_options = description.options or ["None"]

        self._attr_current_option = self.entity_description.value_func(self._device)
        _LOGGER.debug("Initialized select %s", self._attr_unique_id)
        _LOGGER.debug("Options: %s", self._attr_options)

    def _handle_coordinator_update(self) -> None:
        """Handle updated data from the coordinator."""
        _LOGGER.debug("Updating Select Entity for %s", self._device.unique_id)
        self._attr_current_option = self.entity_description.value_func(self._device)

    @property
    def current_option(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the selected entity option to represent the entity state."""
        return self.entity_description.value_func(self._device)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug(
            "async_select_option(%s, %s, %s -> %s)",
            self._device.unique_id,
            self.entity_description.key,
            self.current_option,
            option,
        )

        try:
            self.entity_description.set_func(self._device, option)

            if self.entity_description.updates_device:
                await self._device.update_device_status()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.debug(
                "Error in async_select_option(%s, %s, %s -> %s)",
                self._device.unique_id,
                self.entity_description.key,
                self.current_option,
                option,
            )
            raise HomeAssistantError(
                "Failed to select a different temperature unit."
            ) from err

        self.async_write_ha_state()

    async def async_added_to_hass(self):
        """Handle entity which will be added."""
        await super().async_added_to_hass()

        # Restore last HA state to device if applicable
        if self.restore_state:
            last_state = await self.async_get_last_state()
            if last_state is not None:
                _LOGGER.debug(
                    "Restoring state for %s: %s", self.entity_id, last_state.state
                )
                if last_state.state not in ("unknown", "unavailable"):
                    try:
                        self.entity_description.set_func(self._device, last_state.state)

                        if self.entity_description.updates_device:
                            await self._device.update_device_status()

                        self._attr_current_option = last_state.state
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.error(
                            "Failed to restore state for %s: %s",
                            self.entity_id,
                            repr(err),
                        )
