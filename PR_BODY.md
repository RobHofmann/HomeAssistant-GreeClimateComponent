Fixes half-degree setpoints for units behind a Gree cloud controller, i.e. the ones that report `Add0.1`.

These gateways don't use `TemRec` and they ignore `Add0.5`. The fraction lives in `Add0.1` as a tenths digit, so 27.5 °C is `SetTem=27, Add0.1=5`. On 4.0.16 the packet goes out as `SetTem=27, TemRec=1`, the unit accepts it and stays at 27 °C, and the next poll reports 27 °C again. Only whole degrees work. I read through #237 and #319, both ended up pointing at this same encoding for these models.

What the patch does:

- probes `Add0.1` once in `SyncState()`, the same way `Add0.5` is probed
- when the device answers with a number, reads the target back as `SetTem + Add0.1 / 10` and writes `{SetTem, Add0.1}`, with `TemRec` forced to 0 so only one field carries the fraction
- lifts the target step from 1.0 to 0.5 once, otherwise the slider can't reach a half degree (the step number entity still overrides it)
- units that don't answer the probe keep the `TemRec` / `Add0.5` behaviour as it is today

One thing worth knowing: I didn't gate this on `TemRec` being empty. The gateway also answers `Add0.5` with 1, so any condition that mentions `Add0.5` would rule out the units that need the fix. A numeric `Add0.1` answer seems to be the only signal specific to this encoding.

Tested on six indoor units behind one cloud controller, HA 2026.10.4, running since Oct 31. 27.5 °C set from HA reads back as 27.5 and survives a restart, 24.5 and 26.5 hold across polls. Encoding round-trips 16 to 30 °C in 0.5 steps, empty answers fall back without raising.

master has no test suite, so this is hardware-verified only. Happy to move the helpers into `helpers.py` with tests, or split the step change out, if that's easier to review.

Separate commit on the same branch: `AssHt` still uses `is not None` while the other capability probes in `SyncState()` use `not in (None, "")`. On a gateway that answers unsupported fields with an empty string, every unit gets an auxiliary-heat select that does nothing. One line.
