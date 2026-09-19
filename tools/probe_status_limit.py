"""Find the status request limits of one Gree unit: column count and byte size.

Two runs against the unit, each request sent as exactly one packet:

* count: ``Pow`` repeated N times. Same prop, tiny packet, growing column count.
* size:  a fixed number of columns with long padded names. Growing packet size,
  fixed column count.

A unit can have one limit, both, or neither. Every reply is one of: answered,
EMPTY (r=200 with no data) or NO REPLY (timeout).

Run from the repo root with the devcontainer's Python, or any Python that has
``asyncio_dgram`` and ``cryptography``::

    python tools/probe_status_limit.py --host 192.168.1.50

The unit is bound with the normal library code. The probes bypass the learned
limit on purpose, so the numbers you see are the device's own.
"""

# This is a command line tool: it prints, and it is not a package.
# ruff: noqa: INP001, T201

import argparse
import asyncio
from collections.abc import Callable
import json
import logging
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "custom_components"))

from gree_custom.aiogree.api import (
    _create_get_status_pack,
    _create_payload,
    gree_discover_device_local,
    gree_get_response_pack,
    gree_process_status_pack,
)
from gree_custom.aiogree.cipher import EncryptionVersion, get_cipher
from gree_custom.aiogree.device import GreeDevice
from gree_custom.aiogree.errors import GreeError
from gree_custom.aiogree.transport_udp import GreeUdpTransport

PROBE_TIMEOUT = 5.0
COUNT_STEPS = (10, 20, 25, 28, 29, 30, 31, 32, 35, 40, 50, 60)
SIZE_TARGETS = (300, 400, 500, 600, 700, 800, 900, 1000, 1200)
SIZE_COLUMNS = 10


def pack_bytes(mac: str, cols: list[str]) -> int:
    """Return the unencrypted size of a status pack with these columns."""
    return len(json.dumps(_create_get_status_pack(mac, cols)).encode())


def padded_columns(mac: str, target_bytes: int) -> list[str]:
    """Return SIZE_COLUMNS distinct column names whose pack is about target_bytes."""
    cols = ["Pow", "Mod", "SetTem", "TemSen"]
    fillers = SIZE_COLUMNS - len(cols)
    base = pack_bytes(mac, cols + [f"X{i:02d}" for i in range(fillers)])
    pad = max(0, (target_bytes - base) // fillers)
    return cols + [f"X{i:02d}" + "y" * pad for i in range(fillers)]


async def probe(dev: GreeDevice, cols: list[str], uid: int) -> str:
    """Send one status packet with these columns and classify the reply."""
    transport = dev.transport
    if transport is None:
        return "NO TRANSPORT"
    mac_ctrl = dev.mac_address_controller
    version = dev.encryption_version or EncryptionVersion.V1
    cipher = get_cipher(version, dev.encryption_key)
    payload = _create_payload(
        _create_get_status_pack(dev.mac_address, cols), "pack", 0, mac_ctrl, uid
    )
    try:
        pack = await gree_get_response_pack(
            mac_ctrl, payload, cipher, transport, 1, PROBE_TIMEOUT
        )
    except GreeError:
        return "NO REPLY"
    result = gree_process_status_pack(pack, cols)
    if not result.prop_values:
        return "EMPTY"
    return f"answered {len(result.prop_values)}"


async def bind(host: str, port: int, mac: str | None, uid: int) -> GreeDevice:
    """Discover (if needed) and bind the unit with the normal library code."""
    if mac is None:
        found = await gree_discover_device_local(host, 5, uid)
        if not found:
            raise SystemExit(f"No Gree unit answered a scan at {host}")
        mac = found[0].mac
        print(f"discovered {mac} ({found[0].name})")
    dev = GreeDevice(name="probe", mac_addr=mac, user_id=uid)
    transport = GreeUdpTransport(host, port, max_retries=3, timeout=5.0)
    await dev.bind_with_transport(
        preferred_local_version=None,
        local_controller_mac=mac,
        local_transport=transport,
        mqtt_controller_mac="",
        mqtt_transport=None,
    )
    print(f"bound, encryption v{dev.encryption_version}\n")
    return dev


async def series(
    dev: GreeDevice,
    uid: int,
    steps: tuple[int, ...],
    make_cols: Callable[[int], list[str]],
    describe: Callable[[int, list[str]], str],
) -> int | None:
    """Probe one series of growing requests. Return the step of the first failure."""
    first_failure: int | None = None
    silent = 0
    for step in steps:
        cols = make_cols(step)
        verdict = await probe(dev, cols, uid)
        print(f"  {describe(step, cols)}  {verdict}")
        if verdict.startswith("answered"):
            silent = 0
            continue
        if first_failure is None:
            first_failure = step
        silent += verdict == "NO REPLY"
        if silent >= 2:
            print("  (two silent replies in a row, stopping this run)")
            break
    return first_failure


async def run(host: str, port: int, mac: str | None, uid: int) -> None:
    """Run both probes and print a verdict."""
    dev = await bind(host, port, mac, uid)
    device_mac = dev.mac_address

    print("count run: 'Pow' repeated N times in one packet")
    count_limit = await series(
        dev,
        uid,
        COUNT_STEPS,
        lambda n: ["Pow"] * n,
        lambda n, cols: f"N={n:>3}  {pack_bytes(device_mac, cols):>5} bytes",
    )

    print(f"\nsize run: {SIZE_COLUMNS} columns with padded names, growing bytes")
    size_limit = await series(
        dev,
        uid,
        SIZE_TARGETS,
        lambda target: padded_columns(device_mac, target),
        lambda _, cols: f"{pack_bytes(device_mac, cols):>5} bytes  N={len(cols):>2}",
    )

    print("\nverdict")
    if count_limit is not None:
        print(f"  column limit: the first failure was at {count_limit} columns")
    else:
        print(f"  no column limit found up to {COUNT_STEPS[-1]} columns")
    if size_limit is not None:
        print(f"  size limit: the first failure was at about {size_limit} bytes")
    else:
        print(f"  no size limit found up to about {SIZE_TARGETS[-1]} bytes")


def main() -> None:
    """Parse arguments and run."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--host", required=True, help="IP address of the unit")
    parser.add_argument("--port", type=int, default=7000)
    parser.add_argument("--mac", help="MAC of the unit, lower case, no separators")
    parser.add_argument("--uid", type=int, default=0)
    parser.add_argument("--debug", action="store_true", help="Show library debug logs")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.CRITICAL)
    asyncio.run(run(args.host, args.port, args.mac, args.uid))


if __name__ == "__main__":
    main()
