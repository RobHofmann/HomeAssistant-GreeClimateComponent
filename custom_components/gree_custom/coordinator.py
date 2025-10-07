"""Data update coordinator for Gree integration."""

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
    timedelta,
)

from .gree_device import GreeDevice, GreeDeviceNotBoundError

_LOGGER = logging.getLogger(__name__)

type GreeConfigEntry = ConfigEntry[GreeCoordinator]


class GreeCoordinator(DataUpdateCoordinator[None]):
    """Gree device coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: GreeConfigEntry,
        device: GreeDevice,
        scan_interval: int = 30,
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
        except GreeDeviceNotBoundError as err:
            raise ConfigEntryAuthFailed("Failed to initiate Gree device") from err
        except ValueError as err:
            raise UpdateFailed("Error getting state from device") from err

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
