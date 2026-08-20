"""Contains the ``DeviceState`` class that holds and manages the device state."""

from collections.abc import Iterable
import logging
from types import MappingProxyType

from .api import INFOPROP_KEY_TO_ENUM, PROP_KEY_TO_ENUM, GreeProp, InfoProp

_LOGGER = logging.getLogger(__name__)


class DeviceState:
    """Represents the local state of a Gree device."""

    def __init__(self, device_id: str, capabilities: Iterable[GreeProp]) -> None:
        """Initialize the device state."""
        self._device_id: str = device_id

        self._raw: dict[GreeProp, int] = {}
        self._pending: dict[GreeProp, int] = {}
        self._info: dict[InfoProp, str] = {}

        self._capabilities = set(capabilities)

        # Poll everything but beeper
        self._props_to_poll: tuple[GreeProp, ...] = tuple(
            p for p in GreeProp if p not in (GreeProp.BEEPER, GreeProp.BEEPER_NEW)
        )

    #
    # State access
    #

    def get(self, prop: GreeProp, default: int | None = None) -> int | None:
        """Get the raw value of a property.

        Returns the pending value from ``pending`` if present, otherwise the
        last known value from ``raw``. If the property does not exist in
        either state, returns ``default``.
        """

        # Query first the transient state, so we can make changes to the device state
        # before having to push it to the device, preventing the need for a push for each change
        if prop in self._pending:
            return self._pending[prop]

        if prop in self._raw:
            return self._raw[prop]

        _LOGGER.info(
            "[%s] Property '%s' not found in state of device. Returning default value",
            self._device_id,
            prop,
        )
        return default

    def get_bool(self, prop: GreeProp, default: int = 0) -> bool:
        """Get the bool value of a property."""
        prop_value: int | None = self.get(prop, default)

        return bool(prop_value)

    def set(self, prop: GreeProp, value: int) -> None:
        """Set the pending state value of a property."""
        if self.supports(prop):
            _LOGGER.debug("[%s] Setting property %s: %d", self._device_id, prop, value)
            self._pending[prop] = value
        else:
            _LOGGER.error(
                "[%s] Property %s is unsuported on this device", self._device_id, prop
            )

    def set_bool(self, prop: GreeProp, value: bool) -> None:
        """Set the pending state value of a property with a bool."""
        self.set(prop, 1 if value else 0)

    def update(self, values: dict[GreeProp, int]) -> None:
        """Update the pending state with multiple property values."""
        for prop, value in values.items():
            self.set(prop, value)

    def clear_pending(self) -> None:
        """Clear the pending state."""
        self._pending.clear()

    #
    # Raw protocol processing
    #

    def process_new_state(self, new_state: dict[str, str]) -> None:
        """Process a new state for the properties and update the state object."""
        unknown = []
        errors = []

        for key, value in new_state.items():
            try:
                if key in PROP_KEY_TO_ENUM:
                    prop = PROP_KEY_TO_ENUM[key]

                    if prop in self._props_to_poll:
                        self._raw[prop] = int(value)

                elif key in INFOPROP_KEY_TO_ENUM:
                    self._info[INFOPROP_KEY_TO_ENUM[key]] = value

                else:
                    unknown.append(key)

            except ValueError, TypeError:
                errors.append(key)

        if unknown:
            _LOGGER.debug("[%s] Unknown properties: %s", self._device_id, unknown)

        if errors:
            _LOGGER.debug("[%s] Invalid values: %s", self._device_id, errors)

    #
    # Property helpers
    #

    def supports(self, prop: GreeProp) -> bool:
        """Validate that a property exists in the state.

        We consider a property as unsupported if it is not present in the raw state list
        This assumes that the full state is updated at least once before this method is called

        Beeper is always returned as supported.
        """
        return (prop in self._raw and prop in self._capabilities) or prop in (
            GreeProp.BEEPER,
            GreeProp.BEEPER_NEW,
        )

    def remove(self, prop: GreeProp) -> None:
        """Remove a property from being polled."""
        self._props_to_poll = tuple(p for p in self._props_to_poll if p != prop)
        self._raw.pop(prop, None)
        self._pending.pop(prop, None)
        _LOGGER.debug(
            "[%s] No longer updating property: %s", self._device_id, repr(prop)
        )

    def invalidate_missing_properties(self) -> None:
        """Remove properties from polling if their state values are not valid."""

        # Remove all unsupported properties
        # A unsupported propery is one that the device returns
        # with an empty string, or nothing at all
        # If that is the case, _state_raw should not contain that property
        # In case it still has it, we remove it here as well
        for p in self._props_to_poll:
            if not self.supports(p):
                self.remove(p)

    def invalidate_missing_property_group(
        self, props: list[GreeProp], missing_value: int = 0
    ) -> None:
        """Remove a group of properties from polling based on a ordered list of preference."""

        # Keep the first (lowest priority number) non-zero value
        preferred = next(
            (p for p in props if self.get(p, missing_value) != missing_value),
            None,
        )

        for prop in props:
            if prop is preferred:
                continue

            if prop not in self._props_to_poll:
                continue

            self.remove(prop)

    @property
    def has_pending_updates(self) -> bool:
        """Does the state have pending values to be commited."""
        return any(self._raw.get(k) != v for k, v in self._pending.items())

    #
    # Read-only views
    #
    @property
    def polled_properties(self) -> tuple[GreeProp, ...]:
        """The currently polled properties."""
        return self._props_to_poll

    @property
    def raw(self) -> MappingProxyType[GreeProp, int]:
        """The current device state values."""
        return MappingProxyType(self._raw)

    @property
    def pending(self) -> MappingProxyType[GreeProp, int]:
        """The pending uncommited device state values."""
        return MappingProxyType(self._pending)

    @property
    def info(self) -> MappingProxyType[InfoProp, str]:
        """The Device Info property values."""
        return MappingProxyType(self._info)
