"""Data update coordinator for Gree integration."""

from asyncio import timeout
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
            async with timeout(10):
                await self.device.fetch_device_status()
        except GreeDeviceNotBoundError as err:
            raise ConfigEntryAuthFailed("Failed to initiate Gree device") from err
        except ValueError as err:
            raise UpdateFailed("Error getting state from device") from err
