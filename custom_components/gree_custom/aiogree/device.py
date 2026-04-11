"""Contains the API to interface with the Gree device."""

import logging
from typing import Any

from .api import (
    EncryptionVersion,
    FanSpeed,
    GreeDiscoveredDevice,
    GreeProp,
    HorizontalSwingMode,
    OperationMode,
    TemperatureUnits,
    VerticalSwingMode,
    gree_get_device_info,
    gree_get_status,
    gree_get_sub_devices_list,
    gree_set_status,
    gree_try_bind,
)
from .cipher import CipherBase, get_cipher
from .const import (
    DEFAULT_CONNECTION_MAX_ATTEMPTS,
    DEFAULT_CONNECTION_TIMEOUT,
    DEFAULT_DEVICE_UID,
)
from .errors import GreeBindingError, GreeError, GreeProtocolError
from .helpers import (
    TempOffsetResolver,
    gree_get_target_temp_props_from_c,
    gree_get_target_temp_props_from_f,
    gree_get_target_temperature_c,
    gree_get_target_temperature_f,
)
from .transport import GreeTransport

_LOGGER = logging.getLogger(__name__)


class GreeDevice:
    """Representation of a Gree device."""

    def __init__(
        self,
        name: str,
        ip_addr: str,
        mac_addr: str,
        port: int,
        encryption_key: str,
        encryption_version: EncryptionVersion | None = None,
        uid: int = DEFAULT_DEVICE_UID,
        max_connection_attempts: int = DEFAULT_CONNECTION_MAX_ATTEMPTS,
        timeout: int = DEFAULT_CONNECTION_TIMEOUT,
    ) -> None:
        """Initialize the Gree device."""

        _LOGGER.info(
            "Initialize the GREE Device API for: %s (%s:%d)",
            mac_addr,
            ip_addr,
            port,
        )
        _LOGGER.debug(
            "Version: %s, Key: %s[redacted]", encryption_version, encryption_key[:5]
        )

        self._name: str = name
        self._ip_addr: str = ip_addr
        self._port: int = port
        self._max_connection_attempts: int = max_connection_attempts
        self._timeout: int = timeout

        # For VRF units, the mac will be in the sub_device@main_device format
        # where the sub_device is the device we are controling and
        # main_device is the controller for that sub_device
        mac_addr = mac_addr.replace(":", "").replace("-", "").lower()

        if "@" in mac_addr:
            self._mac_addr, self._mac_addr_controller = mac_addr.split("@", 1)
        else:
            self._mac_addr = self._mac_addr_controller = mac_addr

        self._transport = GreeTransport(ip_addr, port, max_connection_attempts, timeout)

        self._encryption_version: EncryptionVersion | None = encryption_version
        self._encryption_key: str = encryption_key
        self._cipher: CipherBase | None = None
        self._uid: int = uid

        self._raw_state: dict[GreeProp, int] = {}
        self._new_raw_state: dict[GreeProp, int] = {}
        self._is_bound: bool = False
        self._is_available: bool = False
        self._uniqueid: str = self._mac_addr

        self._props_to_update: list[GreeProp] = list(GreeProp)
        # Don't poll the beeper state
        self._props_to_update.remove(GreeProp.BEEPER)
        self._props_to_update.remove(GreeProp.BEEPER_NEW)

        self._temp_processor_indoors: TempOffsetResolver | None = None
        self._temp_processor_outdoors: TempOffsetResolver | None = None
        self._beeper = False

        self._raw_info: dict[str, str | None] = {}
        self._firmware_version: str | None = None
        self._firmware_code: str | None = None
        self._subdevicesCount: int = 0

    async def bind_device(self) -> bool:
        """Setup the device (async)."""

        if self._is_bound:
            return True

        # Use fetch_device_info (targeted scan) to the device
        # since binding only succeeds after a scan
        try:
            await self.fetch_device_info()
        except Exception as err:
            raise GreeBindingError(
                "Could not fetch device info before binding"
            ) from err

        try:
            key, version = await gree_try_bind(
                self._mac_addr_controller,
                self._uid,
                self._encryption_version,
                self._encryption_key,
                self._transport,
            )

        except GreeBindingError:
            raise
        except Exception as e:
            raise GreeBindingError(f"Failed binding to device {self._ip_addr}") from e

        else:
            self._encryption_key = key
            self._encryption_version = version
            _LOGGER.info(
                "Device is bound with version %s and key %s",
                version,
                key[:5] + "[redacted]",
            )

            self._cipher = get_cipher(version, key)
            self._is_available = True
            self._is_bound = True

        return True

    async def fetch_device_info(self, cipher: CipherBase = None):
        """Updates the device info fields."""
        try:
            self._raw_info = await gree_get_device_info(
                self._transport, cipher or self._cipher
            )

        except Exception as e:
            raise GreeProtocolError(
                f"Failed fetching device info for {self._ip_addr}"
            ) from e

        else:
            if self._raw_info.get("mac", "") != self._mac_addr_controller:
                raise GreeProtocolError(
                    f"Wrong device info for {self._ip_addr}. MAC mismatch {self._raw_info.get('mac', '')} not {self._mac_addr_controller}."
                )
            self._firmware_version = self._raw_info.get("firmware_version")
            self._firmware_code = self._raw_info.get("firmware_code")
            self._subdevicesCount = int(self._raw_info.get("subdevices_count", 0) or 0)

    async def fetch_sub_devices(self) -> list[GreeDiscoveredDevice]:
        """Get the sub devices list."""
        _LOGGER.debug("Trying to get subdevices")

        if not self._is_bound:
            await self.bind_device()

        assert self._cipher is not None

        if not self._subdevicesCount:
            return []

        if self._mac_addr != self._mac_addr_controller:
            return []  # For VRF, a non main device does not have subdevices

        discovered_devices: list[GreeDiscoveredDevice] = []

        try:
            subs = await gree_get_sub_devices_list(
                self._mac_addr_controller,
                self._uid,
                self._cipher,  # NOTE: Check if this should use the generic or the device key
                self._transport,
            )
        except GreeProtocolError:
            self._is_available = False
            raise

        except Exception as err:
            self._is_available = False
            raise GreeError("Error getting subdevices") from err

        else:
            for sub_device in subs:
                sub_mac = sub_device.get("mac", "")
                if sub_mac:
                    discovered_sub_device = GreeDiscoveredDevice(
                        name=f"{sub_device.get('name', '') or f'Gree {sub_mac[:4]}@{self.mac_address_controller[-4:]}'}",
                        host=self._ip_addr,
                        mac=sub_mac,
                        port=self._port,
                        brand=sub_device.get("brand", "Gree"),
                        model=sub_device.get("mid", "HVAC"),
                        uid=self._uid,
                        subdevices=0,
                    )
                    discovered_devices.append(discovered_sub_device)
                    _LOGGER.debug(
                        "Discovered sub-device: %s",
                        discovered_sub_device,
                    )

            _LOGGER.debug("Subdevices of '%s': %s", self._mac_addr_controller, subs)
            self._is_available = True

            return discovered_devices

    async def fetch_device_status(self):
        """Get the device status (async)."""
        _LOGGER.debug("Trying to get device status")

        if not self._is_bound:
            await self.bind_device()

        assert self._cipher is not None

        try:
            state, _ = await gree_get_status(
                self._mac_addr_controller,
                self._mac_addr,
                self._uid,
                self._props_to_update,
                self._cipher,
                self._transport,
            )
            self._raw_state.update(state)

            # if self._mac_addr != self._mac_addr_sub:
            #     sub_state, _ = await gree_get_status(
            #         self._ip_addr,
            #         self._mac_addr,
            #         self._mac_addr,
            #         self._port,
            #         self._uid,
            #         self._cipher,
            #         props_not_present,
            #         self._max_connection_attempts,
            #         self._timeout,
            #     )
            #     self._raw_state.update(sub_state)

            self._is_available = True

        except GreeProtocolError:
            raise

        except Exception as err:
            self._is_available = False
            raise GreeError("Error getting device status") from err

        self._remove_unsupported_props()

    async def update_device_status(self):
        """Send the new local device state to the device and updates local state if successfull."""
        if not self._is_bound:
            await self.bind_device()

        assert self._cipher is not None

        # If there is no change in the properties, do nothing
        has_updated_states = any(
            self._raw_state.get(k) != v for k, v in self._new_raw_state.items()
        )
        if not has_updated_states:
            _LOGGER.debug("No changes in the properties, skipping update to device")
            return

        self._new_raw_state[GreeProp.BEEPER] = 0 if self._beeper else 1
        self._new_raw_state[GreeProp.BEEPER_NEW] = 1 if self._beeper else 0

        try:
            self._raw_state.update(
                await gree_set_status(
                    self._mac_addr_controller,
                    self._mac_addr,
                    self._uid,
                    self._new_raw_state,
                    self._cipher,
                    self._transport,
                )
            )
            self._new_raw_state.clear()
            self._is_available = True

        except GreeProtocolError:
            raise

        except Exception as err:
            self._is_available = False
            raise GreeError("Error setting device status") from err

    def _set_device_status(self, props: dict[GreeProp, int]) -> None:
        """Sets a new local device status. Use 'update_device_status' to update the device."""
        self._new_raw_state.update(props)

    def _bool_from_raw_state(
        self, prop: GreeProp, default: int | None = 0
    ) -> bool | None:
        return self._get_prop_raw(prop, 0) != 0

    def _remove_unsupported_props(self):
        """Remove unsupported properties from the list to update."""

        # Remove all unsupported properties
        # A unsupported propery is one that the device returns
        # with an empty string, or nothing at all
        # If that is the case, _state_raw should not contain that property
        # In case it still has it, we remove it here as well
        for p in list(self._props_to_update):
            if not self.supports_property(p):
                self._props_to_update.remove(p)
                self._raw_state.pop(p, None)
                _LOGGER.debug("No longer updating property: %s", p)

        # Sensors should also be invalidated if their values are not expected (=0)
        if (
            GreeProp.SENSOR_TEMPERATURE in self._props_to_update
            and self._get_prop_raw(GreeProp.SENSOR_TEMPERATURE, 0) == 0
        ):
            self._props_to_update.remove(GreeProp.SENSOR_TEMPERATURE)
            self._raw_state.pop(GreeProp.SENSOR_TEMPERATURE, None)
            _LOGGER.debug(
                "No longer updating property due to bad value: %s",
                GreeProp.SENSOR_TEMPERATURE,
            )

        if (
            GreeProp.SENSOR_OUTSIDE_TEMPERATURE in self._props_to_update
            and self._get_prop_raw(GreeProp.SENSOR_OUTSIDE_TEMPERATURE, 0) == 0
        ):
            self._props_to_update.remove(GreeProp.SENSOR_OUTSIDE_TEMPERATURE)
            self._raw_state.pop(GreeProp.SENSOR_OUTSIDE_TEMPERATURE, None)
            _LOGGER.debug(
                "No longer updating property due to bad value: %s",
                GreeProp.SENSOR_OUTSIDE_TEMPERATURE,
            )

        if (
            GreeProp.SENSOR_HUMIDITY in self._props_to_update
            and self._get_prop_raw(GreeProp.SENSOR_HUMIDITY, 0) == 0
        ):
            self._props_to_update.remove(GreeProp.SENSOR_HUMIDITY)
            self._raw_state.pop(GreeProp.SENSOR_HUMIDITY, None)
            _LOGGER.debug(
                "No longer updating property due to bad value: %s",
                GreeProp.SENSOR_HUMIDITY,
            )

    def _get_prop_raw(self, prop: GreeProp, default: int | None = None) -> int | None:
        """Get the raw value of a property. If does not exist, returns default."""
        if prop not in self._raw_state:
            _LOGGER.warning(
                "Property '%s' not found in state of device '%s'", prop, self.name
            )
            return default
        return self._raw_state.get(prop, default)

    def log_device_info(self):
        """Log basic device information."""

        capabilities = []
        if self.supports_property(GreeProp.SENSOR_TEMPERATURE):
            capabilities.append("Temperature Sensor")
        if self.supports_property(GreeProp.SENSOR_OUTSIDE_TEMPERATURE):
            capabilities.append("Outside Temperature Sensor")
        if self.supports_property(GreeProp.SENSOR_HUMIDITY):
            capabilities.append("Humidity Sensor")

        _LOGGER.info(
            "Capabilities: %s", ", ".join(capabilities) if capabilities else "None"
        )

        _LOGGER.info(
            "Indoor Temperature: %s ºC",
            self.indoors_temperature_c
            if self.supports_property(GreeProp.SENSOR_TEMPERATURE)
            else None,
        )
        _LOGGER.info(
            "Outddor Temperature: %s ºC",
            self.outdoors_temperature_c
            if self.supports_property(GreeProp.SENSOR_OUTSIDE_TEMPERATURE)
            else None,
        )
        _LOGGER.info(
            "Target Temperature: %s º%s",
            self.target_temperature,
            self.target_temperature_unit.name,
        )
        _LOGGER.info("Mode: %s", self.operation_mode.name)

    def gather_diagnostics(self) -> dict[str, Any]:
        """Returns diagnostic info for the device."""
        data: dict[str, Any] = {}

        info = {
            "ip": self._ip_addr,
            "mac": self._mac_addr,
            "mac_controller": self._mac_addr_controller,
            "port": self._port,
            "timeout": self._timeout,
            "max_connections": self._max_connection_attempts,
            "is_bound": self._is_bound,
            "is_available": self._is_available,
            "beeper": self.beeper,
            "encryption": str(self.encryption_version),
            "key": self.encryption_key[:5] + "[redacted]",
        }

        data["info"] = info
        data["raw_info"] = self._raw_info
        data["state"] = {str(k): v for k, v in self._raw_state.items()}
        data["state_unsaved"] = {str(k): v for k, v in self._new_raw_state.items()}

        return data

    def supports_property(self, property: GreeProp) -> bool:
        """Returns True if the device endpoint supports the property."""
        # We consider a property as unsupported if it is not present in the raw state list
        # This assumes that the full state is fetched at least once before this method is called
        return property in self._raw_state if property is not GreeProp.BEEPER else True

    @property
    def name(self) -> str:
        """Returns the friendly name of the device."""
        return self._name

    @property
    def encryption_key(self) -> str:
        """Return the encryption key of the device."""
        return self._encryption_key

    @property
    def encryption_version(self) -> EncryptionVersion | None:
        """Return the encryption version of the device."""
        return self._encryption_version

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the device (MAC)."""
        return self._uniqueid

    @property
    def mac_address(self) -> str:
        """Return the main MAC address of the device."""
        return self._mac_addr

    @property
    def mac_address_controller(self) -> str:
        """Return the secondary MAC address of the device. For non VRF is the same as MAC otherwise is the MAC of the main controller (same as MAC for the main device)."""
        return self._mac_addr_controller

    @property
    def firmware_version(self) -> str | None:
        """Returns the firmware version."""
        if self._firmware_version and self._firmware_code:
            return f"{self._firmware_version} ({self._firmware_code})"
        if self._firmware_version:
            return self._firmware_version
        if self._firmware_code:
            return self._firmware_code
        return None

    @property
    def available(self) -> bool:
        """Return True if the device is bouund and last connection was successful."""
        return self._is_bound and self._is_available

    @property
    def has_hvac_error(self) -> bool | None:
        """Return if there is an error with the device."""
        return self._bool_from_raw_state(GreeProp.FAULT, None)

    @property
    def beeper(self) -> bool:
        """Return True if the device beeper is enabled."""
        return self._beeper

    def set_beeper(self, value: bool) -> None:
        """Set the device beeper state."""
        self._beeper = value

    @property
    def indoors_temperature_c(self) -> int | None:
        """Return the current temperature if available."""
        if self.supports_property(GreeProp.SENSOR_TEMPERATURE):
            if self._temp_processor_indoors is None:
                self._temp_processor_indoors = TempOffsetResolver()

            raw_c = self._get_prop_raw(GreeProp.SENSOR_TEMPERATURE, None)
            return (
                int(self._temp_processor_indoors.evaluate(raw_c))
                if raw_c is not None
                else None
            )

        return None

    @property
    def outdoors_temperature_c(self) -> int | None:
        """Return the current outside temperature if available."""
        if self.supports_property(GreeProp.SENSOR_OUTSIDE_TEMPERATURE):
            if self._temp_processor_outdoors is None:
                self._temp_processor_outdoors = TempOffsetResolver()

            raw_c = self._get_prop_raw(GreeProp.SENSOR_OUTSIDE_TEMPERATURE, None)
            return (
                int(self._temp_processor_outdoors.evaluate(raw_c))
                if raw_c is not None
                else None
            )

        return None

    @property
    def humidity(self) -> int | None:
        """Return the current humidity if available."""
        return self._get_prop_raw(GreeProp.SENSOR_HUMIDITY, None)

    @property
    def power_mode(self) -> bool:
        """Return the current power mode."""
        return self._bool_from_raw_state(GreeProp.POWER)

    def set_power_mode(self, value: bool):
        """Sets the device power mode."""
        self._set_device_status({GreeProp.POWER: 1 if value else 0})

    @property
    def operation_mode(self) -> OperationMode:
        """Return the current operation mode."""
        return OperationMode(
            self._get_prop_raw(GreeProp.OP_MODE, OperationMode.auto.value)
        )

    def set_operation_mode(self, mode: OperationMode):
        """Sets the device operation mode."""
        self._set_device_status({GreeProp.OP_MODE: mode})

    @property
    def fan_speed(self) -> FanSpeed:
        """Return the current fan speed."""
        return FanSpeed(self._get_prop_raw(GreeProp.FAN_SPEED, FanSpeed.auto.value))

    def set_fan_speed(self, speed: FanSpeed):
        """Sets the device fan speed mode."""
        self._set_device_status({GreeProp.FAN_SPEED: speed})

    @property
    def vertical_swing_mode(self) -> VerticalSwingMode:
        """Return the current vertical swing setting."""
        return VerticalSwingMode(
            self._get_prop_raw(GreeProp.SWING_VERTICAL, VerticalSwingMode.default.value)
        )

    def set_vertical_swing_mode(self, swing_mode: VerticalSwingMode):
        """Sets the device vertical swing mode."""
        self._set_device_status({GreeProp.SWING_VERTICAL: swing_mode})

    @property
    def horizontal_swing_mode(self) -> HorizontalSwingMode:
        """Return the current horizontal swing setting."""
        return HorizontalSwingMode(
            self._get_prop_raw(
                GreeProp.SWING_HORIZONTAL, HorizontalSwingMode.default.value
            )
        )

    def set_horizontal_swing_mode(self, swing_mode: HorizontalSwingMode):
        """Sets the device horizontal swing mode."""
        self._set_device_status({GreeProp.SWING_HORIZONTAL: swing_mode})

    @property
    def target_temperature_unit(self) -> TemperatureUnits:
        """Return the units of the target temperature."""
        return TemperatureUnits(
            self._get_prop_raw(
                GreeProp.TARGET_TEMPERATURE_UNIT, TemperatureUnits.C.value
            )
        )

    def set_target_temperature_unit(self, units: TemperatureUnits):
        """Sets the units of the target temperature."""
        self._set_device_status({GreeProp.TARGET_TEMPERATURE_UNIT: units})

    @property
    def target_temperature(self) -> float:
        """Return the target temperature in target_temperature_unit."""

        raw_c = self._get_prop_raw(GreeProp.TARGET_TEMPERATURE, 0)
        tem_rec = self._get_prop_raw(GreeProp.TARGET_TEMPERATURE_BIT, 0)

        if raw_c is not None and tem_rec is not None:
            if self.target_temperature_unit == TemperatureUnits.F:
                return gree_get_target_temperature_f(raw_c, tem_rec)
            if self.target_temperature_unit == TemperatureUnits.C:
                return gree_get_target_temperature_c(raw_c, tem_rec)
        return 0.0

    def set_target_temperature(self, value: float) -> None:
        """Sets the target temperature in target_temperature_unit."""

        if self.target_temperature_unit == TemperatureUnits.F:
            if not value.is_integer():
                _LOGGER.warning(
                    "The Gree API does not support floating Fahrenheit values, the applied value will be: %.2f -> %d",
                    value,
                    round(value),
                )
            raw_c, tem_rec = gree_get_target_temp_props_from_f(round(value))
        else:
            raw_c, tem_rec = gree_get_target_temp_props_from_c(value)

        self._set_device_status(
            {
                GreeProp.TARGET_TEMPERATURE: raw_c,
                GreeProp.TARGET_TEMPERATURE_BIT: tem_rec,
            }
        )

    @property
    def feature_light_sensor(self) -> bool:
        """Return the light sensor state."""
        return self._bool_from_raw_state(GreeProp.FEAT_SENSOR_LIGHT)

    def set_feature_light_sensor(self, value: bool) -> None:
        """Set the light sensor state."""
        self._set_device_status({GreeProp.FEAT_SENSOR_LIGHT: 1 if value else 0})

    @property
    def feature_fresh_air(self) -> bool:
        """Return the fresh air mode state."""
        return self._bool_from_raw_state(GreeProp.FEAT_FRESH_AIR)

    def set_feature_fresh_air(self, value: bool) -> None:
        """Set the fresh air mode state."""
        self._set_device_status({GreeProp.FEAT_FRESH_AIR: 1 if value else 0})

    @property
    def feature_x_fan(self) -> bool:
        """Return the x-fan mode state."""
        return self._bool_from_raw_state(GreeProp.FEAT_XFAN)

    def set_feature_xfan(self, value: bool) -> None:
        """Set the x-fan mode state."""
        self._set_device_status({GreeProp.FEAT_XFAN: 1 if value else 0})

    @property
    def feature_health(self) -> bool:
        """Return the health mode state."""
        return self._bool_from_raw_state(GreeProp.FEAT_HEALTH)

    def set_feature_health(self, value: bool) -> None:
        """Set the health mode state."""
        self._set_device_status({GreeProp.FEAT_HEALTH: 1 if value else 0})

    @property
    def feature_sleep(self) -> bool:
        """Return the sleep mode state."""
        val1 = self._bool_from_raw_state(GreeProp.FEAT_SLEEP_MODE_SWING)
        val2 = self._bool_from_raw_state(GreeProp.FEAT_SLEEP_MODE)

        return val1 is True or val2 is True

    def set_feature_sleep(self, value: bool) -> None:
        """Set the sleep mode state."""
        self._set_device_status(
            {
                GreeProp.FEAT_SLEEP_MODE: 1 if value else 0,
                GreeProp.FEAT_SLEEP_MODE_SWING: 1 if value else 0,
            }
        )

    @property
    def feature_light(self) -> bool:
        """Return the light state."""
        return self._bool_from_raw_state(GreeProp.FEAT_LIGHT)

    def set_feature_light(self, value: bool) -> None:
        """Set the light state."""
        self._set_device_status({GreeProp.FEAT_LIGHT: 1 if value else 0})

    @property
    def feature_quiet(self) -> bool:
        """Return the quiet mode state."""
        return self._bool_from_raw_state(GreeProp.FEAT_QUIET_MODE)

    def set_feature_quiet(self, value: bool) -> None:
        """Set the quiet mode state."""
        self._set_device_status({GreeProp.FEAT_QUIET_MODE: 1 if value else 0})

    @property
    def feature_turbo(self) -> bool:
        """Return the turbo mode state."""
        return self._bool_from_raw_state(GreeProp.FEAT_TURBO_MODE)

    def set_feature_turbo(self, value: bool) -> None:
        """Set the turbo mode state."""
        self._set_device_status({GreeProp.FEAT_TURBO_MODE: 1 if value else 0})

    @property
    def feature_smart_heat(self) -> bool:
        """Return the smart heat (8ºC / anti-freeze) mode state."""
        return self._bool_from_raw_state(GreeProp.FEAT_SMART_HEAT_8C)

    def set_feature_smart_heat(self, value: bool) -> None:
        """Set the smart heat (8ºC / anti-freeze) mode state."""
        self._set_device_status({GreeProp.FEAT_SMART_HEAT_8C: 1 if value else 0})

    @property
    def feature_energy_saving(self) -> bool:
        """Return the energy saving mode state."""
        return self._bool_from_raw_state(GreeProp.FEAT_ENERGY_SAVING)

    def set_feature_energy_saving(self, value: bool) -> None:
        """Set the energy saving mode state."""
        self._set_device_status({GreeProp.FEAT_ENERGY_SAVING: 1 if value else 0})

    @property
    def feature_anti_direct_blow(self) -> bool:
        """Return the anti direct blow mode state."""
        return self._bool_from_raw_state(GreeProp.FEAT_ANTI_DIRECT_BLOW)

    def set_feature_anti_direct_blow(self, value: bool) -> None:
        """Set the anti direct blow mode state."""
        self._set_device_status({GreeProp.FEAT_ANTI_DIRECT_BLOW: 1 if value else 0})
