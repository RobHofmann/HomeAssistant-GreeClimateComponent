"""Data update coordinator for Gree integration."""

from datetime import datetime, timedelta
import logging
from typing import Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .aiogree.api import OperationMode
from .aiogree.device import GreeDevice
from .aiogree.errors import GreeBindingError, GreeConnectionError
from .helpers import try_find_new_ip

_LOGGER = logging.getLogger(__name__)

# Seconds between a command and one extra poll, when the device did not confirm
# the command on the read right after it. A VRF gateway needs a moment to pass
# a command on to the indoor unit and to update its cached state.
FOLLOW_UP_REFRESH_DELAY = 2.0

# Home Assistant config entry where the runtime data are Gree coordinators keyed by normalized MAC addresses ("xxxxxxxxxxxx").
type GreeConfigEntry = ConfigEntry[dict[str, GreeCoordinator]]


class GreeCoordinator(DataUpdateCoordinator[None]):
    """Gree device coordinator."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: GreeConfigEntry,
        scan_interval: int,
        check_availability: bool,
        restore_states: bool,
        device_config: dict[str, Any],
        device: GreeDevice,
    ) -> None:
        """Initialize the coordinator for a Gree device."""
        super().__init__(
            hass,
            _LOGGER,
            name="Gree Coordinator " + device.unique_id,
            config_entry=config_entry,
            update_interval=timedelta(seconds=scan_interval),
            always_update=True,
            setup_method=self._setup,
            update_method=self._update_data,
        )

        self.check_availability: bool = check_availability
        self.restore_states: bool = restore_states
        self.device_config: dict[str, Any] = device_config
        self.device: GreeDevice = device
        self._feature_auto_xfan: bool = False
        self._feature_auto_light: bool = False
        self._unsub_follow_up_refresh: CALLBACK_TYPE | None = None

    async def _setup(self) -> None:
        """Bind to the device before the first coordinator refresh.

        This is called automatically by
        `coordinator.async_config_entry_first_refresh()` and performs
        one-time initialization required before regular updates begin.
        """
        self.device.api_client.add_status_listener(self._device_pushed_status)
        # await self.device.bind()
        # We shouldn't arrive here without a bind successfully performed elsewhere

    def _device_pushed_status(self, status: dict[str, str]) -> None:
        _LOGGER.debug("[%s] Got data pushed from the device", self.device.unique_id)
        self.async_update_listeners()

    @override
    async def async_shutdown(self) -> None:
        """Clean up the coordinator and Gree device resources."""
        self._cancel_follow_up_refresh()
        self.device.api_client.remove_status_listener(self._device_pushed_status)

        await self.device.unbind_device()

        await super().async_shutdown()

    async def _update_data(self) -> None:
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

        self._schedule_follow_up_refresh()

    def _schedule_follow_up_refresh(self) -> None:
        """Poll again shortly after a command the device did not confirm yet.

        The read right after a command can still show the old state on a VRF
        gateway. The sent values are held meanwhile, see `DeviceState.hold()`.
        This extra poll lets the device confirm them within a few seconds
        instead of at the next scan interval. A standalone unit confirms on
        the first read, so it never gets this extra poll.

        `async_refresh()` is used instead of `async_request_refresh()`,
        because the request debouncer would push a second request within its
        cooldown back to 10 seconds.
        """
        if self._unsub_follow_up_refresh is not None:
            return

        if not self.device.has_held_values:
            return

        self._unsub_follow_up_refresh = async_call_later(
            self.hass, FOLLOW_UP_REFRESH_DELAY, self._async_follow_up_refresh
        )

    async def _async_follow_up_refresh(self, _now: datetime) -> None:
        """Run the follow-up poll, and plan the next one while values are held.

        The polls repeat until the device confirms the sent values or their
        hold ends. The poll after the hold ends shows what the device really
        reports, so a rejected command is not shown until the next scan
        interval.
        """
        self._unsub_follow_up_refresh = None
        await self.async_refresh()
        self._schedule_follow_up_refresh()

    def _cancel_follow_up_refresh(self) -> None:
        """Cancel a follow-up poll that has not run yet."""
        if self._unsub_follow_up_refresh is not None:
            self._unsub_follow_up_refresh()
            self._unsub_follow_up_refresh = None

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
