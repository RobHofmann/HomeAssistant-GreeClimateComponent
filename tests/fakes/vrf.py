"""A fake Gree VRF gateway: one controller that fronts several indoor units.

A gateway answers a scan with `subCnt` above zero. The client then asks for the
sub-device list. Real gateways answer that in two shapes, one with the list at
the top level and one with the list inside an encrypted pack, so the fake can
produce both.
"""

from typing import Any, override

from .device import DEFAULT_SESSION_KEY, FakeGreeDevice

GATEWAY_MAC = "9424b8fd5ba3"


def sub_device_macs(gateway_mac: str, count: int) -> list[str]:
    """Build the MACs of the indoor units under a gateway.

    A VRF sub-device MAC is the 12 character gateway MAC plus two characters.
    """
    return [f"{gateway_mac}{index:02d}" for index in range(count)]


class FakeVrfGateway(FakeGreeDevice):
    """A gateway with `sub_count` indoor units behind it."""

    def __init__(
        self,
        mac: str = GATEWAY_MAC,
        name: str = "GR-Gcloud_60_0a_5ba3_EC",
        session_key: str = DEFAULT_SESSION_KEY,
        *,
        sub_count: int = 4,
        returned: int | None = None,
        list_shape: str = "top",
        answer_sublist: bool = True,
        **kwargs: Any,
    ) -> None:
        """Set up the gateway.

        Args:
            mac: MAC of the gateway.
            name: Name in the scan reply.
            session_key: Key handed out by the bind.
            sub_count: The subCnt the gateway promises in its scan reply.
            returned: How many units the list really holds. None means all of
                them. A smaller number is a gateway that promised more than it
                delivers.
            list_shape: "top" puts the list at the top level of the reply,
                "pack" puts it inside a pack encrypted with the session key.
            answer_sublist: False means the gateway never answers the request.
            kwargs: Anything FakeGreeDevice accepts.

        """
        scan_info: dict[str, Any] = {"subCnt": sub_count}
        scan_info.update(kwargs.pop("scan_info", None) or {})
        super().__init__(
            mac=mac, name=name, session_key=session_key, scan_info=scan_info, **kwargs
        )

        self.sub_count = sub_count
        self.returned = sub_count if returned is None else returned
        self.list_shape = list_shape
        self.answer_sublist = answer_sublist

        # What the gateway saw on the sub-device request.
        self.sublist_requests: list[dict[str, Any]] = []
        self.sublist_key_used: str | None = None

    def sub_devices(self) -> list[dict[str, str]]:
        """Return the units the gateway really reports."""
        return [
            {"mac": mac, "mid": "6049"}
            for mac in sub_device_macs(self.mac, self.sub_count)[: self.returned]
        ]

    @override
    def handle_pack(
        self, envelope: dict[str, Any], pack: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Answer the sub-device list, or fall back to normal device behaviour."""
        if envelope.get("t") != "subList":
            return super().handle_pack(envelope, pack)

        self.sublist_requests.append(envelope)
        self.sublist_key_used = self.keys_used[-1] if self.keys_used else None

        if not self.answer_sublist:
            return None

        units = self.sub_devices()
        body: dict[str, Any] = {
            "t": "subList",
            "i": 0,
            "c": len(units),
            "r": 200,
            "list": units,
        }

        if self.list_shape == "pack":
            return self._wrap(body, self.session_cipher())

        return body
