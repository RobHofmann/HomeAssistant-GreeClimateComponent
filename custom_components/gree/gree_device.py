"""Contains the API to interface with the Gree device."""

import logging

from attr import dataclass

from .gree_api import (
    FanSpeed,
    GreeProp,
    HorizontalSwingMode,
    OperationMode,
    TemperatureUnits,
    VerticalSwingMode,
    gree_get_device_key,
    gree_get_status,
    gree_set_status,
)
from .gree_const import DEFAULT_UID
from .gree_helpers import (
    TempOffsetResolver,
    gree_get_target_temp_props_from_c,
    gree_get_target_temp_props_from_f,
    gree_get_target_temperature_c,
    gree_get_target_temperature_f,
)

_LOGGER = logging.getLogger(__name__)


class GreeDeviceNotBoundError(Exception):
    """Raised when the device binding fails."""


@dataclass
class GreeDeviceState:
    """Data structure for Gree device state."""

    power: bool = False
    operation_mode: OperationMode = OperationMode.Auto
    fan_speed: FanSpeed = FanSpeed.Auto
    target_temperature: float = -1
    target_temperature_unit: TemperatureUnits = TemperatureUnits.C
    horizontal_swing_mode: HorizontalSwingMode = HorizontalSwingMode.Default
    vertical_swing_mode: VerticalSwingMode = VerticalSwingMode.Default
    feature_fresh_air: bool = False
    feature_x_fan: bool = False
    feature_health: bool = False
    feature_sleep: bool = False
    feature_light: bool = False
    feature_light_sensor: bool = False
    feature_quiet: bool = False
    feature_turbo: bool = False
    feature_smart_heat: bool = False
    feature_energy_saving: bool = False
    feature_anti_direct_blow: bool = False
    has_indoor_temperature_sensor: bool = False
    indoors_temperature_c: int | None = None
    has_outdoor_temperature_sensor: bool = False
    outdoors_temperature_c: int | None = None
    has_humidity_sensor: bool = False
    humidity: int | None = None
    has_light_sensor: bool = False


class GreeDevice:
    """Representation of a Gree device."""

    def __init__(
        self,
        name: str,
        ip_addr: str,
        mac_addr: str,
        port: int,
        encryption_version: int,
        encryption_key: str,
        uid: int = DEFAULT_UID,
        max_connection_attempts: int = 8,
    ) -> None:
        """Initialize the Gree device."""

        _LOGGER.info(
            "Initialize the GREE Device API for: %s (%s:%d)",
            mac_addr,
            ip_addr,
            port,
        )
        _LOGGER.debug("Version: %s, Key: %s", encryption_version, encryption_key)

        self._name: str = name
        self._ip_addr: str = ip_addr
        self._port: int = port
        self._mac_addr = self._mac_addr_sub = mac_addr.lower()
        if "@" in mac_addr:
            self._mac_addr_sub, self._mac_addr = mac_addr.lower().split("@", 1)
        self._encryption_version: int = encryption_version
        self._encryption_key: str = encryption_key
        self._uid: int = uid
        self._state: dict[GreeProp, int] = {}
        self._new_state: dict[GreeProp, int] = {}
        self._is_bound: bool = False
        self._uniqueid: str = self._mac_addr
        self._max_connection_attempts: int = max_connection_attempts

        self._props_to_update: list[GreeProp] = list(GreeProp)
        self._props_to_update.remove(
            GreeProp.BEEPER  # We don't need to poll the beeper state
        )

        self._temp_processor_indoors: TempOffsetResolver | None = None
        self._temp_processor_outdoors: TempOffsetResolver | None = None
        self._beeper = False

        self.state: GreeDeviceState = GreeDeviceState()

        if encryption_version < 0 or encryption_version > 2:
            _LOGGER.error("Unsupported encryption version, defaulting to 0")
            self._encryption_version = 0

    async def bind_device(self) -> bool:
        """Setup the device (async)."""

        if not self._is_bound:
            if not self._encryption_key.strip():
                _LOGGER.info("No encryption key provided")
                try:
                    (
                        self._encryption_key,
                        self._encryption_version,
                    ) = await gree_get_device_key(
                        self._ip_addr,
                        self._mac_addr,
                        self._port,
                        self._uid,
                        self._encryption_version,
                        max_connection_attempts=self._max_connection_attempts,
                    )
                    self._is_bound = True
                except Exception as e:
                    raise GreeDeviceNotBoundError("Device not bound") from e
            else:
                _LOGGER.info(
                    "Using the provided encryption key with version %d",
                    self._encryption_version,
                )
                self._is_bound = True

        return self._is_bound

    async def fetch_device_status(self) -> GreeDeviceState:
        """Get the device status (async)."""

        _LOGGER.debug("Trying to get device status")

        if not self._is_bound:
            await self.bind_device()

        try:
            self._state.update(
                await gree_get_status(
                    self._ip_addr,
                    self._mac_addr,
                    self._port,
                    self._uid,
                    self._encryption_key,
                    self._encryption_version,
                    self._props_to_update,
                )
            )
        except Exception as err:
            raise ValueError("Error getting device status") from err

        self._update_state()

        self._remove_unsupported_props()

        return self.state

    async def update_device_status(self) -> GreeDeviceState:
        """Send the new local device state to the device and updates local state if successfull."""
        if not self._is_bound:
            await self.bind_device()

        # If there is no change in the properties, do nothing
        has_updated_states = any(
            self._state.get(k) != v for k, v in self._new_state.items()
        )
        if not has_updated_states:
            _LOGGER.debug("No changes in the properties, skipping update to device")
            return self.state

        self._new_state[GreeProp.BEEPER] = 0 if self._beeper else 1

        try:
            self._state.update(
                await gree_set_status(
                    self._ip_addr,
                    self._mac_addr,
                    self._port,
                    self._uid,
                    self._encryption_key,
                    self._encryption_version,
                    self._new_state,
                )
            )
            self._new_state.clear()
        except Exception as err:
            raise ValueError("Error setting device status") from err

        self._update_state()
        return self.state

    def set_device_status(self, props: dict[GreeProp, int]) -> None:
        """Sets a new local device status. Use 'update_device_status' to update the device."""
        self._new_state.update(props)

    def _update_state(self) -> None:
        """Update the state from the internal state."""

        self.state.power = self.power_mode
        self.state.operation_mode = self.operation_mode
        self.state.fan_speed = self.fan_speed
        self.state.target_temperature = self.target_temperature
        self.state.target_temperature_unit = self.target_temperature_unit
        self.state.horizontal_swing_mode = self.horizontal_swing_mode
        self.state.vertical_swing_mode = self.vertical_swing_mode
        self.state.feature_fresh_air = self.feature_fresh_air
        self.state.feature_x_fan = self.feature_x_fan
        self.state.feature_health = self.feature_health
        self.state.feature_sleep = self.feature_sleep
        self.state.feature_light = self.feature_light
        self.state.feature_light_sensor = self.feature_light_sensor
        self.state.feature_quiet = self.feature_quiet
        self.state.feature_turbo = self.feature_turbo
        self.state.feature_smart_heat = self.feature_smart_heat
        self.state.feature_energy_saving = self.feature_energy_saving
        self.state.feature_anti_direct_blow = self.feature_anti_direct_blow
        self.state.has_indoor_temperature_sensor = self.has_indoor_temperature_sensor
        self.state.indoors_temperature_c = self.indoors_temperature_c
        self.state.has_outdoor_temperature_sensor = self.has_outdoor_temperature_sensor
        self.state.outdoors_temperature_c = self.outdoors_temperature_c
        self.state.has_humidity_sensor = self.has_humidity_sensor
        self.state.humidity = self.humidity

    def _remove_unsupported_props(self):
        """Remove unsupported properties from the list to update."""
        if (
            GreeProp.SENSOR_TEMPERATURE in self._props_to_update
            and not self.has_indoor_temperature_sensor
        ):
            self._props_to_update.remove(GreeProp.SENSOR_TEMPERATURE)
            self._state.pop(GreeProp.SENSOR_TEMPERATURE, None)
            _LOGGER.debug("No longer updating temperature sensor property")

        if (
            GreeProp.SENSOR_OUTSIDE_TEMPERATURE in self._props_to_update
            and not self.has_outdoor_temperature_sensor
        ):
            self._props_to_update.remove(GreeProp.SENSOR_OUTSIDE_TEMPERATURE)
            self._state.pop(GreeProp.SENSOR_OUTSIDE_TEMPERATURE, None)
            _LOGGER.debug("No longer updating outside temperature sensor property")

        if (
            GreeProp.SENSOR_HUMIDITY in self._props_to_update
            and not self.has_humidity_sensor
        ):
            self._props_to_update.remove(GreeProp.SENSOR_HUMIDITY)
            self._state.pop(GreeProp.SENSOR_HUMIDITY, None)
            _LOGGER.debug("No longer updating humidity sensor property")

    def _get_prop_raw(self, prop: GreeProp, default: int | None = None) -> int | None:
        """Get the raw value of a property."""
        return self._state.get(prop, default)

    def LogDeviceInfo(self):
        """Log basic device information."""

        capabilities = []
        if self.has_indoor_temperature_sensor:
            capabilities.append("Temperature Sensor")
        if self.has_outdoor_temperature_sensor:
            capabilities.append("Outside Temperature Sensor")
        if self.has_humidity_sensor:
            capabilities.append("Humidity Sensor")

        _LOGGER.info(
            "Capabilities: %s", ", ".join(capabilities) if capabilities else "None"
        )

        _LOGGER.info(
            "Indoor Temperature: %s ºC",
            self.indoors_temperature_c if self.has_indoor_temperature_sensor else None,
        )
        _LOGGER.info(
            "Outddor Temperature: %s ºC",
            self.indoors_temperature_c if self.has_indoor_temperature_sensor else None,
        )
        _LOGGER.info(
            "Target Temperature: %s º%s",
            self.target_temperature,
            self.target_temperature_unit.name,
        )
        _LOGGER.info("Mode: %s", self.operation_mode.name)

    @property
    def name(self) -> str:
        """Returns the friendly name of the device."""
        return self._name

    @property
    def encryption_key(self) -> str:
        """Return the encryption key of the device."""
        return self._encryption_key

    @property
    def encryption_version(self) -> int:
        """Return the encryption version of the device."""
        return self._encryption_version

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the device (MAC)."""
        return self._uniqueid

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return bool(self._is_bound)

    @property
    def beeper(self) -> bool:
        """Return True if the device beeper is enabled."""
        return self._beeper

    def set_beeper(self, value: bool) -> None:
        """Set the device beeper state."""
        self._beeper = value

    @property
    def has_indoor_temperature_sensor(self) -> bool:
        """Return True if the device has a temperature sensor."""
        return (
            GreeProp.SENSOR_TEMPERATURE in self._state
            and self._get_prop_raw(GreeProp.SENSOR_TEMPERATURE, 0) != 0
        )

    @property
    def has_outdoor_temperature_sensor(self) -> bool:
        """Return True if the device has an outdoor temperature sensor."""
        return (
            GreeProp.SENSOR_OUTSIDE_TEMPERATURE in self._state
            and self._get_prop_raw(GreeProp.SENSOR_OUTSIDE_TEMPERATURE, 0) != 0
        )

    @property
    def has_humidity_sensor(self) -> bool:
        """Return True if the device has an humidity sensor."""
        return (
            GreeProp.SENSOR_HUMIDITY in self._state
            and self._get_prop_raw(GreeProp.SENSOR_HUMIDITY, 0) != 0
        )

    @property
    def indoors_temperature_c(self) -> int | None:
        """Return the current temperature if available."""
        if self.has_indoor_temperature_sensor:
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
        if self.has_outdoor_temperature_sensor:
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
        if self.has_humidity_sensor:
            return self._get_prop_raw(GreeProp.SENSOR_HUMIDITY, None)
        return None

    @property
    def power_mode(self) -> bool:
        """Return the current power mode."""
        return self._get_prop_raw(GreeProp.POWER, 0) == 1

    def set_power_mode(self, value: bool):
        """Sets the device power mode."""
        self.set_device_status({GreeProp.POWER: 1 if value else 0})

    @property
    def operation_mode(self) -> OperationMode:
        """Return the current operation mode."""
        return OperationMode(
            self._get_prop_raw(GreeProp.OP_MODE, OperationMode.Auto.value)
        )

    def set_operation_mode(self, mode: OperationMode):
        """Sets the device operation mode."""
        self.set_device_status({GreeProp.OP_MODE: mode})

    @property
    def fan_speed(self) -> FanSpeed:
        """Return the current fan speed."""
        return FanSpeed(self._get_prop_raw(GreeProp.FAN_SPEED, FanSpeed.Auto.value))

    def set_fan_speed(self, speed: FanSpeed):
        """Sets the device fan speed mode."""
        self.set_device_status({GreeProp.FAN_SPEED: speed})

    @property
    def vertical_swing_mode(self) -> VerticalSwingMode:
        """Return the current vertical swing setting."""
        return VerticalSwingMode(
            self._get_prop_raw(GreeProp.SWING_VERTICAL, VerticalSwingMode.Default.value)
        )

    def set_vertical_swing_mode(self, swing_mode: VerticalSwingMode):
        """Sets the device vertical swing mode."""
        self.set_device_status({GreeProp.SWING_VERTICAL: swing_mode})

    @property
    def horizontal_swing_mode(self) -> HorizontalSwingMode:
        """Return the current horizontal swing setting."""
        return HorizontalSwingMode(
            self._get_prop_raw(
                GreeProp.SWING_HORIZONTAL, HorizontalSwingMode.Default.value
            )
        )

    def set_horizontal_swing_mode(self, swing_mode: HorizontalSwingMode):
        """Sets the device horizontal swing mode."""
        self.set_device_status({GreeProp.SWING_HORIZONTAL: swing_mode})

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
        self.set_device_status({GreeProp.TARGET_TEMPERATURE_UNIT: units})

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
            raw_c, tem_rec = gree_get_target_temp_props_from_f(value)
        else:
            raw_c, tem_rec = gree_get_target_temp_props_from_c(value)

        self.set_device_status(
            {
                GreeProp.TARGET_TEMPERATURE: raw_c,
                GreeProp.TARGET_TEMPERATURE_BIT: tem_rec,
            }
        )

    @property
    def feature_light_sensor(self) -> bool:
        """Return the light sensor state."""
        return self._get_prop_raw(GreeProp.FEAT_SENSOR_LIGHT, 0) != 0

    def set_feature_light_sensor(self, value: bool) -> None:
        """Set the light sensor state."""
        self.set_device_status({GreeProp.FEAT_SENSOR_LIGHT: 1 if value else 0})

    @property
    def feature_fresh_air(self) -> bool:
        """Return the fresh air mode state."""
        return self._get_prop_raw(GreeProp.FEAT_FRESH_AIR, 0) == 1

    def set_feature_fresh_air(self, value: bool) -> None:
        """Set the fresh air mode state."""
        self.set_device_status({GreeProp.FEAT_FRESH_AIR: 1 if value else 0})

    @property
    def feature_x_fan(self) -> bool:
        """Return the x-fan mode state."""
        return self._get_prop_raw(GreeProp.FEAT_XFAN, 0) == 1

    def set_feature_xfan(self, value: bool) -> None:
        """Set the x-fan mode state."""
        self.set_device_status({GreeProp.FEAT_XFAN: 1 if value else 0})

    @property
    def feature_health(self) -> bool:
        """Return the health mode state."""
        return self._get_prop_raw(GreeProp.FEAT_HEALTH, 0) == 1

    def set_feature_health(self, value: bool) -> None:
        """Set the health mode state."""
        self.set_device_status({GreeProp.FEAT_HEALTH: 1 if value else 0})

    @property
    def feature_sleep(self) -> bool:
        """Return the sleep mode state."""
        return (
            self._get_prop_raw(GreeProp.FEAT_SLEEP_MODE_SWING, 0) == 1
            or self._get_prop_raw(GreeProp.FEAT_SLEEP_MODE, 0) == 1
        )

    def set_feature_sleep(self, value: bool) -> None:
        """Set the sleep mode state."""
        self.set_device_status(
            {
                GreeProp.FEAT_SLEEP_MODE: 1 if value else 0,
                GreeProp.FEAT_SLEEP_MODE_SWING: 1 if value else 0,
            }
        )

    @property
    def feature_light(self) -> bool:
        """Return the light state."""
        return self._get_prop_raw(GreeProp.FEAT_LIGHT, 0) == 1

    def set_feature_light(self, value: bool) -> None:
        """Set the light state."""
        self.set_device_status({GreeProp.FEAT_LIGHT: 1 if value else 0})

    @property
    def feature_quiet(self) -> bool:
        """Return the quiet mode state."""
        return self._get_prop_raw(GreeProp.FEAT_QUIET_MODE, 0) == 1

    def set_feature_quiet(self, value: bool) -> None:
        """Set the quiet mode state."""
        self.set_device_status({GreeProp.FEAT_QUIET_MODE: 1 if value else 0})

    @property
    def feature_turbo(self) -> bool:
        """Return the turbo mode state."""
        return self._get_prop_raw(GreeProp.FEAT_TURBO_MODE, 0) == 1

    def set_feature_turbo(self, value: bool) -> None:
        """Set the turbo mode state."""
        self.set_device_status({GreeProp.FEAT_TURBO_MODE: 1 if value else 0})

    @property
    def feature_smart_heat(self) -> bool:
        """Return the smart heat (8ºC / anti-freeze) mode state."""
        return self._get_prop_raw(GreeProp.FEAT_SMART_HEAT_8C, 0) == 1

    def set_feature_smart_heat(self, value: bool) -> None:
        """Set the smart heat (8ºC / anti-freeze) mode state."""
        self.set_device_status({GreeProp.FEAT_SMART_HEAT_8C: 1 if value else 0})

    @property
    def feature_energy_saving(self) -> bool:
        """Return the energy saving mode state."""
        return self._get_prop_raw(GreeProp.FEAT_ENERGY_SAVING, 0) == 1

    def set_feature_energy_saving(self, value: bool) -> None:
        """Set the energy saving mode state."""
        self.set_device_status({GreeProp.FEAT_ENERGY_SAVING: 1 if value else 0})

    @property
    def feature_anti_direct_blow(self) -> bool:
        """Return the anti direct blow mode state."""
        return self._get_prop_raw(GreeProp.FEAT_ANTI_DIRECT_BLOW, None) == 1

    def set_feature_anti_direct_blow(self, value: bool) -> None:
        """Set the anti direct blow mode state."""
        self.set_device_status({GreeProp.FEAT_ANTI_DIRECT_BLOW: 1 if value else 0})
