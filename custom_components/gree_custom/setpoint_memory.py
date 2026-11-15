"""The target temperature of a device, remembered per mode.

When the mode is changed on the wall panel of a zone controller, the panel sets
the target temperatures the zones had in that mode. A mode change over WiFi
does not. This class remembers the targets per device and mode, from what the
coordinators read, so a mode change from Home Assistant can set them as the
panel does. A standalone or VRF unit uses it for its own target. The memory
does no I/O of its own. See docs/protocol.md.
"""

from typing import Any

from .aiogree.api import DeviceType, GreeProp, OperationMode, TemperatureUnits
from .aiogree.device import GreeDevice

# {device MAC: {mode name: {"temperature": 20.5, "unit": "C"}}}
type SetpointMemoryData = dict[str, dict[str, dict[str, Any]]]


def offers_setpoint_memory(device: GreeDevice) -> bool:
    """Return True if the setpoint_memory option is for this device.

    A unit with a target temperature of its own has it, and so has the ducted
    unit of a zone controller, for all of its zones.
    """
    if device.device_type is DeviceType.ZONE_CONTROLLER:
        return True
    return device.device_type is not DeviceType.ZONE and device.supports_property(
        GreeProp.TARGET_TEMPERATURE_1
    )


class SetpointMemory:
    """Remembers the target temperature of devices per mode."""

    def __init__(self) -> None:
        """Start empty. The climate entity restores what was stored."""
        self._data: SetpointMemoryData = {}
        # The mode each device reported on its last read
        self._last_mode: dict[str, OperationMode] = {}

    @property
    def data(self) -> SetpointMemoryData:
        """Return a copy of everything that is stored."""
        return _copy(self._data)

    def restore(self, data: SetpointMemoryData) -> None:
        """Take back what `data` gave before a restart."""
        self._data = _copy(data)

    def learn(self, device: GreeDevice) -> None:
        """Store what a device reported, once it reports the same mode twice in a row.

        The coordinator calls this after every read. A device reports its mode
        and its target in one reply, so a read in the middle of a mode change on
        the panel is not stored under the wrong mode.
        """
        mode = device.operation_mode
        last_mode = self._last_mode.get(device.mac_address)
        self._last_mode[device.mac_address] = mode
        temperature = device.target_temperature
        if (
            mode is not last_mode
            or temperature is None
            # Sent and not confirmed yet: stored once the device reports it
            or device.has_held_values
            # An off unit keeps a mode and a target that are not in use. A
            # zone's Pow is its damper, so a closed zone still counts.
            or (device.device_type is not DeviceType.ZONE and not device.power_mode)
        ):
            return

        self._data.setdefault(device.mac_address, {})[mode.name] = {
            "temperature": float(temperature),
            "unit": device.target_temperature_unit.name,
        }

    def apply(self, device: GreeDevice, mode: OperationMode) -> bool:
        """Set the stored target of a mode on a device, without sending it.

        Returns:
            True if the device got a new target temperature to send

        """
        stored = self._data.get(device.mac_address, {}).get(mode.name)
        if stored is None:
            return False

        temperature = stored["temperature"]
        unit = device.target_temperature_unit
        if stored["unit"] != unit.name:
            temperature = (
                float(round(temperature * 9 / 5 + 32))
                if unit is TemperatureUnits.F
                else round((temperature - 32) * 5 / 9 * 2) / 2
            )
        if temperature == device.target_temperature:
            return False

        device.set_target_temperature(temperature)
        return True


def _copy(data: SetpointMemoryData) -> SetpointMemoryData:
    return {
        mac: {mode: dict(value) for mode, value in modes.items()}
        for mac, modes in data.items()
    }
