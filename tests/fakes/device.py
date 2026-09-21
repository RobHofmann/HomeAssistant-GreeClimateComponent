"""A fake Gree device that speaks the real protocol over a real UDP socket.

Design choice: the fake encrypts and decrypts with the component's own cipher
from `aiogree.cipher`. That keeps the fake short and gives V2 (AES-GCM) for
free. The cost is that a bug inside the cipher could cancel itself out here,
because both sides would share it. `test_cipher.py` covers the cipher on its
own, with fixed vectors, for that reason.

The fake binds a real UDP socket and answers real packets. Nothing about the
transport is faked, so retries, timeouts, stream resets and the decrypt path
all run as they do in the field.
"""

import asyncio
import json
import logging
import time
from typing import Any, override

from aiogree.cipher import (
    GREE_GENERIC_DEVICE_KEY_ECB,
    GREE_GENERIC_DEVICE_KEY_GCM,
    CipherBase,
    EncryptionVersion,
    get_cipher,
)

_LOGGER = logging.getLogger(__name__)

# A session key is always 16 characters. This one is not a real device key.
DEFAULT_SESSION_KEY = "V1sT9p0aQ3zXcR7m"
ROTATED_SESSION_KEY = "R0tAt3dK3yABCDEF"
DEFAULT_MAC = "f4911e3f1ac8"


class FakeGreeDevice(asyncio.DatagramProtocol):
    """A Gree unit on loopback UDP, with a personality.

    Every keyword stands for a failure mode seen on real hardware. The device
    records each request it received, because most useful assertions are about
    what went over the wire, not only about what came back.
    """

    def __init__(
        self,
        mac: str = DEFAULT_MAC,
        name: str = "Fake AC",
        session_key: str = DEFAULT_SESSION_KEY,
        encryption_version: EncryptionVersion = EncryptionVersion.V1,
        *,
        answer_scan: bool = True,
        answer_bind: bool = True,
        scan_delay: float = 0.0,
        reply_delay: float = 0.0,
        max_columns: int | None = None,
        unsupported_props: set[str] | None = None,
        ignore_first: int = 0,
        drop_after: int | None = None,
        raw_reply: bytes | None = None,
        reply_key: str | None = None,
        scan_info: dict[str, Any] | None = None,
    ) -> None:
        """Set up the device.

        Args:
            mac: MAC the device reports and answers on.
            name: Name in the scan reply.
            session_key: Key handed out by the bind.
            encryption_version: V1 (AES-ECB) or V2 (AES-GCM).
            answer_scan: False means the device never answers a scan.
            answer_bind: False means the device never answers a bind.
            scan_delay: Seconds to wait before answering a scan.
            reply_delay: Seconds to wait before answering anything else.
            max_columns: Status requests above this many columns get an empty
                result, as a real firmware at its limit does.
            unsupported_props: Columns the device leaves out of its reply.
            ignore_first: Say nothing to this many requests first, then answer
                normally. That is a device that needs a retry.
            drop_after: Stop answering after this many requests.
            raw_reply: Answer every request with these exact bytes. Use it for
                replies that are not valid JSON.
            reply_key: Encrypt replies with this key instead of the session
                key, which is what a device with a rotated key looks like.
            scan_info: Extra fields for the scan reply, for example subCnt.

        """
        self.mac = mac
        self.name = name
        self.session_key = session_key
        self.encryption_version = encryption_version

        self.answer_scan = answer_scan
        self.answer_bind = answer_bind
        self.scan_delay = scan_delay
        self.reply_delay = reply_delay
        self.max_columns = max_columns
        self.unsupported_props = unsupported_props or set()
        self.ignore_first = ignore_first
        self.drop_after = drop_after
        self.raw_reply = raw_reply
        self.reply_key = reply_key
        self.scan_info = scan_info

        self.values: dict[str, int] = {"Pow": 1, "Mod": 1, "SetTem": 21, "TemSen": 61}

        # What went over the wire. Times are monotonic seconds.
        self.requests: list[dict[str, Any]] = []
        self.packs: list[dict[str, Any]] = []
        self.request_times: list[float] = []
        self.keys_used: list[str] = []

        self.host = ""
        self.port = 0

        self._transport: asyncio.DatagramTransport | None = None
        self._pending: set[asyncio.TimerHandle] = set()

    # Lifecycle

    async def start(self, host: str = "127.0.0.1", port: int = 0) -> None:
        """Bind the socket. Port 0 picks a free port and reads it back."""
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: self, local_addr=(host, port)
        )
        self._transport = transport
        sockname = transport.get_extra_info("sockname")
        self.host, self.port = sockname[0], sockname[1]

    def close(self) -> None:
        """Close the socket and cancel anything still scheduled."""
        for handle in self._pending:
            handle.cancel()
        self._pending.clear()

        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def rotate_key(self) -> None:
        """Hand out a new session key, as a device does after a power cycle."""
        self.session_key = ROTATED_SESSION_KEY

    # Ciphers

    def generic_cipher(self) -> CipherBase:
        """Return the cipher every device accepts before it is bound."""
        return get_cipher(self.encryption_version)

    def session_cipher(self) -> CipherBase:
        """Return the cipher used for everything after the bind."""
        return get_cipher(self.encryption_version, self.reply_key or self.session_key)

    def _decrypt(self, envelope: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """Decrypt a pack. Returns the pack and which key opened it.

        A real device silently drops what it cannot decrypt, so an unreadable
        pack gives (None, "none") and the caller sends no reply.
        """
        raw = envelope.get("pack")
        if not raw:
            return None, "none"

        tag = envelope.get("tag")
        candidates = (
            (self.session_key, "session"),
            (GREE_GENERIC_DEVICE_KEY_ECB, "generic"),
            (GREE_GENERIC_DEVICE_KEY_GCM, "generic"),
        )
        for key, label in candidates:
            try:
                plain = get_cipher(self.encryption_version, key).decrypt(raw, tag)
                return json.loads(plain), label
            except Exception:  # noqa: BLE001
                continue

        return None, "none"

    def _wrap(self, pack: dict[str, Any], cipher: CipherBase) -> dict[str, Any]:
        """Put a pack in an envelope, encrypted the way a device does."""
        encrypted, tag = cipher.encrypt(json.dumps(pack))
        envelope: dict[str, Any] = {
            "t": "pack",
            "i": 1,
            "uid": 0,
            "cid": self.mac,
            "tcid": "",
            "pack": encrypted,
        }
        if tag is not None:
            envelope["tag"] = tag
        return envelope

    # Wire handling

    @override
    def datagram_received(self, data: bytes, addr: tuple[str | Any, int]) -> None:
        """Handle one packet."""
        self.request_times.append(time.monotonic())

        try:
            envelope = json.loads(data)
        except json.JSONDecodeError:
            _LOGGER.debug("Fake device got a packet that is not JSON")
            return

        self.requests.append(envelope)

        if len(self.requests) <= self.ignore_first:
            return

        if self.drop_after is not None and len(self.requests) > self.drop_after:
            return

        if self.raw_reply is not None:
            self._send_raw(self.raw_reply, addr)
            return

        reply = self.handle(envelope)
        if reply is None:
            return

        delay = self.scan_delay if envelope.get("t") == "scan" else self.reply_delay
        self._send_raw(json.dumps(reply).encode(), addr, delay)

    def _send_raw(
        self, payload: bytes, addr: tuple[str | Any, int], delay: float = 0.0
    ) -> None:
        """Send bytes back, now or after a delay."""
        if self._transport is None:
            return

        if delay <= 0:
            self._transport.sendto(payload, addr)
            return

        loop = asyncio.get_running_loop()
        handle = loop.call_later(delay, self._send_later, payload, addr)
        self._pending.add(handle)

    def _send_later(self, payload: bytes, addr: tuple[str | Any, int]) -> None:
        """Send bytes that were held back by a delay."""
        if self._transport is not None:
            self._transport.sendto(payload, addr)

    def handle(self, envelope: dict[str, Any]) -> dict[str, Any] | None:
        """Build the reply for one request, or None to stay silent."""
        kind = envelope.get("t")

        if kind == "scan":
            if not self.answer_scan:
                return None
            return self._wrap(self.build_scan_info(), self.generic_cipher())

        pack, key_used = self._decrypt(envelope)
        if pack is None:
            return None

        self.packs.append(pack)
        self.keys_used.append(key_used)

        return self.handle_pack(envelope, pack)

    def handle_pack(
        self, envelope: dict[str, Any], pack: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Build the reply for one decrypted pack."""
        kind = pack.get("t")

        if kind == "bind":
            if not self.answer_bind:
                return None
            body = {"t": "bindok", "mac": self.mac, "key": self.session_key}
            return self._wrap(body, self.generic_cipher())

        if kind == "status":
            return self._wrap(self.build_status(pack), self.session_cipher())

        if kind == "cmd":
            return self._wrap(self.build_command_result(pack), self.session_cipher())

        return None

    # Reply bodies

    def build_scan_info(self) -> dict[str, Any]:
        """Build the 'dev' pack a device answers a scan with."""
        info: dict[str, Any] = {
            "t": "dev",
            "cid": self.mac,
            "mac": self.mac,
            "bc": "",
            "brand": "gree",
            "catalog": "gree",
            "mid": "60",
            "model": "gree",
            "name": self.name,
            "lock": 0,
            "series": "gree",
            "vender": "1",
            "ver": "V3.2.M",
        }
        if self.scan_info:
            info.update(self.scan_info)
        return info

    def build_status(self, pack: dict[str, Any]) -> dict[str, Any]:
        """Mirror the asked columns, within this firmware's limits."""
        cols: list[str] = list(pack.get("cols", []))

        if self.max_columns is not None and len(cols) > self.max_columns:
            # A unit at its column limit answers r=200 with nothing in it.
            return {"t": "dat", "mac": self.mac, "r": 200, "cols": [], "dat": []}

        answered = [col for col in cols if col not in self.unsupported_props]
        return {
            "t": "dat",
            "mac": self.mac,
            "r": 200,
            "cols": answered,
            "dat": [self.values.get(col, 0) for col in answered],
        }

    def build_command_result(self, pack: dict[str, Any]) -> dict[str, Any]:
        """Acknowledge a command by mirroring its options and values."""
        options = list(pack.get("opt", []))
        values = list(pack.get("p", []))
        for option, value in zip(options, values, strict=False):
            self.values[option] = value
        return {
            "t": "res",
            "mac": self.mac,
            "r": 200,
            "opt": options,
            "p": values,
        }
