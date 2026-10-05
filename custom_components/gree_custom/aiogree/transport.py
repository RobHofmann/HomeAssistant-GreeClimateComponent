"""Handles network connections."""

from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from collections.abc import Callable
import json
import logging
from typing import Any, NamedTuple

from .cipher import CipherBase, EncryptionVersion
from .helpers import gree_decrypt_pack, gree_encrypt_pack

_LOGGER = logging.getLogger(__name__)


class BindingInfo(NamedTuple):
    """Combination of key and encryption version from a binding procedure."""

    encryption_key: str
    encryption_version: EncryptionVersion


class GreeBaseTransport(ABC):
    """Base transport interface."""

    batch_support: bool = False

    def __init__(self) -> None:
        """Init transport."""
        self._listeners: dict[str, set[Callable[[str, dict], None]]] = defaultdict(set)
        self.connected_devices: Counter[str] = Counter()
        self.bound_controllers: dict[str, BindingInfo] = {}

    @abstractmethod
    async def connect(self) -> None:
        """Establish connection to endpoint."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Terminate connection to endpoint."""

    @abstractmethod
    async def subscribe(self, mac_controller: str) -> None:
        """Subscribe the transport to a device."""

    @abstractmethod
    async def unsubscribe(self, mac_controller: str) -> None:
        """Unsubscribe the transport from a device."""

    def is_bound_to_controller(self, mac_controller: str) -> BindingInfo | None:
        """If the transport is already bound to a controller, return the binding info otherwise None."""
        if mac_controller in self.bound_controllers:
            return self.bound_controllers[mac_controller]

        return None

    def set_bound_to_controller(
        self, mac_controller: str, binding_info: BindingInfo | None
    ) -> None:
        """Set the state of a coontroller to bound in this transport."""

        if binding_info is None and mac_controller in self.bound_controllers:
            self.bound_controllers.pop(mac_controller)
        elif binding_info is not None and mac_controller not in self.bound_controllers:
            self.bound_controllers.setdefault(mac_controller, binding_info)

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
