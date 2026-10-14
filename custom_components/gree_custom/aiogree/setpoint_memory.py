"""The target temperature of a device, remembered per mode.

The wall panel of a zone controller remembers the target temperature of every
zone for each mode, and sets them again when the mode is changed on the panel.
A mode change over WiFi does not do that: the zones keep the values of the old
mode (seen on a LE60-13/GH). This class keeps the same memory, so a mode change
from Home Assistant works like one on the panel. See docs/protocol.md.

- A device reports its mode and its target temperature in one reply, so the
  two belong together. A value is stored when the device reported the same
  mode on the poll before. A poll in the middle of a mode change on the panel
  is then not stored under the wrong mode.
- Before the mode is changed, `snapshot()` reads the devices again and stores
  them under the old mode, so a change made on the panel since the last poll is
  not lost. After the change, `recall()` sends the stored values of the new
  mode.
- What is stored are the raw columns that hold the target temperature, as
  `GreeDevice.target_temperature_props` gives them, per device MAC and mode.
  Today only zones give any.

The memory does not store itself. The owner loads `data` and saves it when
`on_change` is called.
"""

from collections.abc import Callable, Iterable, Mapping
import logging

from .api import PROP_KEY_TO_ENUM, GreeProp, OperationMode
from .device import GreeDevice
from .errors import GreeError

_LOGGER = logging.getLogger(__name__)

# {device MAC: {mode name: {column: raw value}}}
type SetpointMemoryData = dict[str, dict[str, dict[str, int]]]


class SetpointMemory:
    """Remembers the target temperature of devices per mode."""

    def __init__(
        self,
        data: SetpointMemoryData | None = None,
        on_change: Callable[[], None] | None = None,
    ) -> None:
        """Start with stored data, if there is any.

        Args:
            data: What `data` held before, for example after a restart.
            on_change: Called after a stored value changed.

        """
        self._data: SetpointMemoryData = data or {}
        self._on_change = on_change
        # The mode each device reported on its last poll.
        self._last_mode: dict[str, OperationMode] = {}

    @property
    def data(self) -> SetpointMemoryData:
        """Everything that is stored, to be saved by the owner."""
        return self._data

    def stored(self, device_mac: str, mode: OperationMode) -> dict[GreeProp, int]:
        """Return the stored target temperature columns of a device for one mode."""
        columns = self._data.get(device_mac, {}).get(mode.name, {})
        return {
            PROP_KEY_TO_ENUM[key]: value
            for key, value in columns.items()
            if key in PROP_KEY_TO_ENUM
        }

    def learn(self, device: GreeDevice) -> None:
        """Store what a device reported, once its mode is the same twice in a row.

        Call this after every poll of the device.
        """
        props = device.target_temperature_props
        if props is None:
            return

        mode = device.operation_mode
        previous = self._last_mode.get(device.mac_address)
        self._last_mode[device.mac_address] = mode

        # Values that were just sent and are not confirmed yet are stored once
        # the device reports them.
        if previous is mode and not device.has_held_values:
            self._remember(device, mode, props)

    async def snapshot(
        self, devices: Iterable[GreeDevice], mode: OperationMode
    ) -> None:
        """Read the devices again and store their values under the mode that is about to end."""
        for device in devices:
            try:
                await device.fetch_device_status()
            except GreeError:
                _LOGGER.debug(
                    "[%s] Could not read the device before the mode change",
                    device.unique_id,
                )
                continue

            props = device.target_temperature_props
            if (
                props is not None
                and device.operation_mode is mode
                and not device.has_held_values
            ):
                self._remember(device, mode, props)

    async def recall(
        self, devices: Iterable[GreeDevice], mode: OperationMode
    ) -> list[GreeDevice]:
        """Send the stored target temperatures of a mode to the devices.

        Returns:
            The devices that got a new target temperature

        """
        changed: list[GreeDevice] = []
        for device in devices:
            stored = self.stored(device.mac_address, mode)
            if not stored or stored == device.target_temperature_props:
                continue

            device.set_target_temperature_props(stored)
            try:
                await device.push_device_status()
            except GreeError:
                _LOGGER.warning(
                    "[%s] Could not set the stored target temperature for %s",
                    device.unique_id,
                    mode.name,
                )
                continue
            changed.append(device)

        return changed

    def _remember(
        self, device: GreeDevice, mode: OperationMode, props: Mapping[GreeProp, int]
    ) -> None:
        """Store the target temperature columns a device has now for one mode."""
        columns = {prop.value: value for prop, value in props.items()}
        modes = self._data.setdefault(device.mac_address, {})
        if modes.get(mode.name) == columns:
            return

        modes[mode.name] = columns
        _LOGGER.debug(
            "[%s] Stored target temperature %s for %s",
            device.unique_id,
            columns,
            mode.name,
        )
        if self._on_change is not None:
            self._on_change()
