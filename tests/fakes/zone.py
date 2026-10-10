"""A fake Gree zone controller: one ducted unit and its zones behind one WiFi module.

Seen on a real LE60-13/GH zone controller with a ME31-00/C13 WiFi module,
firmware `362001062617+U-W05SAV1.27.bin` (see docs/protocol.md):

- It is a gateway. It only answers the subDev form of the sub-device list and
  calls every unit "zone". The ducted unit has model id 5000 and MAC suffix
  `00`. The zones have model id 5001 and suffixes `01` to `08`.
- Each sub-unit answers only its own columns. The ducted unit has `Pow`, `Mod`,
  `WdSpd` and `AllErr`. A zone has `Pow`, `Mod`, `WdSpd` and `StTem`. `Mod`
  and `WdSpd` of a zone follow the ducted unit.
- `Mod` is 1 Cool, 2 Heat, 3 Dry, 4 Fan, 5 Auto. Turbo is `WdSpd` 6.
- `StTem` is the zone target temperature in degrees Celsius minus 16.
- Every sub-unit answers the info columns with the name of the controller.
- A status request with too many columns gets an empty result.
"""

from typing import Any, override

from aiogree.api import SubListForm

from .vrf import FakeVrfGateway

ZONE_CONTROLLER_MAC = "9424b8c0ffee"
ZONE_CONTROLLER_NAME = "GR-ZCntrlr_5000_02_ffee_EC"


class FakeZoneController(FakeVrfGateway):
    """A zone controller with a ducted unit and `zones` zones."""

    def __init__(
        self,
        mac: str = ZONE_CONTROLLER_MAC,
        name: str = ZONE_CONTROLLER_NAME,
        *,
        zones: int = 4,
        **kwargs: Any,
    ) -> None:
        """Set up the controller.

        Args:
            mac: MAC of the controller.
            name: Name in the scan reply and in the info columns.
            zones: How many zones the controller has.
            kwargs: Anything FakeVrfGateway accepts.

        """
        kwargs.setdefault("forms", {SubListForm.SUB_DEV: None})
        kwargs.setdefault("max_columns", 25)
        super().__init__(mac=mac, name=name, sub_count=zones + 1, **kwargs)

        self.ac_unit = f"{mac}00"
        self.zone_macs = [f"{mac}{index:02d}" for index in range(1, zones + 1)]
        self.units: dict[str, dict[str, Any]] = {
            mac: {"Pow": 0, "Mod": 4, "WdSpd": 5},
            self.ac_unit: {"Pow": 1, "Mod": 4, "WdSpd": 5, "AllErr": 0},
        }
        for zone in self.zone_macs:
            self.units[zone] = {"Pow": 1, "Mod": 4, "WdSpd": 5, "StTem": 2}
        self.info: dict[str, Any] = {
            "name": name,
            "mid": "3017",
            "hid": "362001062617+U-W05SAV1.27.bin",
            "host": "au.dis.gree.com",
            "ver": "V1.2.1",
        }

    @override
    def build_scan_info(self) -> dict[str, Any]:
        """Answer the scan as the real controller does. Note: there is no cid."""
        return {
            "t": "dev",
            "bc": "gree",
            "catalog": "gree",
            "mid": "50",
            "lock": 0,
            "model": "gree",
            "name": self.name,
            "series": "gree",
            "vender": "2",
            "ver": "V1.2.1",
            "brand": "gree",
            "mac": self.mac,
            "subCnt": self.sub_count,
        }

    @override
    def sub_devices(self, form: SubListForm) -> list[dict[str, str]]:
        """Return the ducted unit and the zones, each called "zone"."""
        units = [{"mac": self.ac_unit, "mid": "5000", "name": "zone"}]
        units += [
            {"mac": zone, "mid": "5001", "name": "zone"} for zone in self.zone_macs
        ]
        return units

    @override
    def build_status(self, pack: dict[str, Any]) -> dict[str, Any]:
        """Answer the columns the addressed unit has, and the info columns."""
        target: str = pack.get("mac", self.mac)
        cols: list[str] = list(pack.get("cols", []))

        if self.max_columns is not None and len(cols) > self.max_columns:
            return {"t": "dat", "mac": target, "r": 200, "cols": [], "dat": []}

        values = {**self.info, **self.units.get(target, {})}
        answered = [col for col in cols if col in values]
        return {
            "t": "dat",
            "mac": target,
            "r": 200,
            "cols": answered,
            "dat": [values[col] for col in answered],
        }

    @override
    def build_command_result(self, pack: dict[str, Any]) -> dict[str, Any]:
        """Apply a command to the addressed unit. The zones follow the ducted unit."""
        target: str = pack.get("sub", self.mac)
        options = list(pack.get("opt", []))
        values = list(pack.get("p", []))

        unit = self.units.get(target, {})
        for option, value in zip(options, values, strict=False):
            if option in unit:
                unit[option] = value
                if target == self.ac_unit and option in ("Mod", "WdSpd"):
                    for other in (self.mac, *self.zone_macs):
                        self.units[other][option] = value

        return {"t": "res", "mac": target, "r": 200, "opt": options, "p": values}
