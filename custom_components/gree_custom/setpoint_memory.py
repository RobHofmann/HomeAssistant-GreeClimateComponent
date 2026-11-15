"""The target temperature of a device, remembered per mode.

When the mode is changed on the wall panel of a zone controller, the panel sets
the target temperatures the zones had in that mode. A mode change over WiFi
does not. This class remembers the targets per device and mode, from what the
devices report, so a mode change from Home Assistant can set them. A standalone
or VRF unit uses it for its own target. It is Home Assistant behaviour, turned
on per device by the setpoint_memory option, but imports nothing from Home
Assistant. See docs/protocol.md.
"""

from collections.abc import Iterable, Mapping
import logging
from typing import Any

from .aiogree.api import DeviceType, OperationMode, TemperatureUnits
from .aiogree.device import GreeDevice
from .aiogree.errors import GreeError

_LOGGER = logging.getLogger(__name__)

# {device MAC: {mode name: {"temperature": 20.5, "unit": "C"}}}
type SetpointMemoryData = dict[str, dict[str, dict[str, Any]]]


class SetpointMemory:
    """Remembers the target temperature of devices per mode."""

    def __init__(self) -> None:
        """Start empty. The climate entity restores what was stored."""
        self._data: SetpointMemoryData = {}
        # The mode each device reported on its last read, see learn().
        self._last_mode: dict[str, OperationMode] = {}

    @property
    def data(self) -> SetpointMemoryData:
        """Return a copy of everything that is stored."""
        return {
            mac: {mode: dict(value) for mode, value in modes.items()}
            for mac, modes in self._data.items()
        }

    def restore(self, data: Mapping[str, Any]) -> None:
        """Take back what `data` gave before a restart. Values learned since win."""
        for mac, modes in data.items():
            if not isinstance(modes, Mapping):
                continue
            for mode, value in modes.items():
                if mode in OperationMode.__members__ and _is_stored_value(value):
                    self._data.setdefault(mac, {}).setdefault(mode, dict(value))

    def stored(self, device: GreeDevice, mode: OperationMode) -> float | None:
        """Return the stored target of a device for a mode, in the unit it uses now."""
        value = self._data.get(device.mac_address, {}).get(mode.name)
        if value is None:
            return None

        temperature = float(value["temperature"])
        unit = device.target_temperature_unit
        if value["unit"] == unit.name:
            return temperature
        if unit is TemperatureUnits.F:
            return float(round(temperature * 9 / 5 + 32))
        return round((temperature - 32) * 5 / 9 * 2) / 2

    def learn(self, device: GreeDevice) -> None:
        """Store what a device reported, once it reports the same mode twice in a row.

        The coordinator calls this after every read. A device reports its mode
        and its target in one reply, so a read in the middle of a mode change on
        the panel is not stored under the wrong mode.
        """
        mode = device.operation_mode
        if self._last_mode.get(device.mac_address) is mode:
            self._store(device, mode)
        self._last_mode[device.mac_address] = mode

    async def snapshot(
        self, devices: Iterable[GreeDevice], mode: OperationMode
    ) -> None:
        """Read the devices again and store their targets under the mode that ends.

        Call it before the new mode or a new target is set, so a change made on
        the panel or with the remote since the last poll is kept.
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
            self._store(device, mode)

    async def recall(
        self, devices: Iterable[GreeDevice], mode: OperationMode
    ) -> list[GreeDevice]:
        """Send the stored targets of a mode to the devices.

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
        """Set the stored target of a mode on a device, without sending it.

        Returns:
            True if the device got a new target temperature to send

        """
        temperature = self.stored(device, mode)
        if temperature is None or temperature == device.target_temperature:
            return False

        device.set_target_temperature(temperature)
        return True

    def _store(self, device: GreeDevice, mode: OperationMode) -> None:
        """Store the target of a device under a mode, if it belongs to that mode."""
        temperature = device.target_temperature
        if (
            temperature is None
            or device.operation_mode is not mode
            # Sent and not confirmed yet: stored once the device reports it
            or device.has_held_values
            # An off unit keeps a mode and a target that are not in use. A
            # zone's Pow is its damper, so a closed zone still counts.
            or (device.device_type is not DeviceType.ZONE and not device.power_mode)
        ):
            return

        unit = device.target_temperature_unit.name
        value = {"temperature": float(temperature), "unit": unit}
        modes = self._data.setdefault(device.mac_address, {})
        if modes.get(mode.name) != value:
            modes[mode.name] = value
            _LOGGER.debug(
                "[%s] Stored %s %s for %s",
                device.unique_id,
                temperature,
                unit,
                mode.name,
            )


def _is_stored_value(value: Any) -> bool:
    """Return True if `value` is a target as _store() stores it."""
    return (
        isinstance(value, Mapping)
        and isinstance(value.get("temperature"), int | float)
        and value.get("unit") in TemperatureUnits.__members__
    )
