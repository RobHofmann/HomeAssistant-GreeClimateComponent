"""Contains the API to interface with the Gree device."""

from collections.abc import Mapping
import logging
from typing import Any

from packaging.version import Version

from .api import (
    EncryptionVersion,
    FanSpeed,
    GreeProp,
    HorizontalSwingMode,
    HumidityControlMode,
    InfoProp,
    OperationMode,
    SleepMode,
    TemperatureUnits,
    VerticalSwingMode,
    extract_fw_version,
)
from .cloud_api import FirmwareInfoResponse, GreeRegion, gree_get_latest_firmware_info
from .const import (
    DEFAULT_DEVICE_USERID,
    MAX_HUM_COOL_P,
    MAX_HUM_DRY_P,
    MIN_HUM_COOL_P,
    MIN_HUM_DRY_P,
)
from .device_api_client import DeviceApiClient
from .device_state import DeviceState
from .errors import (
    GreeBindingError,
    GreeConnectionError,
    GreeContinuousDryUnavailable,
    GreeEnergySavingUnavailable,
    GreeError,
    GreeHumidityControlTargetUnavailable,
    GreeHumidityControlUnavailable,
    GreeProtocolError,
    GreeSleepUnavailable,
    GreeSmartDryUnavailable,
    GreeSmartHeatUnavailable,
    GreeTurboUnavailable,
)
from .helpers import (
    TempOffsetResolver,
    gree_get_target_humidity_p,
    gree_get_target_humidity_prop_from_p,
    gree_get_target_temp_props_from_c,
    gree_get_target_temp_props_from_f,
    gree_get_target_temperature_c,
    gree_get_target_temperature_f,
    redact_str,
)
from .transport import GreeBaseTransport
from .transport_mqtt import GreeMqttTransport
from .transport_udp import GreeUdpTransport

_LOGGER = logging.getLogger(__name__)


class GreeDevice:
    """Representation of a Gree device."""

    def __init__(
        self,
        name: str,
        mac_addr: str,
        preferred_encryption_key: str | None = None,
        user_id: int = DEFAULT_DEVICE_USERID,
        capabilities: list[GreeProp] | None = None,
    ) -> None:
        """Initialize the Gree device."""

        _LOGGER.info(
            "[%s] Initializing the GREE Device API",
            mac_addr,
        )

        self._name: str = name

        self._mac_addr = mac_addr

        self._preferred_encryption_key: str | None = preferred_encryption_key

        self._capabilities: list[GreeProp] = capabilities or list(GreeProp)

        self._temp_processor_indoors: TempOffsetResolver | None = None
        self._temp_processor_outdoors: TempOffsetResolver | None = None
        self._beeper = False

        self._firmware_version: str | None = None
        self._firmware_code: str | None = None
        self._firmware_protocol_version: str = ""

        self._state = DeviceState(
            device_id=self.unique_id, capabilities=self._capabilities
        )

        self._client = DeviceApiClient(
            mac=self._mac_addr,
            userid=user_id,
        )

    async def bind_with_transport(
        self,
        preferred_local_version: EncryptionVersion | None = None,
        local_controller_mac: str | None = None,
        local_transport: GreeUdpTransport | None = None,
        mqtt_controller_mac: str | None = None,
        mqtt_transport: GreeMqttTransport | None = None,
    ) -> None:
        """Bind the device to a new transport. It will try local transport first and then MQTT."""
        await self._client.unbind()

        if not local_transport and not mqtt_transport:
            raise GreeBindingError(
                f"No transport provided for {self._mac_addr} to bind with"
            )

        attempts: list[tuple[GreeBaseTransport, str, EncryptionVersion | None]] = []

        if local_transport:
            if not local_controller_mac:
                _LOGGER.error("No controller MAC provided for local transport")
            else:
                attempts.append(
                    (local_transport, local_controller_mac, preferred_local_version)
                )

        if mqtt_transport:
            if not mqtt_controller_mac:
                _LOGGER.error("No controller MAC provided for MQTT transport")
            else:
                attempts.append(
                    (mqtt_transport, mqtt_controller_mac, EncryptionVersion.V1)
                )

        error: Exception | None = None
        for transport, mac_controller, version in attempts:
            await self._client.set_transport(transport)
            try:
                await self._client.bind(
                    controller_mac=mac_controller,
                    preferred_version=version,
                    preferred_key=self._preferred_encryption_key,
                )

            except GreeError as err:
                error = err
                await self._client.unbind()
                _LOGGER.warning(
                    "[%s] Failed binding via %s",
                    self.unique_id,
                    transport,
                    exc_info=True,
                )
            else:
                # Fetch initial information after sucessful bind
                await self.fetch_device_info()
                await self.fetch_device_status()
                self._remove_unsupported_props()
                return

        raise GreeBindingError(
            f"Could not perform binding with {self._mac_addr} with any transport"
        ) from error

    async def unbind_device(self) -> None:
        """Properly disconnect the device from transport."""
        if not self._client.bound:
            return

        try:
            await self._client.unbind()
        except GreeConnectionError:
            raise

        except Exception as err:
            raise GreeBindingError(
                f"Problem unbinding {self._mac_addr} in {self.transport}"
            ) from err

    async def fetch_device_info(self) -> None:
        """Update the device info state fields."""

        _LOGGER.debug(
            "[%s:%s] Trying to get device info",
            self.unique_id,
            self.transport,
        )

        try:
            props = [prop.value for prop in InfoProp]
            raw_info, _ = await self._client.query_props(props, len(props))

        except GreeConnectionError, GreeProtocolError:
            _LOGGER.exception(
                "[%s:%s] Failed fetching device device info",
                self.unique_id,
                self.transport,
            )
            raise

        except Exception as err:
            _LOGGER.exception(
                "[%s:%s] Failed fetching device device info",
                self.unique_id,
                self.transport,
            )
            raise GreeProtocolError(
                f"Failed fetching device info for {self._mac_addr} via {self.transport}"
            ) from err

        else:
            _LOGGER.debug(
                "[%s:%s] Got device info: %s", self.unique_id, self.transport, raw_info
            )

            self._state.process_new_state(raw_info)

            _LOGGER.debug(self._state.info)

            self._firmware_protocol_version = self._state.info.get(
                InfoProp.PROTOCOL_VERSION, ""
            ).lstrip("V")

            self._firmware_version, self._firmware_code = extract_fw_version(
                self._state.info.get(InfoProp.HID, "")
            )

    async def fetch_device_status(self) -> None:
        """Get the device status (async)."""
        _LOGGER.debug(
            "[%s:%s] Trying to get status",
            self.unique_id,
            self.transport,
        )

        try:
            status, _ = await self._client.query_props(
                [prop.value for prop in self._state.polled_properties],
                len(self._state.polled_properties),
            )

            _LOGGER.debug(
                "[%s:%s] Got device status: %s", self.unique_id, self.transport, status
            )

            self._state.process_new_state(status)

        except GreeConnectionError, GreeProtocolError:
            _LOGGER.exception(
                "[%s:%s] Failed fetching device device status",
                self.unique_id,
                self.transport,
            )
            raise

        except Exception as err:
            _LOGGER.exception(
                "[%s:%s] Failed fetching device device status",
                self.unique_id,
                self.transport,
            )
            raise GreeError(f"Error getting {self._mac_addr} status") from err

    async def push_device_status(self) -> None:
        """Send the new local device state to the device and updates local state if successfull."""

        _LOGGER.debug(
            "[%s:%s] Trying to set status",
            self.unique_id,
            self.transport,
        )

        # If there is no change in the properties, do nothing
        if not self._state.has_pending_updates:
            _LOGGER.info(
                "[%s] No changes in properties, skipping update to device",
                self.unique_id,
            )
            self._state.clear_pending()
            return

        # Theoretically, the device saves the beeper value when the property is sent with others,
        # however remote commands overwrite the value to enable the beeper, so here we force our state
        self._state.set(GreeProp.BEEPER, 0 if self._beeper else 1)
        self._state.set(GreeProp.BEEPER_NEW, 1 if self._beeper else 0)

        try:
            await self._client.set_props(
                {k.value: v for k, v in self._state.pending.items()}
            )

            _LOGGER.debug("[%s:%s] Device status set", self.unique_id, self.transport)
            self._state.clear_pending()

            await self.fetch_device_status()

        except GreeConnectionError, GreeProtocolError:
            _LOGGER.exception(
                "[%s:%s] Failed pushing device device status",
                self.unique_id,
                self.transport,
            )
            raise

        except Exception as err:
            _LOGGER.exception(
                "[%s:%s] Failed pushing device device status",
                self.unique_id,
                self.transport,
            )
            raise GreeError(f"Error setting device {self._mac_addr} status") from err

    def _remove_unsupported_props(self) -> None:
        """Remove unsupported properties from the list to update."""

        # Remove all unsupported properties
        self._state.invalidate_missing_properties()

        # Sensors should also be invalidated if their values are not expected (=0)
        self._state.invalidate_missing_property_group(
            [
                GreeProp.SENSOR_INDOOR_TEMPERATURE_1,
                GreeProp.SENSOR_INDOOR_TEMPERATURE_2,
                GreeProp.SENSOR_INDOOR_TEMPERATURE_3,
            ]
        )

        self._state.invalidate_missing_property_group(
            [
                GreeProp.SENSOR_OUTSIDE_TEMPERATURE_1,
                GreeProp.SENSOR_OUTSIDE_TEMPERATURE_2,
            ]
        )

        self._state.invalidate_missing_property_group(
            [
                GreeProp.SENSOR_HUMIDITY_1,
                GreeProp.SENSOR_HUMIDITY_2,
            ]
        )

        # As far as it is known, both values at 0 is not a valid combination.
        if (
            GreeProp.FEATURE_HUMIDITY_CONTROL in self._state.polled_properties
            and self._state.get(GreeProp.FEATURE_HUMIDITY_CONTROL, 0) == 0
            and self._state.get(GreeProp.FEATURE_HUMIDITY_TARGET, 0) == 0
        ):
            self._state.remove(GreeProp.FEATURE_HUMIDITY_CONTROL)
            self._state.remove(GreeProp.FEATURE_HUMIDITY_TARGET)

    def gather_diagnostics(self) -> dict[str, Any]:
        """Return diagnostic info for the device."""
        data: dict[str, Any] = {}

        info = {
            "transport": str(self._client.transport),
            "mac": self.mac_address,
            "mac_controller": self.mac_address_controller,
            "name": self.name,
            "fw": self.firmware_version,
            "is_bound": self._client.bound,
            "is_available": self._client.available,
            "beeper": self.beeper,
            "encryption": str(self._client.encryption_version),
            "key": redact_str(self._client.encryption_key),
        }

        data["info"] = info
        data["state_info"] = dict(self._state.info)
        data["state"] = {str(k): v for k, v in self._state.raw.items()}
        data["state_pending"] = {str(k): v for k, v in self._state.pending.items()}

        return data

    async def query_props(
        self, props: list[str], request_batch: int = 1, error_as_missing: bool = False
    ) -> tuple[dict[str, str], list[str]]:
        """Query the value of the given props."""
        return await self._client.query_props(props, request_batch, error_as_missing)

    async def query_props_all(
        self, request_batch: int = 1, error_as_missing: bool = False
    ) -> tuple[dict[str, str], list[str]]:
        """Query all possible props."""
        return await self._client.query_all_props(request_batch, error_as_missing)

    async def set_props(self, values: Mapping[str, int]) -> None:
        """Allow setting generic property value set to the device.

        Caution: Don't set random property status.
        """
        return await self._client.set_props(values)

    def supports_property(self, property: GreeProp) -> bool:
        """Return True if the device endpoint supports the property."""
        # We consider a property as unsupported if it is not present in the raw state list
        # This assumes that the full state is fetched at least once before this method is called
        return self._state.supports(property)

    async def check_fw_updates(self) -> tuple[bool, FirmwareInfoResponse | None]:
        """Check for device updates. Returns the latest firmware info if possible."""
        if not self._firmware_code:
            _LOGGER.error(
                "Unable to retrieve firmware because firmware code is unknown"
            )
            return False, None

        latest_fw = await gree_get_latest_firmware_info(
            GreeRegion.EU, self._firmware_code
        )

        if not latest_fw:
            _LOGGER.error("Unable to retrieve firmware because of a bad server request")
            return False, None

        if not self._firmware_version:
            _LOGGER.error(
                "Unable to assess because current firmware version is unknown"
            )
            return False, latest_fw

        if not latest_fw.version:
            _LOGGER.error("Unable to assess because latest firmware version is unknown")
            return False, latest_fw

        return Version(self._firmware_version) < Version(latest_fw.version), latest_fw

    @property
    def transport(self) -> GreeBaseTransport | None:
        """The Transport assigned to the device."""
        return self._client.transport

    async def set_transport(self, transport: GreeBaseTransport) -> None:
        """Update the transport used by the device for communication."""
        await self._client.set_transport(transport)
        await self._client.rebind()

    @property
    def api_client(self) -> DeviceApiClient:
        """Clinet to interface with the device API."""
        return self._client

    @property
    def name(self) -> str:
        """Friendly name of the device."""
        return self._name

    @property
    def encryption_key(self) -> str | None:
        """Encryption key of the device."""
        return self._client.encryption_key

    @property
    def encryption_version(self) -> EncryptionVersion | None:
        """Return the encryption version of the device."""
        return self._client.encryption_version

    @property
    def unique_id(self) -> str:
        """Return the unique ID of the device (MAC)."""
        return self._mac_addr

    @property
    def mac_address(self) -> str:
        """Return the main MAC address of the device."""
        return self._mac_addr

    @property
    def mac_address_controller(self) -> str:
        """Return the secondary MAC address of the device. For non VRF is the same as MAC otherwise is the MAC of the main controller (same as MAC for the main device)."""
        return self._client.controller_mac

    @property
    def firmware_version(self) -> str | None:
        """Returns the firmware version."""
        fw_str = ""

        if self._firmware_version:
            fw_str += f"{self._firmware_version} "

        if self._firmware_protocol_version.strip():
            fw_str += f"(Protocol: {self._firmware_protocol_version}) "

        return fw_str.strip() or None

    @property
    def firmware_code(self) -> str | None:
        "Code for the firmware WIFI module."
        code: str = self._firmware_code or ""
        if isinstance(self.transport, GreeUdpTransport):
            code += " (UDP)"
        else:
            code += " (MQTT)"
        return code.strip()

    @property
    def device_model_id(self) -> str | None:
        """The model of the unit."""
        mt = self._state.info.get(InfoProp.MODEL_TYPE, "")
        v = self._state.info.get(InfoProp.VENDER, "")
        model = ""
        if mt.strip():
            model += mt
        if v.strip() and model.strip():
            model += f" ({v})"
        return model

    @property
    def available(self) -> bool:
        """Return True if the device is bound and last connection was successful."""
        return self._client.bound and self._client.available

    @property
    def is_bound(self) -> bool:
        """Return True if the device is bound."""
        return self._client.bound

    @property
    def has_hvac_error(self) -> bool:
        """Return if there is an error with the device."""
        return self._state.get_bool(GreeProp.SENSOR_FAULT)

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
        if self._temp_processor_indoors is None:
            self._temp_processor_indoors = TempOffsetResolver()

        for prop in (
            GreeProp.SENSOR_INDOOR_TEMPERATURE_1,
            GreeProp.SENSOR_INDOOR_TEMPERATURE_2,
            GreeProp.SENSOR_INDOOR_TEMPERATURE_3,
        ):
            if self._state.supports(prop):
                raw_c = self._state.get(prop, None)
                return (
                    int(self._temp_processor_indoors.evaluate(raw_c))
                    if raw_c is not None
                    else None
                )

        return None

    @property
    def outdoors_temperature_c(self) -> int | None:
        """Return the current outside temperature if available."""

        if self._temp_processor_outdoors is None:
            self._temp_processor_outdoors = TempOffsetResolver()

        for prop in (
            GreeProp.SENSOR_OUTSIDE_TEMPERATURE_1,
            GreeProp.SENSOR_OUTSIDE_TEMPERATURE_2,
        ):
            if self._state.supports(prop):
                raw_c = self._state.get(prop, None)
                return (
                    int(self._temp_processor_outdoors.evaluate(raw_c))
                    if raw_c is not None
                    else None
                )

        return None

    @property
    def humidity(self) -> int | None:
        """Return the current humidity if available."""

        for prop in (
            GreeProp.SENSOR_HUMIDITY_1,
            GreeProp.SENSOR_HUMIDITY_2,
        ):
            if self._state.supports(prop):
                return self._state.get(prop, None)

        return None

    @property
    def power_mode(self) -> bool:
        """Return the current power mode."""
        return self._state.get_bool(GreeProp.POWER)

    def set_power_mode(self, value: bool) -> None:
        """Set the device power mode."""
        self._state.set_bool(GreeProp.POWER, value)

    @property
    def operation_mode(self) -> OperationMode:
        """Return the current operation mode."""
        return OperationMode(
            self._state.get(GreeProp.OP_MODE) or OperationMode.auto.value
        )

    def set_operation_mode(self, mode: OperationMode) -> None:
        """Set the device operation mode."""

        # Force disable Humidity Control
        if self.feature_humidity_control != HumidityControlMode.disabled:
            _LOGGER.info(
                "[%s] Humidity control disabled due to operation mode change to %s",
                self.unique_id,
                mode,
            )
            self.set_feature_humidity_control(HumidityControlMode.disabled)

        # Disable Energy Saver when changing to modes that are not Cool
        if mode != OperationMode.cool and self.feature_energy_saving:
            self.set_feature_energy_saving(False)

        # Disable Smart Heat when changing to modes that are not Hear
        if mode != OperationMode.heat and self.feature_smart_heat:
            self.set_feature_smart_heat(False)

        self._state.set(GreeProp.OP_MODE, mode)

    @property
    def fan_speed(self) -> FanSpeed:
        """Return the current fan speed."""
        return FanSpeed(self._state.get(GreeProp.FAN_SPEED) or FanSpeed.auto.value)

    def set_fan_speed(self, speed: FanSpeed) -> None:
        """Set the device fan speed mode.

        Setting a fan speed other than 'Auto' will deactivate Energy Saving and Smart Heat features.
        """

        if speed is not FanSpeed.auto and self.feature_energy_saving:
            self.set_feature_energy_saving(False)
            _LOGGER.info(
                "[%s] Energy saving mode disabled because of fan mode setting",
                self.unique_id,
            )

        if speed is not FanSpeed.auto and self.feature_smart_heat:
            self.set_feature_smart_heat(False)
            _LOGGER.info(
                "[%s] Smart Heat mode disabled because of fan mode setting",
                self.unique_id,
            )

        self._state.set(GreeProp.FAN_SPEED, speed)

    @property
    def vertical_swing_mode(self) -> VerticalSwingMode:
        """Return the current vertical swing setting."""
        return VerticalSwingMode(
            self._state.get(GreeProp.SWING_VERTICAL) or VerticalSwingMode.default.value
        )

    def set_vertical_swing_mode(self, swing_mode: VerticalSwingMode) -> None:
        """Set the device vertical swing mode."""
        self._state.set(GreeProp.SWING_VERTICAL, swing_mode)

    @property
    def horizontal_swing_mode(self) -> HorizontalSwingMode:
        """Return the current horizontal swing setting."""
        return HorizontalSwingMode(
            self._state.get(GreeProp.SWING_HORIZONTAL)
            or HorizontalSwingMode.default.value
        )

    def set_horizontal_swing_mode(self, swing_mode: HorizontalSwingMode) -> None:
        """Set the device horizontal swing mode."""
        self._state.set(GreeProp.SWING_HORIZONTAL, swing_mode)

    @property
    def target_temperature_unit(self) -> TemperatureUnits:
        """Return the units of the target temperature."""
        return TemperatureUnits(
            self._state.get(GreeProp.TARGET_TEMPERATURE_UNIT)
            or TemperatureUnits.C.value
        )

    def set_target_temperature_unit(self, units: TemperatureUnits) -> None:
        """Set the units of the target temperature."""
        self._state.set(GreeProp.TARGET_TEMPERATURE_UNIT, units)

    @property
    def target_temperature(self) -> float:
        """Return the target temperature in target_temperature_unit."""

        raw_c = self._state.get(GreeProp.TARGET_TEMPERATURE, 0)
        tem_rec = self._state.get(GreeProp.TARGET_TEMPERATURE_BIT, 0)

        if raw_c is not None and tem_rec is not None:
            if self.target_temperature_unit == TemperatureUnits.F:
                return gree_get_target_temperature_f(raw_c, tem_rec)
            if self.target_temperature_unit == TemperatureUnits.C:
                return gree_get_target_temperature_c(raw_c, tem_rec)
        return 0.0

    def set_target_temperature(self, value: float) -> None:
        """Set the target temperature in target_temperature_unit."""

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

        self._state.update(
            {
                GreeProp.TARGET_TEMPERATURE: raw_c,
                GreeProp.TARGET_TEMPERATURE_BIT: tem_rec,
            }
        )

        if self.feature_smart_heat or self.feature_energy_saving:
            _LOGGER.info(
                "[%s] Temperature set, but being ignored while smart heat or energy saving modes are enabled",
                self.unique_id,
            )

    @property
    def feature_light_sensor(self) -> bool:
        """Return the light sensor state."""
        return self._state.get_bool(GreeProp.FEAT_SENSOR_LIGHT)

    def set_feature_light_sensor(self, value: bool) -> None:
        """Set the light sensor state."""
        self._state.set_bool(GreeProp.FEAT_SENSOR_LIGHT, value)

    @property
    def feature_fresh_air(self) -> bool:
        """Return the fresh air mode state."""
        return self._state.get_bool(GreeProp.FEAT_FRESH_AIR)

    def set_feature_fresh_air(self, value: bool) -> None:
        """Set the fresh air mode state."""
        self._state.set_bool(GreeProp.FEAT_FRESH_AIR, value)

    @property
    def feature_x_fan(self) -> bool:
        """Return the x-fan mode state."""
        return self._state.get_bool(GreeProp.FEAT_XFAN)

    def set_feature_xfan(self, value: bool) -> None:
        """Set the x-fan mode state."""
        self._state.set_bool(GreeProp.FEAT_XFAN, value)

    @property
    def feature_health(self) -> bool:
        """Return the health mode state."""
        return self._state.get_bool(GreeProp.FEAT_HEALTH)

    def set_feature_health(self, value: bool) -> None:
        """Set the health mode state."""
        self._state.set_bool(GreeProp.FEAT_HEALTH, value)

    @property
    def feature_sleep(self) -> SleepMode:
        """Return the sleep mode state."""

        sleep_enabled = self._state.get_bool(GreeProp.FEAT_SLEEP_MODE)
        mode = SleepMode(
            self._state.get(GreeProp.FEAT_SLEEP_MODE_TYPE) or SleepMode.disabled.value
        )

        if sleep_enabled and mode is SleepMode.disabled:
            _LOGGER.warning(
                "[%s] Inconsistent Sleep mode properties. Mode enabled and type disabled",
                self.unique_id,
            )
            return SleepMode.normal

        if not sleep_enabled and mode is not SleepMode.disabled:
            _LOGGER.warning(
                "[%s] Inconsistent Sleep mode properties. Mode disabled and type enabled",
                self.unique_id,
            )
            return SleepMode.disabled

        return mode

    def set_feature_sleep(self, mode: SleepMode) -> None:
        """Set the sleep mode state.

        This feature is only available under `Cool` or `Heat` modes.
        This feature is incompatible with `Power Saving` and `Smart Heat`, and will force disable them if activated.
        """

        if mode is not SleepMode.disabled and self.operation_mode not in (
            OperationMode.cool,
            OperationMode.heat,
        ):
            raise GreeSleepUnavailable("Sleep is only available in Cool and Heat")

        # Mirror the remote/app functionality
        if mode is not SleepMode.disabled:
            self.set_feature_energy_saving(False)
            self.set_feature_smart_heat(False)

        self._state.update(
            {
                GreeProp.FEAT_SLEEP_MODE: (1 if mode is not SleepMode.disabled else 0),
                GreeProp.FEAT_SLEEP_MODE_TYPE: mode.value,
            }
        )

    @property
    def feature_light(self) -> bool:
        """Return the light state."""
        return self._state.get_bool(GreeProp.FEAT_LIGHT)

    def set_feature_light(self, value: bool) -> None:
        """Set the light state."""
        self._state.set_bool(GreeProp.FEAT_LIGHT, value)

    @property
    def feature_quiet(self) -> bool:
        """Return the quiet mode state."""
        return self._state.get_bool(GreeProp.FEAT_QUIET_MODE)

    def set_feature_quiet(self, value: bool) -> None:
        """Set the quiet mode state.

        This mode is ignored until Energy Saving or Smart Heat features are disabled.
        """

        self._state.set_bool(GreeProp.FEAT_QUIET_MODE, value)

        if value and (self.feature_energy_saving or self.feature_smart_heat):
            _LOGGER.info(
                "[%s] Quiet mode set, but being ignored while smart heat or energy saving modes are enabled",
                self.unique_id,
            )

    @property
    def feature_turbo(self) -> bool:
        """Return the turbo mode state."""
        return self._state.get_bool(GreeProp.FEAT_TURBO_MODE)

    def set_feature_turbo(self, value: bool) -> None:
        """Set the turbo mode state.

        This mode is only availabe under `Cool` or `Heat` modes.
        This mode is ignored until Energy Saving or Smart Heat features are disabled.
        """

        if value and self.operation_mode not in (
            OperationMode.cool,
            OperationMode.heat,
        ):
            raise GreeTurboUnavailable(
                "Turbo mode is only available under Cool or Heat modes"
            )

        self._state.set_bool(GreeProp.FEAT_TURBO_MODE, value)

        if value and (self.feature_energy_saving or self.feature_smart_heat):
            _LOGGER.info(
                "[%s] Turbo mode set, but being ignored while smart heat or energy saving modes are enabled",
                self.unique_id,
            )

    @property
    def feature_smart_heat(self) -> bool:
        """Return the smart heat (8ºC / anti-freeze) mode state."""
        return self._state.get_bool(GreeProp.FEAT_SMART_HEAT_8C)

    def set_feature_smart_heat(self, value: bool) -> None:
        """Set the smart heat (8ºC / anti-freeze) mode state.

        This mode is only availabe under `Heat` mode.
        This feature is incompatible with `Sleep` and `Energy Saving`, and will force disable them if activated.
        The device will ignore the temperature and fan settings.
        """

        if value and self.operation_mode is not OperationMode.heat:
            raise GreeSmartHeatUnavailable(
                "Smart Heat mode is only available under Heat mode"
            )

        # Mirror physical behaviour
        if value:
            self.set_feature_sleep(SleepMode.disabled)
            self.set_feature_energy_saving(False)

        self._state.set_bool(GreeProp.FEAT_SMART_HEAT_8C, value)

    @property
    def feature_energy_saving(self) -> bool:
        """Return the energy saving mode state."""
        return self._state.get_bool(GreeProp.FEAT_ENERGY_SAVING)

    def set_feature_energy_saving(self, value: bool) -> None:
        """Set the energy saving mode state.

        This feature is only available under `Cool` mode.
        This feature is incompatible with `Sleep` and `Smart Heat`, and will force disable them if activated.
        The device will ignore the temperature and fan settings.
        """

        if value and self.operation_mode is not OperationMode.cool:
            raise GreeEnergySavingUnavailable(
                "Energy saving is only available under Cool mode."
            )

        # Mirror the remote/app functionality
        if value:
            self.set_feature_sleep(SleepMode.disabled)
            self.set_feature_smart_heat(False)

        self._state.set_bool(GreeProp.FEAT_ENERGY_SAVING, value)

    @property
    def feature_anti_direct_blow(self) -> bool:
        """Return the anti direct blow mode state."""
        return self._state.get_bool(GreeProp.FEAT_ANTI_DIRECT_BLOW)

    def set_feature_anti_direct_blow(self, value: bool) -> None:
        """Set the anti direct blow mode state."""
        self._state.set_bool(GreeProp.FEAT_ANTI_DIRECT_BLOW, value)

    @property
    def feature_humidity_control(self) -> HumidityControlMode:
        """Returns the current humidity control mode."""

        return HumidityControlMode(
            self._state.get(GreeProp.FEATURE_HUMIDITY_CONTROL)
            or HumidityControlMode.disabled.value
        )

    def set_feature_humidity_control(self, mode: HumidityControlMode) -> None:
        """Set the Humidy Control mode.

        `HumidityControlMode.smart_dry` is only available under `Cool` mode.
        `HumidityControlMode.continuous_dry`  is only available under `Dry` mode.
        """

        if mode != HumidityControlMode.disabled and self.operation_mode not in (
            OperationMode.cool,
            OperationMode.dry,
        ):
            raise GreeHumidityControlUnavailable(
                "Humidity Control is only available in Cool and Dry modes"
            )

        if (
            mode == HumidityControlMode.smart_dry
            and self.operation_mode is not OperationMode.cool
        ):
            raise GreeSmartDryUnavailable(
                "Smart Dry is only available in Cool operation mode"
            )

        if (
            mode is HumidityControlMode.continuous_dry
            and self.operation_mode is not OperationMode.dry
        ):
            raise GreeContinuousDryUnavailable(
                "Continuous Dry is only available in Dry operation mode"
            )

        match mode:
            case HumidityControlMode.disabled:
                target = 0

            case HumidityControlMode.target_dry:
                if self.operation_mode == OperationMode.cool:
                    target = gree_get_target_humidity_prop_from_p(
                        MIN_HUM_COOL_P, MIN_HUM_COOL_P, MAX_HUM_COOL_P
                    )
                else:
                    target = gree_get_target_humidity_prop_from_p(
                        MIN_HUM_DRY_P, MIN_HUM_DRY_P, MAX_HUM_DRY_P
                    )

            case HumidityControlMode.smart_dry:
                target = 3  # It's possible the device ignores this value in this mode

            case HumidityControlMode.continuous_dry:
                target = 3  # It's possible the device ignores this value in this mode

        self._state.update(
            {
                GreeProp.FEATURE_HUMIDITY_CONTROL: mode.value,
                GreeProp.FEATURE_HUMIDITY_TARGET: target,
            }
        )

    @property
    def feature_humidity_control_target(self) -> int:
        """Return the current set target humidity value."""

        raw_value: int | None = self._state.get(GreeProp.FEATURE_HUMIDITY_TARGET, 0)
        return gree_get_target_humidity_p(raw_value or 0)

    def set_feature_humidity_control_target(
        self, humidity_target_percentage: int
    ) -> None:
        """Set the target humidity percentage (in multiples of 5).

        Cool mode range: 40-80.
        Dry mode range: 30-70.
        """

        if self.feature_humidity_control is not HumidityControlMode.target_dry:
            raise GreeHumidityControlTargetUnavailable(
                "Humidity Control with a target humidity is only available in Normal Dry mode"
            )

        if self.operation_mode == OperationMode.cool:
            target = gree_get_target_humidity_prop_from_p(
                humidity_target_percentage, MIN_HUM_COOL_P, MAX_HUM_COOL_P
            )
        else:
            target = gree_get_target_humidity_prop_from_p(
                humidity_target_percentage, MIN_HUM_DRY_P, MAX_HUM_DRY_P
            )

        self._state.set(GreeProp.FEATURE_HUMIDITY_TARGET, target)
