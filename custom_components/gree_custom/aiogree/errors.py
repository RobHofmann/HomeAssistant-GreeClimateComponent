"""Errors raised by the integration."""


class GreeError(Exception):
    """Base error for the Gree integration."""


class GreeConnectionError(GreeError):
    """Network communication with device failed."""


class GreeProtocolError(GreeError):
    """Device returned invalid data."""


class GreeBindingError(GreeError):
    """Failed to obtain encryption key."""
