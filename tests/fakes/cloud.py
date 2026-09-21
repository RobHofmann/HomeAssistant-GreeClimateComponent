"""A fake Gree Cloud, served over real HTTP on loopback.

The cloud API posts a base64 string that holds an AES-ECB encrypted JSON body,
and gets back `{"enRes": <same encoding>}`. This server speaks that, so the
client under test does its real encryption, its real HTTP request and its real
parsing. Only the host changes.

The encryption is written out here instead of borrowed from the client, so a
bug in the client's own encrypt or decrypt cannot cancel itself out.
"""

import base64
import json
import socket
from typing import Any

from aiohttp import web
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

# The key the Gree app uses for its cloud calls.
CLOUD_AES_KEY = b"#G$&^jgfujy6ujxt"

USER_ID = 4242
TOKEN = "cloud-token-abc"


def encrypt(plain: str) -> str:
    """Encrypt the way the cloud does: AES-128-ECB, PKCS7, base64."""
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plain.encode()) + padder.finalize()
    encryptor = Cipher(
        algorithms.AES(CLOUD_AES_KEY), modes.ECB(), backend=default_backend()
    ).encryptor()
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode()


def decrypt(encoded: str) -> str:
    """Read back what the client sent."""
    decryptor = Cipher(
        algorithms.AES(CLOUD_AES_KEY), modes.ECB(), backend=default_backend()
    ).decryptor()
    raw = base64.b64decode(encoded)
    padded = decryptor.update(raw) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return (unpadder.update(padded) + unpadder.finalize()).decode()


def cloud_device(mac: str, key: str, name: str = "Zolderkamer") -> dict[str, Any]:
    """One device as the cloud lists it. Every field the model needs is here."""
    return {
        "mac": mac,
        "pmac": mac[:12],
        "name": name,
        "catalog": "gree",
        "brand": "gree",
        "mid": "60",
        "subdivCode": "32768",
        "vender": "1",
        "key": key,
        "barCode": "0000",
        "longitude": "0",
        "latitude": "0",
        "altitude": "0",
        "city": "Utrecht",
        "bindTime": "2026-01-01 00:00:00",
        "selfLearning": 0,
        "ssid": "wifi",
        "autoRepair": 0,
        "authorize": "1",
        "thirdpartyId": "",
        "ver": "V3.2.M",
        "prodModel": "gree",
        "hid": "362001065279+U-CS532Z(LT)V3.75.bin",
        "institutionCodeSN": "",
        "devNoteName": "",
        "isHidden": 0,
        "devExt": "",
        "regionalControl": "",
        "homeSort": 0,
    }


class FakeGreeCloud:
    """A Gree Cloud server on a free port."""

    def __init__(
        self,
        homes: list[dict[str, Any]] | None = None,
        devices_per_home: dict[int, list[dict[str, Any]]] | None = None,
        *,
        login_response: dict[str, Any] | None = None,
        firmware_response: dict[str, Any] | None = None,
        http_status: int = 200,
    ) -> None:
        """Set up the answers this cloud gives.

        Args:
            homes: The homes the account has.
            devices_per_home: The devices in each home, by home id.
            login_response: What the login returns. The default is a good login.
            firmware_response: What the firmware endpoint returns.
            http_status: Answer every call with this status instead of 200.

        """
        self.homes = homes if homes is not None else [{"id": 1, "name": " Thuis "}]
        self.devices_per_home = devices_per_home or {}
        self.login_response = (
            login_response
            if login_response is not None
            else {"uid": USER_ID, "token": TOKEN}
        )
        self.firmware_response = firmware_response
        self.http_status = http_status

        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.url = ""

        self._runner: web.AppRunner | None = None

    async def start(self) -> None:
        """Bind a free port and start serving."""
        app = web.Application()
        app.router.add_post("/App/UserLoginV2", self._handle_login)
        app.router.add_post("/App/GetHomes", self._handle_homes)
        app.router.add_post("/App/GetDevsInRoomsOfHomeV2", self._handle_devices)
        app.router.add_get("/wifiModule/Lastversion", self._handle_firmware)

        # Bind first, so the port is known without reaching into the server.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

        self._runner = web.AppRunner(app)
        await self._runner.setup()
        await web.SockSite(self._runner, sock).start()

        self.url = f"http://127.0.0.1:{port}"

    async def close(self) -> None:
        """Stop serving."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None

    async def _read(self, request: web.Request) -> dict[str, Any]:
        """Decrypt and record one request body."""
        body = await request.text()
        payload: dict[str, Any] = json.loads(decrypt(body))
        self.requests.append((request.path, payload))
        return payload

    def _answer(self, body: dict[str, Any]) -> web.Response:
        """Wrap a body the way the cloud does."""
        if self.http_status != 200:
            return web.Response(status=self.http_status, text="no")
        return web.json_response({"enRes": encrypt(json.dumps(body))})

    async def _handle_login(self, request: web.Request) -> web.Response:
        await self._read(request)
        return self._answer(self.login_response)

    async def _handle_homes(self, request: web.Request) -> web.Response:
        await self._read(request)
        return self._answer({"home": self.homes})

    async def _handle_devices(self, request: web.Request) -> web.Response:
        payload = await self._read(request)
        devices = self.devices_per_home.get(int(payload["homeId"]), [])
        return self._answer({"rooms": [{"devs": devices}]})

    async def _handle_firmware(self, request: web.Request) -> web.Response:
        self.requests.append((request.path, dict(request.query)))
        if self.firmware_response is None:
            return web.Response(status=404, text="unknown firmware")
        return web.json_response(self.firmware_response)
