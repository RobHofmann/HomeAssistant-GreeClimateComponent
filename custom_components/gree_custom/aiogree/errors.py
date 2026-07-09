"""Errors raised by the integration."""


class GreeError(Exception):
    """Base error for the Gree integration."""


class GreeConnectionError(GreeError):
    """Network communication with device failed."""


class GreeProtocolError(GreeError):
    """Device returned invalid data."""


class GreeBindingError(GreeError):
    """Failed to obtain encryption key."""


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


class GreeTurboIgnored(GreeUnsupportedState):
    """Turbo mode is ignored when Energy Saving or Smart Heat are enabled."""


class GreeQuietIgnored(GreeUnsupportedState):
    """Quiet mode is ignored when Energy Saving or Smart Heat are enabled."""


class GreeHumidityControlUnavailable(GreeUnsupportedState):
    """Humidty Control is only available under Cool mode."""


class GreeHumidityControlTargetUnavailable(GreeUnsupportedState):
    """Humidity Control with a target humidity is only available in Cool with Normal Dry mode."""


class GreeContinuousDryUnavailable(GreeUnsupportedState):
    """Humidity Control Continuos Dry only available in Dry operation mode."""
