"""Data update coordinator for Gree integration."""

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
    timedelta,
)

from .aiogree.device import GreeDevice
from .aiogree.errors import GreeBindingError, GreeConnectionError
from .helpers import try_find_new_ip

_LOGGER = logging.getLogger(__name__)

type GreeConfigEntry = ConfigEntry[dict[str, GreeCoordinator]]


class GreeCoordinator(DataUpdateCoordinator[None]):
    """Gree device coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: GreeConfigEntry,
        device: GreeDevice,
        scan_interval: int,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name="Gree Coordinator " + device.unique_id,
            config_entry=config_entry,
            update_interval=timedelta(seconds=scan_interval),
            always_update=True,
        )
        self.device: GreeDevice = device
        self._feature_auto_xfan: bool = False
        self._feature_auto_light: bool = False

    async def _async_setup(self):
        """Set up the coordinator.

        This is the place to set up your coordinator,
        or to load data, that only needs to be loaded once.

        This method will be called automatically during
        coordinator.async_config_entry_first_refresh.
        """
        await self.device.bind_device()

    async def _async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            await self.device.fetch_device_status()

        except GreeConnectionError as err:
            if not await try_find_new_ip(self.hass, self.device, self.config_entry):
                raise UpdateFailed("Error getting state from device") from err

            # retry once after IP recovery
            try:
                await self.device.fetch_device_status()
            except Exception as err_inner:
                raise UpdateFailed("Error getting state from device") from err_inner

        except GreeBindingError as err:
            _LOGGER.exception("Failed to initiate Gree device")
            raise ConfigEntryAuthFailed("Failed to initiate Gree device") from err

        except Exception as err:
            _LOGGER.exception("Error getting state from device")
            raise UpdateFailed("Error getting state from device") from err

    async def push_device_status(self):
        """Pushes the transient state to the device."""
        try:
            await self.device.push_device_status()
        except GreeConnectionError:
            if not await try_find_new_ip(self.hass, self.device, self.config_entry):
                raise  # propagate original error if recovery fails

            # retry once after recovering IP
            await self.device.push_device_status()

    def get_coordinator_diagnostics(self) -> dict[str, Any]:
        """Returns diagnostic data for the coordinator."""
        data = self.device.gather_diagnostics()
        data["coordinator_props"] = {
            "auto_light": self.feature_auto_light,
            "auto_xfan": self.feature_auto_xfan,
        }

        return data

    @property
    def feature_auto_light(self) -> bool:
        """Returns the state of the Auto Display Light Feature."""
        return self._feature_auto_light

    def set_feature_auto_light(self, value: bool) -> None:
        """Sets the state of the Auto Display Light Feature."""
        self._feature_auto_light = value

    @property
    def feature_auto_xfan(self) -> bool:
        """Returns the state of the Auto X-Fan Feature."""
        return self._feature_auto_xfan

    def set_feature_auto_xfan(self, value: bool) -> None:
        """Sets the state of the Auto X-Fan Feature."""
        self._feature_auto_xfan = value
