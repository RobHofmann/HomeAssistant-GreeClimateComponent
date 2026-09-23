"""Contains the ``DeviceState`` class that holds and manages the device state."""

from collections.abc import Callable, Iterable, Mapping
import logging
import time
from types import MappingProxyType

from .api import (
    INFOPROP_KEY_TO_ENUM,
    POLLED_PROPS,
    PROP_KEY_TO_ENUM,
    GreeProp,
    InfoProp,
)
from .const import HELD_VALUE_TTL

_LOGGER = logging.getLogger(__name__)


class DeviceState:
    """Represents the local state of a Gree device."""

    def __init__(
        self,
        device_id: str,
        capabilities: Iterable[GreeProp],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the device state.

        Args:
            device_id: Name of the device in log lines
            capabilities: The props this device may be told to change
            clock: Source of monotonic seconds for the held values. Tests pass
                their own so they do not have to wait.

        """
        self._device_id: str = device_id
        self._clock = clock

        self._raw: dict[GreeProp, int] = {}
        self._pending: dict[GreeProp, int] = {}
        # Values that were sent and are not confirmed yet, with the monotonic
        # time at which the hold ends.
        self._held: dict[GreeProp, tuple[int, float]] = {}
        self._info: dict[InfoProp, str] = {}
        self._unknown: dict[str, str] = {}

        self._capabilities = set(capabilities)

        # Poll everything but beeper
        self._props_to_poll: tuple[GreeProp, ...] = POLLED_PROPS

    #
    # State access
    #

    def get(self, prop: GreeProp, default: int | None = None) -> int | None:
        """Get the raw value of a property.

        Returns the pending value from ``pending`` if present, then the held
        value from ``held``, otherwise the last known value from ``raw``. If
        the property does not exist in any of them, returns ``default``.
        """

        # Query first the transient state, so we can make changes to the device state
        # before having to push it to the device, preventing the need for a push for each change
        if prop in self._pending:
            return self._pending[prop]

        held = self._held_value(prop)
        if held is not None:
            return held

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
                "[%s] Property %s is unsupported on this device", self._device_id, prop
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
    # Held values
    #

    def hold(self, values: Mapping[GreeProp, int]) -> None:
        """Keep showing values that were just sent, until the device confirms them.

        A VRF gateway can answer with its old cached state for a few seconds
        after a command. While a prop is held, `get()` returns the sent value
        instead of the reported one. The hold ends when the device reports the
        sent value, or after `HELD_VALUE_TTL` seconds, after which the reported
        value wins again. That way a command the device rejected is not shown
        for ever.

        Props that are not polled, like the beeper, are never reported, so
        they are not held.
        """
        expires = self._clock() + HELD_VALUE_TTL
        for prop, value in values.items():
            if prop in self._props_to_poll:
                self._held[prop] = (value, expires)

    def _held_value(self, prop: GreeProp) -> int | None:
        """Return the held value of a prop, or None when it is not held."""
        entry = self._held.get(prop)
        if entry is None:
            return None

        value, expires = entry
        if self._clock() >= expires:
            del self._held[prop]
            _LOGGER.debug(
                "[%s] Device did not confirm %s=%d in time, using the reported value",
                self._device_id,
                prop,
                value,
            )
            return None

        return value

    def _drop_expired_holds(self) -> None:
        """Drop every hold whose time is up."""
        for prop in list(self._held):
            self._held_value(prop)

    def _confirm_hold(self, prop: GreeProp, reported: int) -> None:
        """End the hold on a prop if the device reported the sent value.

        This compares with what the device really sent, never with the held
        value that `get()` shows.
        """
        entry = self._held.get(prop)
        if entry is None:
            return

        if reported == entry[0]:
            del self._held[prop]
            _LOGGER.debug(
                "[%s] Device confirmed %s=%d", self._device_id, prop, reported
            )
        else:
            _LOGGER.debug(
                "[%s] Device still reports %s=%d, holding the sent value %d",
                self._device_id,
                prop,
                reported,
                entry[0],
            )

    #
    # Raw protocol processing
    #

    def process_new_state(self, new_state: dict[str, str]) -> None:
        """Process a new state for the properties and update the state object."""
        unknown = []
        errors = []

        self._drop_expired_holds()

        for key, value in new_state.items():
            try:
                if key in PROP_KEY_TO_ENUM:
                    prop = PROP_KEY_TO_ENUM[key]

                    if prop in self._props_to_poll:
                        self._raw[prop] = int(value)
                        self._confirm_hold(prop, self._raw[prop])

                elif key in INFOPROP_KEY_TO_ENUM:
                    self._info[INFOPROP_KEY_TO_ENUM[key]] = value

                else:
                    self._unknown[key] = value
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
        self._held.pop(prop, None)
        _LOGGER.debug(
            "[%s] No longer updating property: %s", self._device_id, repr(prop)
        )

    def invalidate_missing_properties(self) -> None:
        """Remove properties from polling if their state values are not valid."""

        # Remove all unsupported properties
        # A unsupported property is one that the device returns
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
        """Does the state have pending values to be committed.

        A pending value is compared with the held value first, because that
        is what the device was last told. Comparing with a stale reported
        value would skip a change back to that value.
        """
        return any(
            (held if (held := self._held_value(k)) is not None else self._raw.get(k))
            != v
            for k, v in self._pending.items()
        )

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
        """The pending uncommitted device state values."""
        return MappingProxyType(self._pending)

    @property
    def held(self) -> MappingProxyType[GreeProp, int]:
        """The values that were sent and are not confirmed by the device yet."""
        self._drop_expired_holds()
        return MappingProxyType({k: v for k, (v, _) in self._held.items()})

    @property
    def info(self) -> MappingProxyType[InfoProp, str]:
        """The Device Info property values."""
        return MappingProxyType(self._info)

    @property
    def unknown(self) -> MappingProxyType[str, str]:
        """The unknown property values."""
        return MappingProxyType(self._unknown)
