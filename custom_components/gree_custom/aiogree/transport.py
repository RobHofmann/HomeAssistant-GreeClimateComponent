"""Handles network connections."""

from abc import ABC, abstractmethod
from collections import Counter, defaultdict
from collections.abc import Callable
import json
import logging
from typing import Any

from .cipher import CipherBase
from .helpers import gree_decrypt_pack, gree_encrypt_pack

_LOGGER = logging.getLogger(__name__)


class GreeBaseTransport(ABC):
    """Base transport interface."""

    batch_support: bool = False

    def __init__(self) -> None:
        """Init transport."""
        self._listeners: dict[str, set[Callable[[str, dict], None]]] = defaultdict(set)
        self.connected_devices: Counter[str] = Counter()

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

    @abstractmethod
    async def request(self, mac_controller: str, json_str: str) -> str:
        """Send raw bytes and return the response."""

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
        self, mac_controller: str, payload: dict[str, Any], cipher: CipherBase
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
            raw_response = await self.request(mac_controller, raw_request)

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
