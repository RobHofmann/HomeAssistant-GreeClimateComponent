"""Errors raised by the integration."""


class GreeError(Exception):
    """Base error for the Gree integration."""


class GreeCloudError(Exception):
    """Error while communicating with the Gree Cloud."""


class GreeCloudLoginError(GreeCloudError):
    """Error while logging in to the Gree Cloud."""


class GreeConnectionError(GreeError):
    """Network communication with device failed."""


class GreeProtocolError(GreeError):
    """Device returned invalid data."""


class GreeBindingError(GreeError):
    """Failed to obtain encryption key."""


class GreeRuntimeError(GreeError):
    """Problem with the runtime."""


class GreeUnsupportedState(GreeError):
    """The requested state/feature is not valid or available."""


class GreeSleepUnavailable(GreeUnsupportedState):
    """Sleep mode is only available under Cool or Heat modes."""


class GreeEnergySavingUnavailable(GreeUnsupportedState):
    """Energy Saving mode is only available under Cool mode."""


class GreeSmartHeatUnavailable(GreeUnsupportedState):
    """Smart Heat mode is only available under Heat mode."""


class GreeTurboUnavailable(GreeUnsupportedState):
    """Turbo mode is only available under Cool and Heat modes."""


class GreeHumidityControlUnavailable(GreeUnsupportedState):
    """Humidity Control is only available under Cool mode."""


class GreeContinuousDryUnavailable(GreeUnsupportedState):
    """Humidity Control Continuous Dry only available in Dry operation mode."""


class GreeSmartDryUnavailable(GreeUnsupportedState):
    """Humidity Control Smart Dry only available in Cool operation mode."""


class GreeHumidityControlTargetUnavailable(GreeUnsupportedState):
    """Humidity Control with a target humidity is only available in Cool with Normal Dry mode."""
