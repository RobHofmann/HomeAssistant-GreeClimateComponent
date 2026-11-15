"""The target temperature of a device, remembered per mode.

The wall panel of a zone controller remembers the target temperature of every
zone for each mode, and sets them again when the mode is changed on the panel.
A mode change over WiFi does not do that: the zones keep the values of the old
mode (seen on a LE60-13/GH). This class keeps the same memory, so a mode change
from Home Assistant works like one on the panel. See docs/protocol.md.

It is Home Assistant behaviour, turned on per device by the setpoint_memory
option, so it lives here and not in aiogree. It still imports nothing from
Home Assistant, so the tests need no Home Assistant instance.

- A device reports its mode and its target temperature in one reply, so the
  two belong together. A value is stored when the device reported the same
  mode on the read before. A read in the middle of a mode change on the panel
  is then not stored under the wrong mode. Another look at the same read does
  not count, see `GreeDevice.status_reads`.
- Only what a device reported is stored, never a value that is set and not
  sent yet. A standalone or VRF unit learns only while it is on. A zone also
  learns while it is closed: its `Pow` is its damper, not the power of the
  unit.
- Before the mode is changed, `snapshot()` reads the devices again and stores
  them under the old mode, so a change made on the panel since the last poll is
  not lost. After the change, `recall()` sends the stored values of the new
  mode.
- What is stored are the raw columns that hold the target temperature, as
  `GreeDevice.target_temperature_props` gives them, per device MAC and mode:
  `StTem` and `StFahFlg` for a zone, `SetTem` and `TemRec` for a standalone or
  VRF unit.
- For a unit that remembers its own target, `apply()` sets the stored value
  without sending it, so it can go out in the same command as the new mode.
  It uses `GreeDevice.set_state_props()`, since the raw columns need no
  conversion. A target set for the same command, for example by
  `climate.set_temperature` with a mode, wins over the stored one.

The memory does not store itself. The owner loads `data` and saves it when
`on_change` is called.
"""

from collections.abc import Callable, Iterable, Mapping
import logging

from .aiogree.api import PROP_KEY_TO_ENUM, DeviceType, GreeProp, OperationMode
from .aiogree.device import GreeDevice
from .aiogree.errors import GreeError

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
        # The read and the mode each device reported on it, as last seen by
        # learn().
        self._last_read: dict[str, tuple[int, OperationMode]] = {}

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
        """Store what a device reported, once it reports the same mode twice in a row.

        Call this whenever the device may have been read, for example from a
        coordinator listener. A call without a new read changes nothing.
        """
        props = device.target_temperature_props
        if props is None:
            return

        read = device.status_reads
        last = self._last_read.get(device.mac_address)
        if last is not None and last[0] == read:
            return
        mode = device.operation_mode
        self._last_read[device.mac_address] = (read, mode)

        # Values that were just sent and are not confirmed yet are stored once
        # the device reports them.
        if (
            last is not None
            and last[1] is mode
            and not device.has_held_values
            and _is_running(device)
        ):
            self._remember(device, mode, props)

    async def snapshot(
        self, devices: Iterable[GreeDevice], mode: OperationMode
    ) -> None:
        """Read the devices again and store their values under the mode that is about to end.

        What the devices report is stored, not a target that is set and not
        sent yet.
        """
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
                and _is_running(device)
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
            if not self.apply(device, mode):
                continue

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

    def apply(self, device: GreeDevice, mode: OperationMode) -> bool:
        """Set the stored target temperature of a mode on a device, without sending it.

        A target that is already set for the same command wins, for example
        one given to climate.set_temperature with the mode.

        Returns:
            True if the device got a new target temperature to send

        """
        stored = self.stored(device.mac_address, mode)
        if (
            not stored
            or device.has_pending_target_temperature
            or stored == device.target_temperature_props
        ):
            return False

        device.set_state_props(stored)
        return True

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


def _is_running(device: GreeDevice) -> bool:
    """Return True if the target of the device belongs to the mode it reports.

    A standalone or VRF unit that is off keeps a mode and a target, but they
    are not in use. A zone's Pow is its damper, not the power of the unit, so
    a closed zone counts as running.
    """
    return device.device_type is DeviceType.ZONE or device.power_mode
