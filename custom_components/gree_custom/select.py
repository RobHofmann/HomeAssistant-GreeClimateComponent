"""Support for Gree select entities (e.g., external temperature sensor selection)."""

from collections.abc import Callable
import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .aiogree.api import HumidityControlMode, OperationMode, TemperatureUnits
from .aiogree.device import GreeDevice
from .aiogree.errors import (
    GreeContinuousDryUnavailable,
    GreeHumidityControlUnavailable,
    GreeSmartDryUnavailable,
)
from .const import DOMAIN, GATTR_FEAT_HUMIDITY, GATTR_TEMP_UNITS
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription
from .platform_helpers import iter_platform_context, supported_descriptions

_LOGGER = logging.getLogger(__name__)


class GreeSelectDescription(
    GreeEntityDescription, SelectEntityDescription, frozen_or_thawed=True
):
    """Description of a Gree switch."""

    options_func: Callable[[], list[str]] | None = None
    value_func: Callable[[GreeDevice], str | None]
    set_func: Callable[[GreeDevice, str], None]
    updates_device: bool = True


def _set_humidity_control_mode(device: GreeDevice, mode: str) -> None:
    try:
        device.set_feature_humidity_control(HumidityControlMode[mode])

    except GreeHumidityControlUnavailable as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="humidity_mode_unavailable"
        ) from err

    except GreeSmartDryUnavailable as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="smart_dry_unavailable"
        ) from err

    except GreeContinuousDryUnavailable as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="continuous_dry_unavailable"
        ) from err


SELECT_TYPES: list[GreeSelectDescription] = [
    GreeSelectDescription(
        auto_device_support=True,
        key=GATTR_TEMP_UNITS,
        translation_key=GATTR_TEMP_UNITS,
        entity_category=EntityCategory.CONFIG,
        options=[f"º{member.name}" for member in TemperatureUnits],
        value_func=lambda device: f"º{device.target_temperature_unit.name}",
        set_func=lambda device, value: device.set_target_temperature_unit(
            TemperatureUnits[value.replace("º", "")]
        ),
        updates_device=True,
    ),
    GreeSelectDescription(
        key=GATTR_FEAT_HUMIDITY,
        translation_key=GATTR_FEAT_HUMIDITY,
        options=[member.name for member in HumidityControlMode],
        value_func=lambda device: str(device.feature_humidity_control),
        set_func=_set_humidity_control_mode,
        additional_available_func=lambda device: (
            device.operation_mode in (OperationMode.cool, OperationMode.dry)
        ),
        updates_device=True,
    ),
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches from a config entry."""

    _LOGGER.debug("Setting up Select Entities")

    entities: list[GreeSelect] = []

    for ctx in iter_platform_context(entry):
        descriptions = supported_descriptions(
            SELECT_TYPES,
            ctx.coordinator.device,
            ctx.device_config,
        )

        _LOGGER.debug(
            "Adding Select Entities for device '%s': %s",
            ctx.coordinator.device.mac_address,
            [d.key for d in descriptions],
        )

        entities.extend(
            GreeSelect(description, ctx.coordinator, False, ctx.check_availability)
            for description in descriptions
        )

    async_add_entities(entities)


class GreeSelect(GreeEntity, SelectEntity, RestoreEntity):  # pyright: ignore[reportIncompatibleVariableOverride]
    """A Gree select entity."""

    entity_description: GreeSelectDescription

    def __init__(
        self,
        description: GreeSelectDescription,
        coordinator: GreeCoordinator,
        restore_state: bool = True,
        check_availability: bool = True,
    ) -> None:
        """Initialize select."""
        super().__init__(description, coordinator, restore_state, check_availability)

        self.entity_description = description  # pyright: ignore[reportIncompatibleVariableOverride]

        # Set up options dynamically
        if description.options_func:
            self._attr_options = description.options_func()
        else:
            self._attr_options = description.options or ["None"]

        self._attr_current_option = self.entity_description.value_func(self.device)
        _LOGGER.debug(
            "Initialized select: %s (check_availability=%s) Options: %s",
            self.unique_id,
            self.check_availability,
            self._attr_options,
        )

    @property
    def current_option(self) -> str | None:  # pyright: ignore[reportIncompatibleVariableOverride]
        """Return the selected entity option to represent the entity state."""
        return self.entity_description.value_func(self.device)

    async def async_select_option(self, option: str) -> None:
        """Change the selected option."""
        _LOGGER.debug(
            "async_select_option(%s, %s, %s -> %s)",
            self.device.unique_id,
            self.entity_description.key,
            self.current_option,
            option,
        )

        try:
            self.entity_description.set_func(self.device, option)

            if self.entity_description.updates_device:
                await self.coordinator.push_device_status()

            # notify coordinator listeners of state change so that dependent entities are updated immediately
            self.coordinator.async_update_listeners()

            await self.coordinator.async_request_refresh()
        except Exception as err:
            _LOGGER.debug(
                "Error in async_select_option(%s, %s, %s -> %s)",
                self.device.unique_id,
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
                    "Restoring state for %s: %s", self.unique_id, last_state.state
                )
                if last_state.state not in ("unknown", "unavailable"):
                    try:
                        self.entity_description.set_func(self.device, last_state.state)

                        if self.entity_description.updates_device:
                            await self.coordinator.push_device_status()

                        self._attr_current_option = last_state.state
                    except Exception as err:  # noqa: BLE001
                        _LOGGER.error(
                            "Failed to restore state for %s: %s",
                            self.entity_id,
                            repr(err),
                        )
