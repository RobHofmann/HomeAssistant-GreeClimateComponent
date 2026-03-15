"""Errors raised by the integration."""


class GreeError(Exception):
    """Base error for the Gree integration."""


class GreeConnectionError(GreeError):
    """Network communication with device failed."""


class GreeProtocolError(GreeError):
    """Device returned invalid data."""


class GreeAuthenticationError(GreeError):
    """Failed to obtain encryption key."""


class GreeAuthenticationErrorBadKey(GreeError):
    """Provided encryption key wrong."""
