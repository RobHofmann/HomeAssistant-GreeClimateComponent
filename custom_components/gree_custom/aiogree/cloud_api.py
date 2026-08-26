"""Gree Cloud API Client.

Based on: https://github.com/luc10/gree-api-client

Allows authentication with Gree Cloud and retrieval of device information
including encryption keys required for MQTT communication.
"""

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
import logging
from types import TracebackType
from typing import Self

import aiohttp
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from pydantic import BaseModel, ConfigDict, Field

from .errors import GreeCloudError, GreeCloudLoginError

_LOGGER = logging.getLogger(__name__)


@dataclass
class CloudHome:
    """Information about a Gree Cloud home."""

    id: int
    name: str


@dataclass
class CloudCredentials:
    """Gree Cloud authentication credentials."""

    user_id: int
    token: str


class CloudDeviceInfoResponse(BaseModel):
    """Response format for a cloud device discovered using the Gree Cloud."""

    model_config = ConfigDict(extra="ignore")

    mac: str
    pmac: str
    name: str
    catalog: str
    brand: str
    mid: str
    subdivCode: str  # noqa: N815
    vender: str
    key: str
    barCode: str  # noqa: N815
    longitude: str
    latitude: str
    altitude: str
    city: str
    bindTime: str  # noqa: N815
    selfLearning: int  # noqa: N815
    ssid: str
    autoRepair: int  # noqa: N815
    authorize: str
    thirdpartyId: str  # noqa: N815
    ver: str
    prodModel: str  # noqa: N815
    hid: str
    institutionCodeSN: str  # noqa: N815
    devNoteName: str  # noqa: N815
    isHidden: int  # noqa: N815
    devExt: str  # noqa: N815
    regionalControl: str  # noqa: N815
    homeSort: int  # noqa: N815


class FirmwareInfoResponse(BaseModel):
    """Response format for a firmware information query."""

    model_config = ConfigDict(populate_by_name=True)

    create_date: str | None = Field(default=None, alias="CreateDate")
    comm_protocol_version: str | None = Field(default=None, alias="commProtVer")
    description: str | None = Field(default=None, alias="desc")
    forced_upgrade: bool | None = Field(default=None, alias="forcedUpgrade")
    forced_upgrade_type: int | None = Field(default=None, alias="frcUpgdType")
    result: int | None = Field(default=None, alias="r")
    url: str | None = None
    version: str | None = Field(default=None, alias="ver")


class GreeRegion(StrEnum):
    """List of supported Gree regions."""

    AU = "Australia"
    CN = "China Mainland"
    AS = "East South Asia"
    EU = "Europe"
    IN = "India"
    LA = "Latin American"
    ME = "Middle East"
    US = "North American"
    RU = "Russia"
    SA = "South American"


CLOUD_SERVERS = {
    GreeRegion.AU: "https://augrih.gree.com",
    GreeRegion.CN: "https://grih.gree.com",
    GreeRegion.AS: "https://hkgrih.gree.com",
    GreeRegion.EU: "https://eugrih.gree.com",
    GreeRegion.IN: "https://ingrih.gree.com",
    GreeRegion.LA: "https://lagrih.gree.com",
    GreeRegion.ME: "https://megrih.gree.com",
    GreeRegion.US: "https://nagrih.gree.com",
    GreeRegion.RU: "https://rugrih.gree.com",
    GreeRegion.SA: "https://sagrih.gree.com",
}


class GreeCloudApi:
    """Gree Cloud API Client.

    Provides authentication and device discovery for Gree Cloud services.
    """

    # App constants from reverse engineering
    APP_ID = "4920681951525131286"
    APP_HASH = "0fa513124aa97781d1f3f40d61ca1a89"
    AES_KEY = b"#G$&^jgfujy6ujxt"

    def __init__(self, region: GreeRegion, username: str, password: str) -> None:
        """Initialize the Gree Cloud API client.

        Args:
            base_url: The regional Gree Cloud server URL
            username: User email/username
            password: User password (will be hashed internally)

        """
        self.region = region
        self.base_url = CLOUD_SERVERS[region]
        self.username = username
        self.password = password
        self.user_id: int | None = None
        self.token: str | None = None

        # Create session with timeout
        timeout = aiohttp.ClientTimeout(total=30, connect=10)
        self._session: aiohttp.ClientSession | None = aiohttp.ClientSession(
            timeout=timeout
        )

    @classmethod
    def for_server(
        cls, region: GreeRegion, username: str, password: str
    ) -> GreeCloudApi:
        """Create API client for a specific server region.

        Args:
            region: Gree region (e.g., 'Europe', 'North American')
            username: User email/username
            password: User password

        Returns:
            GreeCloudApi instance configured for the specified region

        """

        return cls(region, username, password)

    def _md5(self, input_str: str) -> str:
        """Calculate MD5 hash."""
        return hashlib.md5(input_str.encode("utf-8")).hexdigest()

    def _prepare_body(
        self, payload: dict, date: datetime, hash_props: list[str]
    ) -> dict:
        """Prepare request body with authentication.

        Args:
            payload: Request payload data
            date: Current datetime (should be UTC)
            hash_props: List of property names to include in hash calculation

        Returns:
            Complete request body with API authentication

        """
        # Use UTC time for consistency with server
        t = date.strftime("%Y-%m-%d %H:%M:%S")
        r = int(date.timestamp())

        # Generate verification code
        vc = self._md5(f"{self.APP_ID}_{self.APP_HASH}_{t}_{r}")

        # Generate data verification code
        props = [str(payload[p]) for p in hash_props]
        dat_vc = self._md5(f"{self.APP_HASH}_{'_'.join(props)}")

        return {
            "api": {
                "appId": self.APP_ID,
                "r": r,
                "t": t,
                "vc": vc,
            },
            "datVc": dat_vc,
            **payload,
        }

    def _encrypt(self, data: str) -> bytes:
        """Encrypt data with AES-128-ECB."""

        # Setup padding (PKCS7)
        padder = padding.PKCS7(128).padder()
        padded_data = padder.update(data.encode()) + padder.finalize()

        # Setup Cipher
        cipher = Cipher(
            algorithms.AES(self.AES_KEY), modes.ECB(), backend=default_backend()
        )
        encryptor = cipher.encryptor()
        return encryptor.update(padded_data) + encryptor.finalize()

    def _decrypt(self, data: bytes) -> str:
        """Decrypt data with AES-128-ECB."""
        # Setup Cipher
        cipher = Cipher(
            algorithms.AES(self.AES_KEY), modes.ECB(), backend=default_backend()
        )
        decryptor = cipher.decryptor()

        # Decrypt
        decrypted_padded = decryptor.update(data) + decryptor.finalize()

        # Remove padding (PKCS7)
        unpadder = padding.PKCS7(128).unpadder()

        try:
            unpadded_data = unpadder.update(decrypted_padded) + unpadder.finalize()
            return unpadded_data.decode()
        except Exception:
            # Fallback for malformed padding if necessary
            return decrypted_padded.decode(errors="ignore")

    async def _send_request(self, endpoint: str, data: str) -> str:
        """Send POST request to API.

        Args:
            endpoint: API endpoint path
            data: JSON data to send

        Returns:
            Encrypted response string

        """

        url = f"{self.base_url}{endpoint}"

        encrypted_body = self._encrypt(data)
        base64_body = base64.b64encode(encrypted_body).decode("utf-8")

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Gaen1": "5ac2bdf935bcca70",
            "Charset": "utf-8",
        }

        _LOGGER.debug("Sending request to %s", url)

        if self._session is None:
            raise GreeCloudError("No HTTP session")

        # Use persistent session with timeout
        async with self._session.post(
            url, data=base64_body, headers=headers
        ) as response:
            if response.status != 200:
                raise GreeCloudError(f"HTTP {response.status}: {response.reason}")

            json_data = await response.json()
            return json_data["enRes"]

    async def login(self) -> CloudCredentials:
        """Login to Gree Cloud.

        Returns:
            CloudCredentials with user_id and token

        """

        # IMPORTANT: Use UTC time to match server time
        date = datetime.now(UTC)  # pylint: disable=home-assistant-enforce-utcnow
        t = date.strftime("%Y-%m-%d %H:%M:%S")

        # Hash password using Gree's algorithm
        h = self._md5(self._md5(self.password) + self.password)
        psw = self._md5(h + t)

        body = json.dumps(
            self._prepare_body(
                {
                    "psw": psw,
                    "t": t,
                    "user": self.username,
                },
                date,
                ["user", "psw", "t"],
            )
        )

        encrypted_response = await self._send_request("/App/UserLoginV2", body)
        decrypted = self._decrypt(base64.b64decode(encrypted_response))

        _LOGGER.debug("Login response (decrypted): %s", decrypted)

        data = json.loads(decrypted)
        _LOGGER.debug("Login response (parsed): %s", data)

        # Check for error response
        if "r" in data and data["r"] != 200:
            raise GreeCloudLoginError(
                f"Login failed: {data.get('msg', 'Unknown error')}"
            )

        # Handle different response formats
        if "uid" in data:
            user_id = data["uid"]
            token = data["token"]
        elif "data" in data and isinstance(data["data"], dict):
            user_id = data["data"].get("uid")
            token = data["data"].get("token")
        else:
            raise GreeCloudError(f"Unexpected login response format: {data}")

        if not user_id or not token:
            raise GreeCloudLoginError(f"Missing uid or token in response: {data}")

        self.user_id = user_id
        self.token = token

        _LOGGER.info("Successfully logged in as user %s", self.user_id)

        return CloudCredentials(user_id=user_id, token=token)

    async def get_homes(self) -> list[CloudHome]:
        """Get list of homes.

        Returns:
            List of CloudHome objects

        """

        if not self.user_id or not self.token:
            raise GreeCloudError("Not logged in. Call login() first.")

        date = datetime.now(UTC)  # pylint: disable=home-assistant-enforce-utcnow

        body = json.dumps(
            self._prepare_body(
                {
                    "token": self.token,
                    "uid": self.user_id,
                },
                date,
                ["token", "uid"],
            )
        )

        encrypted_response = await self._send_request("/App/GetHomes", body)
        decrypted = self._decrypt(base64.b64decode(encrypted_response))
        data = json.loads(decrypted)
        _LOGGER.debug(data)

        homes = [CloudHome(id=h["id"], name=h["name"].strip()) for h in data["home"]]

        _LOGGER.info("Found %d homes", len(homes))
        return homes

    async def get_devices(self, home_id: int) -> list[CloudDeviceInfoResponse]:
        """Get list of devices in a home.

        Args:
            home_id: ID of the home

        Returns:
            List of CloudDeviceInfo objects

        """

        if not self.user_id or not self.token:
            raise GreeCloudError("Not logged in. Call login() first.")

        date = datetime.now(UTC)  # pylint: disable=home-assistant-enforce-utcnow

        body = json.dumps(
            self._prepare_body(
                {
                    "token": self.token,
                    "homeId": home_id,
                    "uid": self.user_id,
                },
                date,
                ["token", "uid", "homeId"],
            )
        )

        encrypted_response = await self._send_request(
            "/App/GetDevsInRoomsOfHomeV2", body
        )
        decrypted = self._decrypt(base64.b64decode(encrypted_response))
        data = json.loads(decrypted)
        _LOGGER.debug(data)

        devices = []
        for room in data["rooms"]:
            for dev in room["devs"]:
                device = CloudDeviceInfoResponse.model_validate(dev)
                devices.append(device)

        _LOGGER.info("Found %d devices in home %d", len(devices), home_id)
        return devices

    async def get_all_devices(self) -> list[CloudDeviceInfoResponse]:
        """Get all devices from all homes.

        Filters out duplicate devices with same key. When duplicates exist,
        keeps the one with MAC ending in '00' (responsive) and hides the one without.

        Returns:
            List of all CloudDeviceInfo objects across all homes (deduplicated)

        """
        homes = await self.get_homes()
        all_devices: list[CloudDeviceInfoResponse] = []

        for home in homes:
            devices = await self.get_devices(home.id)
            all_devices.extend(devices)

        # Filter duplicates: when same key exists with MACs where one ends with '00'
        filtered_devices = self._filter_duplicate_devices_complete(all_devices)

        if len(filtered_devices) < len(all_devices):
            _LOGGER.info(
                "Filtered out %d duplicate device(s)",
                len(all_devices) - len(filtered_devices),
            )

        _LOGGER.info(
            "Found total of %d devices across all homes", len(filtered_devices)
        )
        return filtered_devices

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            _LOGGER.debug("HTTP session closed")

    async def __aenter__(self) -> Self:
        """Async context manager enter."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Async context manager exit."""
        await self.close()
        return False

    def _filter_duplicate_devices_complete(
        self, devices: list[CloudDeviceInfoResponse]
    ) -> list[CloudDeviceInfoResponse]:
        """Filter out duplicate devices with same key.

        When devices share the same encryption key but have different MACs
        (one normal, one ending with '00'), keep only the one with '00'.
        The device without '00' suffix doesn't respond to commands.

        Args:
            devices: List of devices to filter

        Returns:
            Filtered list without duplicates

        """
        # Group devices by encryption key
        key_groups: dict[str, list[CloudDeviceInfoResponse]] = {}
        for device in devices:
            if device.key not in key_groups:
                key_groups[device.key] = []
            key_groups[device.key].append(device)

        filtered = []
        for group in key_groups.values():
            if len(group) == 1:
                # No duplicates, keep as is
                filtered.append(group[0])
            else:
                # Multiple devices with same key - filter by MAC
                # Prefer device >12 chars and ending in "00"
                devices_over_12 = [
                    d for d in group if len(d.mac) > 12 and d.mac.endswith("00")
                ]
                devices_under_12 = [
                    d for d in group if not (len(d.mac) > 12 and d.mac.endswith("00"))
                ]

                if devices_over_12:
                    # Keep device(s) with '00' suffix
                    filtered.extend(devices_over_12)
                    if devices_under_12:
                        _LOGGER.debug(
                            "Filtering out non-responsive device(s) without '00': %s",
                            [d.mac for d in devices_under_12],
                        )
                else:
                    # No device with '00' found, keep all (shouldn't happen but be safe)
                    filtered.extend(group)

        return filtered


async def gree_get_latest_firmware_info(
    region: GreeRegion,
    firmware_code: str,
    timeout: float = 10.0,
) -> FirmwareInfoResponse | None:
    """Fetch firmware information from a Gree firmware server."""
    endpoint = f"{CLOUD_SERVERS[region]}/wifiModule/Lastversion"

    async with (
        aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session,
        session.get(
            endpoint,
            params={"firmwareCode": firmware_code},
        ) as response,
    ):
        response.raise_for_status()
        data = await response.json()

    if data.get("r") != 200:
        return None

    return FirmwareInfoResponse.model_validate(data)
