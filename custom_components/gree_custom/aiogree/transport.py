"""Handles network connections."""

from abc import ABC, abstractmethod
from collections import defaultdict
from collections.abc import Callable
import json
import logging
from typing import Any, NamedTuple

from .cipher import CipherBase, EncryptionVersion
from .errors import GreeBindingError
from .helpers import gree_decrypt_pack, gree_encrypt_pack

_LOGGER = logging.getLogger(__name__)


class BindingInfo(NamedTuple):
    """Combination of key and encryption version from a binding procedure."""

    encryption_key: str
    encryption_version: EncryptionVersion
    cipher: CipherBase


class GreeBaseTransport(ABC):
    """Base transport interface."""

    batch_support: bool = False

    def __init__(self) -> None:
        """Init transport."""
        self._listeners: dict[str, set[Callable[[str, dict], None]]] = defaultdict(set)
        self.connections: dict[str, list[str]] = {}
        self.bound_controllers: dict[str, BindingInfo] = {}

    #
    # Connection
    #

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to endpoint."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Terminate connection to endpoint."""

    @abstractmethod
    async def _subscribe(self, mac_controller: str) -> None:
        """Subscribe the transport to a device."""

    @abstractmethod
    async def _unsubscribe(self, mac_controller: str) -> None:
        """Unsubscribe the transport from a device."""

    #
    # Requests
    #

    def add_listener(
        self, target_mac: str, listener: Callable[[str, dict], None]
    ) -> None:
        """Register a listener for messages for a given device. Callback has the message type and data."""
        self._listeners[target_mac].add(listener)

    def remove_listener(
        self, target_mac: str, listener: Callable[[str, dict], None]
    ) -> None:
        """Unregister a listener for messages for a given device. Callback has the message type and data."""
        listeners = self._listeners.get(target_mac)
        if listeners is None:
            return

        listeners.discard(listener)

        if not listeners:
            del self._listeners[target_mac]

    async def request_json(
        self,
        mac_controller: str,
        payload: dict[str, Any],
        cipher: CipherBase,
        max_attempts: int | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send and receive a JSON payload."""

        requests: list[dict[str, Any]]

        pack = payload.get("pack")
        if (
            pack
            and not self.batch_support
            and pack.get("t") == "cmd"
            and len(pack.get("opt", [])) > 1
        ):
            requests = []

            for opt, value in zip(pack["opt"], pack["p"], strict=True):
                request = payload.copy()
                request["pack"] = {
                    **pack,
                    "opt": [opt],
                    "p": [value],
                }
                requests.append(request)
        else:
            requests = [payload]

        responses: list[dict[str, Any]] = []

        for request in requests:
            request = gree_encrypt_pack(request, cipher)

            raw_request = json.dumps(request)
            raw_response = await self.request(
                mac_controller, raw_request, max_attempts, timeout
            )

            response = json.loads(raw_response)
            response = gree_decrypt_pack(response, cipher)

            responses.append(response)

        if len(responses) == 1:
            return responses[0]

        # Merge responses
        merged = responses[-1].copy()
        merged_pack: dict[str, Any] = {}

        for response in responses:
            pack = response.get("pack")
            if not isinstance(pack, dict):
                continue

            for key, value in pack.items():
                if isinstance(value, list):
                    merged_pack.setdefault(key, []).extend(value)
                else:
                    merged_pack[key] = value

        if merged_pack:
            merged["pack"] = merged_pack
        else:
            merged.pop("pack", None)

        return merged

    @abstractmethod
    async def request(
        self,
        mac_controller: str,
        json_str: str,
        max_attempts: int | None = None,
        timeout: float | None = None,
    ) -> str:
        """Send raw bytes and return the response.

        max_attempts and timeout override the transport's own retry count and
        reply timeout for this one request.
        """

    #
    # Binding
    #
    async def add_device(
        self,
        mac_addr: str,
        mac_addr_controller: str,
        listener: Callable[[str, dict], None] | None = None,
    ) -> None:
        """Add a device to the transport."""
        if not mac_addr or not bool(mac_addr.strip()):
            raise GreeBindingError("No device MAC provided")

        if not mac_addr_controller or not bool(mac_addr_controller.strip()):
            raise GreeBindingError("No controller MAC provided")

        if mac_addr_controller not in self.bound_controllers:
            await self._subscribe(mac_addr_controller)

        self._add_connected_device(mac_addr_controller, mac_addr)

        if listener:
            self.add_listener(mac_addr, listener)

    async def remove_device(
        self,
        mac_addr: str,
        mac_addr_controller: str,
        listener: Callable[[str, dict], None] | None = None,
    ) -> None:
        """Remove a device from the transport."""
        if not mac_addr or not bool(mac_addr.strip()):
            raise GreeBindingError("No device MAC provided")

        if not mac_addr_controller or not bool(mac_addr_controller.strip()):
            raise GreeBindingError("No controller MAC provided")

        if listener:
            self.remove_listener(mac_addr, listener)

        self._remove_connected_device(mac_addr_controller, mac_addr)

        if mac_addr_controller not in self.bound_controllers:
            await self._unsubscribe(mac_addr_controller)

    def _add_connected_device(self, mac_addr_controller: str, mac_addr: str) -> None:
        if mac_addr_controller not in self.connections:
            self.connections[mac_addr_controller] = []

        if mac_addr not in self.connections[mac_addr_controller]:
            self.connections[mac_addr_controller].append(mac_addr)

    def _remove_connected_device(self, mac_addr_controller: str, mac_addr: str) -> None:
        if mac_addr_controller not in self.connections:
            return

        if mac_addr in (conn := self.connections.get(mac_addr_controller, [])):
            conn.remove(mac_addr)

        if len(conn) == 0:
            self.connections.pop(mac_addr_controller, None)
            self.bound_controllers.pop(mac_addr_controller, None)

    def get_controller_connected_devices(self, mac_addr_controller: str) -> list[str]:
        """Has the controller any connected devices on this transport."""
        return self.connections.get(mac_addr_controller, [])

    def get_controller_binding_info(
        self, mac_addr_controller: str
    ) -> BindingInfo | None:
        """Retrieve the Binding Info associated to a controller."""
        return self.bound_controllers.get(mac_addr_controller, None)

    def set_controller_binding_info(
        self, mac_controller: str, binding_info: BindingInfo | None
    ) -> None:
        """Set the state of a controller to bound in this transport."""

        if binding_info is None and mac_controller in self.bound_controllers:
            self.bound_controllers.pop(mac_controller, None)
        elif binding_info is not None:
            self.bound_controllers[mac_controller] = binding_info
