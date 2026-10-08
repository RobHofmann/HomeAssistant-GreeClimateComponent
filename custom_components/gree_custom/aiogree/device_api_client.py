"""Client used to interface with the actual device through a Transport."""

from collections.abc import Callable, Mapping
import logging

from .api import (
    POLLED_PROPS,
    BindingInfo,
    GreeProp,
    InfoProp,
    OtherProps,
    StatusResult,
    gree_get_status,
    gree_process_status_pack,
    gree_set_status,
    gree_try_bind,
)
from .cipher import CipherBase, EncryptionVersion, get_cipher
from .const import (
    MIN_PACK_PROPS,
    PROBE_TIMEOUT,
    STATUS_CANARY_PROP,
    STATUS_CANARY_PROP_MAX_REQUESTS,
)
from .errors import GreeBindingError, GreeConnectionError, GreeError, GreeRuntimeError
from .helpers import chunked, gree_decrypt_pack, redact_str
from .transport import GreeBaseTransport

_LOGGER = logging.getLogger(__name__)


class DeviceApiClient:
    """Manager for the communication with the device API."""

    def __init__(
        self,
        mac: str,
        userid: int,
    ) -> None:
        """Initialize the client."""
        self.controller_mac = ""
        self._mac = mac
        self._userid = userid

        self._transport: GreeBaseTransport | None = None

        self._available = False

        self._listeners: list[Callable[[dict[str, str]], None]] = []

        # How many columns one status request may carry on this device.
        # Measured once by probe_device_limits() right after binding.
        # None means the device has no limit we need to care about.
        self._max_props: int | None = None

    #
    # Binding
    #

    async def bind(
        self,
        controller_mac: str,
        preferred_version: EncryptionVersion | None = None,
        preferred_key: str | None = None,
        force_bind: bool = False,
    ) -> None:
        """Bind to the current transport using the suggested version and key."""

        if self._transport is None:
            raise GreeBindingError("No transport configured")

        if not controller_mac or not bool(controller_mac.strip()):
            raise GreeBindingError("No controller MAC provided")

        if self.bound:
            return

        self.controller_mac = controller_mac

        _LOGGER.info(
            "[%s:%s] Starting binding procedure", self.controller_mac, self._transport
        )

        await self._transport.add_device(
            self.controller_mac, self._mac, self._handle_transport_message
        )

        # Bind if the transport is not bound to the controller already
        if (
            force_bind
            or self._transport.get_controller_binding_info(self.controller_mac) is None
        ):
            try:
                result = await gree_try_bind(
                    self.controller_mac,
                    self._userid,
                    preferred_version,
                    preferred_key,
                    self._transport,
                )

            except Exception:
                _LOGGER.exception("Error while binding")
                await self._transport.remove_device(
                    self.controller_mac, self._mac, self._handle_transport_message
                )
                raise

            else:
                self._transport.set_controller_binding_info(self.controller_mac, result)
                _LOGGER.info(
                    "[%s] Device is bound with version %s and key %s via %s",
                    self.controller_mac,
                    result.encryption_version,
                    redact_str(result.encryption_key),
                    self._transport,
                )

        self._available = True

        await self.probe_device_limits()

    async def probe_device_limits(self) -> None:
        """Measure how many columns one status request may carry.

        Some firmwares cap the number of columns per status request. The cap
        differs per firmware, so it is measured here instead of being fixed.
        The first probe asks for as many columns as the default poll has,
        which is the largest status request the component sends. If that
        works there is nothing to limit and `_max_props` stays None. If it
        fails, a binary search below it looks for the largest size that
        still works. The result is kept until `unbind()`.

        A probe never raises. A device that answers nothing at all ends up on
        MIN_PACK_PROPS, and the empty status guard in `GreeDevice` deals with
        the rest.
        """
        first = len(POLLED_PROPS)

        if await self._probe_columns(first):
            self._max_props = None
            _LOGGER.debug(
                "[%s] Status requests are not limited, %d columns are answered",
                self._mac,
                first,
            )
            return

        # Largest size that still works, somewhere below the failing first probe
        low = MIN_PACK_PROPS
        high = first - 1
        best: int | None = None

        while low <= high:
            middle = (low + high) // 2
            if await self._probe_columns(middle):
                best = middle
                low = middle + 1
            else:
                high = middle - 1

        if best is None:
            self._max_props = MIN_PACK_PROPS
            _LOGGER.warning(
                "[%s] Not even %d columns were answered, the device may be "
                "answering nothing at all. Using %d columns per request",
                self._mac,
                MIN_PACK_PROPS,
                MIN_PACK_PROPS,
            )
            return

        self._max_props = best
        _LOGGER.info("[%s] Status requests are limited to %d columns", self._mac, best)

    async def _probe_columns(self, count: int) -> bool:
        """Ask for `count` columns once and tell if the device answered well.

        The request holds STATUS_CANARY_PROP, which every unit answers, plus
        throw-away names the device does not know. The probe passes when the
        canary comes back and no column with an empty name comes back. An empty
        name is how some firmwares mark a request they had to cut short. No
        reply, an empty reply or any error is a failure.
        """
        if not self.cipher or not self._transport:
            return False

        props = [STATUS_CANARY_PROP, *[f"X{i:02d}" for i in range(count - 1)]]

        try:
            result = await gree_get_status(
                self.controller_mac,
                self._mac,
                self._userid,
                props,
                self.cipher,
                self._transport,
                1,
                None,
                PROBE_TIMEOUT,
            )

        except GreeError as err:
            _LOGGER.debug("[%s] Probe of %d columns failed: %s", self._mac, count, err)
            return False

        # A dict that holds the canary is never empty, so this covers the
        # empty reply case as well.
        passed = (
            STATUS_CANARY_PROP in result.prop_values and "" not in result.prop_values
        )

        _LOGGER.debug(
            "[%s] Probe of %d columns %s",
            self._mac,
            count,
            "passed" if passed else "failed",
        )

        return passed

    async def unbind(self) -> None:
        """Unbind from the current transport."""
        if not self.bound:
            return

        if not self._transport:
            raise GreeBindingError("Cannot unbind when no transport is set.")

        await self._transport.remove_device(
            self.controller_mac, self._mac, self._handle_transport_message
        )

        self._listeners.clear()

        self._available = False
        self._max_props = None

    async def rebind(self, force_bind: bool = False) -> None:
        """Try binding with the current transport.

        If force_bind is false, reuses previous binding info.
        """
        await self.unbind()
        return await self.bind(
            self.controller_mac,
            self.encryption_version,
            self.encryption_key,
            force_bind,
        )

    #
    # Transport
    #

    @property
    def transport(self) -> GreeBaseTransport | None:
        """The current client transport."""
        return self._transport

    async def set_transport(
        self,
        transport: GreeBaseTransport,
    ) -> None:
        """Set the client transport."""
        await self.unbind()
        self._transport = transport

    #
    # Query
    #
    async def _is_device_responsive(self) -> bool:
        if not self._transport:
            return False

        _LOGGER.warning(
            "[%s] Assessing if device is responding",
            self._mac,
        )

        try:
            await gree_get_status(
                self.controller_mac,
                self._mac,
                self._userid,
                [STATUS_CANARY_PROP],
                self.cipher,
                self._transport,
                STATUS_CANARY_PROP_MAX_REQUESTS,
                self._max_props,
                PROBE_TIMEOUT,
            )
        except GreeError:
            return False
        else:
            return True

    async def query_props(
        self,
        props: list[str],
        request_batch: int = 1,
        error_as_missing: bool = False,
        max_attempts: int | None = None,
    ) -> StatusResult:
        """Query the status value of device properties.

        With error_as_missing, a request that gets no answer marks its props as
        missing and the sweep goes on. After MAX_UNANSWERED_IN_A_ROW of those in a
        row the sweep stops and the rest is reported as missing too.
        max_attempts limits the transport retries per request, so a diagnostic
        sweep does not spend timeout x retries on every prop the device ignores.
        """
        if not self.bound:
            await self.rebind(force_bind=True)

        if not self.binding_info:
            raise GreeRuntimeError("No binding info.")

        if not self._transport:
            raise GreeRuntimeError("No transport set.")

        state: dict[str, str] = {}
        missing: list[str] = []

        chunks = list(chunked(props, request_batch))
        for _, chunk in enumerate(chunks):
            try:
                result = await gree_get_status(
                    self.controller_mac,
                    self._mac,
                    self._userid,
                    chunk,
                    self.cipher,
                    self._transport,
                    max_attempts,
                    self._max_props,
                )

                state.update(result.prop_values)
                missing.extend(result.missing_props)
                self._available = True

            except GreeError as err:
                if (
                    isinstance(err, GreeConnectionError)
                    and not await self._is_device_responsive()
                ):
                    self._available = False
                    raise

                if error_as_missing:
                    missing.extend(chunk)
                else:
                    raise

        return StatusResult(prop_values=state, missing_props=missing)

    async def query_all_props(
        self,
        request_batch: int = 1,
        error_as_missing: bool = False,
        max_attempts: int | None = None,
    ) -> StatusResult:
        """Query all possible props."""

        all_props = [
            *[prop.value for prop in GreeProp],
            *[prop.value for prop in InfoProp],
            *[prop.value for prop in OtherProps],
        ]

        return await self.query_props(
            all_props, request_batch, error_as_missing, max_attempts
        )

    async def set_props(
        self,
        values: Mapping[str, int],
    ) -> None:
        """Send the state of multiple properties to the device."""
        if not self.bound:
            await self.rebind()

        if not self.binding_info:
            raise GreeRuntimeError("No bidning info.")

        if not self._transport:
            raise GreeRuntimeError("No transport set.")

        try:
            await gree_set_status(
                self.controller_mac,
                self._mac,
                self._userid,
                values,
                self.cipher,
                self._transport,
            )
            self._available = True

        except GreeError as err:
            if (
                isinstance(err, GreeConnectionError)
                and not await self._is_device_responsive()
            ):
                self._available = False
            raise

    #
    # Transport Push Messages
    #

    def add_status_listener(
        self,
        callback: Callable[[dict[str, str]], None],
    ) -> None:
        """Add a listener for status updates."""
        _LOGGER.debug("Adding Listener: %s", callback)
        self._listeners.append(callback)

    def remove_status_listener(
        self,
        callback: Callable[[dict[str, str]], None],
    ) -> None:
        """Remove a listener from status updates."""
        _LOGGER.debug("Removing Listener: %s", callback)
        try:
            self._listeners.remove(callback)
        except ValueError:
            _LOGGER.warning("Callback to remove not in the listeners list")

    def _handle_transport_message(
        self,
        topic: str,
        payload: dict,
    ) -> None:

        if self.cipher is None:
            return

        if "status" not in topic:
            return

        response = gree_decrypt_pack(
            payload,
            self.cipher,
        )

        if pack := response.get("pack"):
            result = gree_process_status_pack(
                pack,
                None,
            )

            for listener in self._listeners:
                try:
                    listener(result.prop_values)
                except Exception:
                    _LOGGER.exception("Error during listener execution")

    #
    # Properties
    #

    @property
    def available(self) -> bool:
        """Is the device available."""
        return self._available

    @property
    def bound(self) -> bool:
        """Is the device bound to the transport."""
        return (
            self.binding_info is not None
            and self._transport is not None
            and self._mac
            in self._transport.get_controller_connected_devices(self.controller_mac)
        )

    @property
    def binding_info(self) -> BindingInfo | None:
        """Binding information for the last successful binding with a transport."""
        if self._transport:
            return self._transport.get_controller_binding_info(self.controller_mac)
        return None

    @property
    def encryption_key(self) -> str | None:
        """The current device encryption key obtained after binding."""
        return None if self.binding_info is None else self.binding_info.encryption_key

    @property
    def encryption_version(self) -> EncryptionVersion | None:
        """The current device encryption version obtained after binding."""
        return (
            None if self.binding_info is None else self.binding_info.encryption_version
        )

    @property
    def cipher(self) -> CipherBase:
        """The current device cipher."""
        return (
            get_cipher(EncryptionVersion.V1)
            if self.binding_info is None
            else self.binding_info.cipher
        )
