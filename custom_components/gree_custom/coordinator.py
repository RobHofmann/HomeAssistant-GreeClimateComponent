"""Data update coordinator for Gree integration."""

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aiogree.api import OperationMode
from .aiogree.device import GreeDevice
from .aiogree.errors import GreeBindingError, GreeConnectionError
from .helpers import try_find_new_ip

_LOGGER = logging.getLogger(__name__)

# Home Assistant config entry where the runtime data are Gree coordinators keyed by normalized MAC addresses ("xxxxxxxxxxxx").
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
        """Initialize the coordinator for a Gree device."""
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

    async def _async_setup(self) -> None:
        """Bind to the device before the first coordinator refresh.

        This is called automatically by
        `coordinator.async_config_entry_first_refresh()` and performs
        one-time initialization required before regular updates begin.
        """

        # await self.device.bind()
        # We shouldn't arrive here without a bind successfully performed elsewhere

    async def _async_update_data(self) -> None:
        """Update the device with he latest state.

        If communication fails due to a connection error, the coordinator
        attempts to discover the device's new IP address and retries the
        request once before reporting the update as failed.
        """
        try:
            await self.device.fetch_device_status()

        except GreeConnectionError as err:
            if not self.config_entry or not await try_find_new_ip(
                self.hass, self.device, self.config_entry
            ):
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

    async def push_device_status(self) -> None:
        """Push the current transient state to the device.

        If communication fails because the device IP has changed, attempt
        to rediscover the device and retry the request once.
        """
        try:
            await self.device.push_device_status()
        except GreeConnectionError:
            if not self.config_entry or not await try_find_new_ip(
                self.hass, self.device, self.config_entry
            ):
                raise  # propagate original error if recovery fails

            # retry once after recovering IP
            await self.device.push_device_status()

    def get_coordinator_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic information for the coordinator.

        Includes device diagnostics along with coordinator-specific
        configuration and feature flags.
        """
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
        """Set the state of the Auto Display Light Feature."""
        self._feature_auto_light = value

        # Immediately apply Light
        desired_light = value if self.device.power_mode else False
        if self.device.feature_light != desired_light:
            self.device.set_feature_light(desired_light)
            self.hass.async_create_task(self._push_status_and_refresh())

    @property
    def feature_auto_xfan(self) -> bool:
        """Returns the state of the Auto X-Fan Feature."""
        return self._feature_auto_xfan

    def set_feature_auto_xfan(self, value: bool) -> None:
        """Set the state of the Auto X-Fan Feature."""
        self._feature_auto_xfan = value

        # Immediately apply X-Fan
        if self.device.operation_mode == OperationMode.cool:
            self.device.set_feature_xfan(value)
            self.hass.async_create_task(self._push_status_and_refresh())

    async def _push_status_and_refresh(self) -> None:
        await self.push_device_status()
        await self.async_request_refresh()
