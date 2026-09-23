"""A fake Gree VRF gateway: one controller that fronts several indoor units.

A gateway answers a scan with `subCnt` above zero. The client then asks for the
sub-device list. Real gateways know three forms of that request, and a given
WiFi module may answer only some of them (see docs/protocol.md):

- device-key: a `pack` envelope with `t: subList` inside. The reply uses the
  bound device key.
- generic-key: a `subList` envelope with `i: 1`. The request uses the bound
  device key, but the reply uses the generic key.
- subDev: a `pack` envelope with `t: subDev` inside, for older W06 modules.
  The reply uses the bound device key.

Each form can be switched on or off on its own, and each can return its own
subset of the units. A reply has the list at the top level or inside an
encrypted pack, so the fake can produce both shapes.
"""

from collections.abc import Mapping, Sequence
import time
from typing import Any, override

from aiogree.api import SubListForm

from .device import DEFAULT_SESSION_KEY, FakeGreeDevice

GATEWAY_MAC = "9424b8fd5ba3"

# A request that matches none of the known forms, for example the old request
# with a `subList` envelope and `i: 0`.
UNKNOWN_FORM = "unknown"


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
        forms: Mapping[SubListForm, Sequence[int] | None] | None = None,
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
                "pack" puts it inside an encrypted pack.
            answer_sublist: False means the gateway answers no form at all.
            forms: The forms this gateway answers, each with the indexes of
                the units that form returns. None as a value means the first
                `returned` units. A form that is not in the mapping gets no
                answer. None for the whole mapping means every form answers
                with the first `returned` units.
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
        self.forms: Mapping[SubListForm, Sequence[int] | None] = (
            dict.fromkeys(SubListForm) if forms is None else forms
        )

        # What the gateway saw on the sub-device requests, one entry per
        # request: the envelope, the form, the key that opened the pack and
        # the monotonic time it came in.
        self.sublist_requests: list[dict[str, Any]] = []
        self.sublist_forms: list[str] = []
        self.sublist_keys: list[str] = []
        self.sublist_times: list[float] = []

    def sub_devices(self, form: SubListForm) -> list[dict[str, str]]:
        """Return the units the gateway reports for one form."""
        indexes = self.forms.get(form)
        if indexes is None:
            indexes = range(self.returned)

        macs = sub_device_macs(self.mac, max([self.sub_count, *indexes]) + 1)
        return [{"mac": macs[index], "mid": "6049"} for index in indexes]

    @staticmethod
    def sublist_form(envelope: dict[str, Any], pack: dict[str, Any]) -> str | None:
        """Tell which form a request is, or None if it is not a sub-device request."""
        if envelope.get("t") == "subList":
            return SubListForm.GENERIC_KEY if envelope.get("i") == 1 else UNKNOWN_FORM

        if envelope.get("t") == "pack" and pack.get("t") == "subList":
            return SubListForm.DEVICE_KEY

        if envelope.get("t") == "pack" and pack.get("t") == "subDev":
            return SubListForm.SUB_DEV

        return None

    @override
    def handle_pack(
        self, envelope: dict[str, Any], pack: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Answer the sub-device list, or fall back to normal device behaviour."""
        form = self.sublist_form(envelope, pack)
        if form is None:
            return super().handle_pack(envelope, pack)

        self.sublist_requests.append(envelope)
        self.sublist_forms.append(form)
        self.sublist_keys.append(self.keys_used[-1] if self.keys_used else "none")
        self.sublist_times.append(time.monotonic())

        if not self.answer_sublist or form == UNKNOWN_FORM:
            return None

        known_form = SubListForm(form)
        if known_form not in self.forms:
            return None

        units = self.sub_devices(known_form)
        body: dict[str, Any] = {
            "t": "subList",
            "i": 0,
            "c": len(units),
            "r": 200,
            "list": units,
        }

        if self.list_shape == "pack":
            # The generic key form is answered with the generic key, the
            # other two with the bound key.
            cipher = (
                self.generic_cipher()
                if known_form is SubListForm.GENERIC_KEY
                else self.session_cipher()
            )
            return self._wrap(body, cipher)

        return body
