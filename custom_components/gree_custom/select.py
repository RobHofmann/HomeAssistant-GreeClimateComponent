"""Support for Gree select entities (e.g., external temperature sensor selection)."""

from collections.abc import Callable
import logging
from typing import TypeVar

from attr import dataclass

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import CONF_MAC, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .aiogree.api import GreeProp, HumidityControlMode, OperationMode, TemperatureUnits
from .aiogree.device import GreeDevice
from .aiogree.errors import GreeContinuousDryUnavailable, GreeHumidityControlUnavailable
from .const import (
    CONF_ADVANCED,
    CONF_DEVICES,
    CONF_DISABLE_AVAILABLE_CHECK,
    CONF_FEATURES,
    CONF_RESTORE_STATES,
    DEFAULT_DISABLE_AVAILABLE_CHECK,
    DEFAULT_RESTORE_STATES,
    DEFAULT_SUPPORTED_FEATURES,
    DOMAIN,
    GATTR_FEAT_HUMIDITY,
    GATTR_TEMP_UNITS,
)
from .coordinator import GreeConfigEntry, GreeCoordinator
from .entity import GreeEntity, GreeEntityDescription

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")  # T can be any type


def _set_humidity_control_mode(device: GreeDevice, mode: str) -> None:
    try:
        device.set_feature_humidity_control(HumidityControlMode[mode])

    except GreeHumidityControlUnavailable as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="humidity_mode_unavailable"
        ) from err

    except GreeContinuousDryUnavailable as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="continuous_dry_unavailable"
        ) from err


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GreeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switches from a config entry."""

    entities: list[GreeSelect] = []

    for d in entry.data.get(CONF_DEVICES, []):
        mac = d.get(CONF_MAC, "")
        coordinator: GreeCoordinator = entry.runtime_data[mac]
        if not coordinator:
            _LOGGER.error(
                "Cannot create Gree Selectors. No coordinator found for device '%s'",
                mac,
            )
            continue

        descriptions: list[GreeSelectDescription] = []

        if coordinator.device.supports_property(GreeProp.TARGET_TEMPERATURE_UNIT):
            descriptions.append(
                GreeSelectDescription[GreeDevice](
                    key=GATTR_TEMP_UNITS,
                    translation_key=GATTR_TEMP_UNITS,
                    entity_category=EntityCategory.CONFIG,
                    options=[f"º{member.name}" for member in TemperatureUnits],
                    value_func=lambda device: f"º{device.target_temperature_unit.name}",
                    set_func=lambda device, value: device.set_target_temperature_unit(
                        TemperatureUnits[value.replace("º", "")]
                    ),
                    updates_device=True,
                )
            )

        conf_supported_features = d.get(CONF_FEATURES, DEFAULT_SUPPORTED_FEATURES)
        if (
            GATTR_FEAT_HUMIDITY in conf_supported_features
            and coordinator.device.supports_property(GreeProp.FEATURE_HUMIDITY)
        ):
            descriptions.append(
                GreeSelectDescription[GreeDevice](
                    key=GATTR_FEAT_HUMIDITY,
                    translation_key=GATTR_FEAT_HUMIDITY,
                    options=[f"{member.name}" for member in HumidityControlMode],
                    value_func=lambda device: device.feature_humidity_control.name,
                    set_func=_set_humidity_control_mode,
                    additional_available_func=lambda device: (
                        device.operation_mode in (OperationMode.cool, OperationMode.dry)
                    ),
                    updates_device=True,
                )
            )

        _LOGGER.debug(
            "Adding Select Entities for device '%s': %s",
            coordinator.device.mac_address,
            [d.key for d in descriptions],
        )

        entities.extend(
            GreeSelect(
                description,
                coordinator,
                d.get(CONF_RESTORE_STATES, DEFAULT_RESTORE_STATES),
                check_availability=(
                    not entry.data[CONF_ADVANCED].get(
                        CONF_DISABLE_AVAILABLE_CHECK, DEFAULT_DISABLE_AVAILABLE_CHECK
                    )
                ),
            )
            for description in descriptions
        )

    async_add_entities(entities)


@dataclass(frozen=True, kw_only=True)
class GreeSelectDescription[T](GreeEntityDescription, SelectEntityDescription):
    """Description of a Gree switch."""

    additional_available_func = lambda _: True  # noqa: E731
    device_class = None
    entity_category = None
    entity_registry_enabled_default = True
    entity_registry_visible_default = True
    force_update = False
    icon = None
    has_entity_name = True
    name = None
    translation_key = None
    translation_placeholders = None
    unit_of_measurement = None
    options_func: Callable[[], list[str]] | None = None
    value_func: Callable[[T], str | None]
    set_func: Callable[[T, str], None]
    updates_device: bool = True


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
