# Protocol notes

Facts about how Gree devices behave on the wire. Most of these are not visible from the code, and several were learned from real units. Where a fact comes from one specific unit, it says so.

## Encryption

- V1 is AES-128 ECB. Binding uses the generic key `GREE_GENERIC_DEVICE_KEY_ECB`. The device answers the bind with its own key. All later packs use that key.
- V2 is AES-128 GCM with a fixed IV (`GCM_IV`) and a `tag` field in the packet.
- `EncryptionVersion.V1 = 1`, `V2 = 2`. In config, `"0"` means auto detect: try V1, then V2.
- V2 is only used locally. Over MQTT (cloud) the device always uses V1.
- A device silently drops any pack it cannot decrypt. No reply is the normal sign of a wrong key, not an error message.

## Requests and batching

- Every request is one UDP datagram with a JSON envelope and an encrypted `pack`. `transport.request_json()` does the encrypt, send, receive, decrypt.
- Status requests are split into batches in `gree_get_status()`. A batch closes when it would pass `MAX_PACK_SIZE` (512 bytes before encryption) or the column limit passed in as `max_props`, whichever comes first.
- Some firmwares cap the number of columns per request. `U-CS532Z(LT)V3.75` answers 29 columns, returns an empty result for 30, and stops replying at 31 or more. Pack size and the names of the columns play no role: `Pow` repeated 30 times in a 258 byte packet fails the same way.
- The limit differs per firmware, so `DeviceApiClient.probe_device_limits()` measures it once, right after binding. A probe asks for `STATUS_CANARY_PROP` (`Pow`, which every unit answers) plus distinct throw-away names (`X00`, `X01`, ...). Distinct names matter: a device may merge repeated names before it counts them. Each probe is one request with one attempt and `PROBE_TIMEOUT` (5 s), so a unit that goes silent on a too large request does not stall the bind.
- A probe passes when `Pow` comes back and no column with an empty name comes back. Anything else fails: no reply, an empty result, or an error. The empty name is how some firmwares mark a request they had to cut short (seen: 65 columns asked, 64 answered plus one column named `""`).
- The first probe asks for as many columns as the default poll has (`POLLED_PROPS`, 30 today: every `GreeProp` except the two beeper props). Passing that probe means no limit affects anything the component sends; it does not mean the device has no limit at all. If it passes there is no limit worth keeping and `max_props` stays `None`. If it fails, a binary search between `MIN_PACK_PROPS` and the first failing size minus one looks for the largest size that still passes. If even `MIN_PACK_PROPS` fails, the limit is set to `MIN_PACK_PROPS` and one warning is logged; the device is most likely answering nothing at all, which the empty status guard in `GreeDevice` then catches.
- The result lives on the client and is reset on unbind, so a rebind measures again. Cost: one tiny request on a device without a limit, about five on a device with one. A probe that gets no reply costs 5 s.
- A unit can have both limits at once. The `U-CS532Z(LT)V3.75` unit caps at 29 columns and also stops replying at about 800 bytes in one packet, which matches the "about 760 bytes unencrypted" note above `MAX_PACK_SIZE`. The 512 byte cap keeps normal polls far below the size limit; the measured column limit handles the other one.
- To measure a unit, run `tools/probe_status_limit.py --host <ip>` from the repo root. It sends `Pow` repeated N times (growing count, tiny packets) and then 10 columns with padded names (growing bytes, fixed count), each as exactly one packet, and prints where each run first fails. See [development.md](development.md#tools).
- A device may return fewer columns than asked. That is normal. The missing columns are reported in `StatusResult.missing_props`. Because of this, values and columns can only be matched inside one response, never across responses.
- A device may return `r=200` with empty `cols` and `dat`. That means "no data", not "nothing is supported". `_remove_unsupported_props()` raises `GreeProtocolError` when the very first status comes back empty, so setup fails and retries instead of leaving a device with nothing to poll.
- Some props are never answered at all, not even with an empty result. The request times out and the device is fine right after. Seen on one firmware: `ElcDatDte`, `ElcDatHor`, `ElcDatMth`. This is why the diagnostic services pass `max_attempts=1` (one timeout per ignored prop instead of timeout x retries). It is also why `query_props()` with `error_as_missing` checks the device after a request that gets no answer (`GreeConnectionError`). It sends one canary request for `STATUS_CANARY_PROP` (`Pow`), with at most `STATUS_CANARY_PROP_MAX_REQUESTS` (2) attempts of `PROBE_TIMEOUT` (5 s) each. If the canary gets no answer, the device stopped talking and the error is raised. If the canary is answered, the props of the failed request are reported missing and the sweep goes on. Other errors, such as a bad answer, skip the canary and also report the props as missing.
- A normal poll does not use `error_as_missing`, so it sends no canary. A request that gets no answer raises at once and marks the device unavailable. A canary there would only add up to 10 s and a warning to every poll of a unit that is switched off.
- Request rate is not a problem. 600 back-to-back single-prop requests were answered without a drop.
- The device does not type its values. `InfoProp` values can come back as `int` (seen: `ModelType` as `32768`) while others are `str`. `gree_process_status_pack()` casts every column and value to `str` for that reason.

## Temperature

- `SetTem` is a whole number of degrees. `TemRec` adds the half degree.
- Some devices report sensor temperatures with a +40 offset. `TempOffsetResolver` in `aiogree/helpers.py` detects this from the values it sees.
- Fahrenheit uses the protocol's own lookup table, not a formula.

## Discovery and network

- Local discovery is a plain text `{"t": "scan"}` UDP broadcast. The device answers with a `dev` pack encrypted with the generic key.
- Most devices put a `cid` in that `dev` pack. Some do not (seen: a Gree LE60-13/GH zone controller), so `DeviceScanInfoResponse` must not require it. Nothing reads it.
- `extra_scan_networks` and `extra_scan_hosts` exist for devices on another subnet, where a broadcast does not reach. Those are probed with unicast.
- A device that does not answer the scan cannot be bound. Setup retries the scan with the normal transport retries.

## VRF gateways

A VRF gateway is one WiFi module (seen: GR-Gcloud, firmware V3.2.M) with several indoor units behind it. It answers the scan with `subCnt` above zero. Discovery binds it with the normal bind and then asks it for the list of its units.

### One bind per controller

A transport binds once per controller MAC, not once per device. It keeps the result, a `BindingInfo` with the key, the encryption version and the cipher, in `bound_controllers`. Every device of that controller on the same transport uses it, so the sub-units of one gateway share one key and the second sub-unit sends no bind request. `connections` holds, per controller MAC, the device MACs that use the transport. The push listeners are kept per device MAC.

- `rebind(force_bind=True)` on any device of the controller binds again and replaces the `BindingInfo` for all of them. This is how a new key after a key rotation reaches every sub-unit.
- When the last device of a controller leaves the transport, its `BindingInfo` is dropped. The next device of that controller binds again.

### The sub-device list request

There are three forms of the request. Different WiFi module firmwares answer different forms, and some gateways return a different subset of units in each form. All three were seen on real hardware in PR 507 of the 4.x line.

| Form (`SubListForm`) | Envelope `t`, `i` | Pack | Key, request and reply |
|---|---|---|---|
| `device-key` | `pack`, `0` | `{"mac": <gw>, "t": "subList", "i": 0}` | the bound device key |
| `generic-key` | `subList`, `1` | `{"mac": <gw>, "i": 1}` | the generic key |
| `subDev` | `pack`, `0` | `{"cid": <gw>, "i": 0, "mac": <gw>, "t": "subDev"}` | the bound device key |

- The `generic-key` form is answered with the generic key, as a scan or a bind is, so its request uses the generic key too. The other two forms use the bound device key both ways. A GR-Gcloud V3.2.M gateway ignores the request pack of the `generic-key` form: a pack encrypted with the device key, with the generic key and with a random key all got the same answer, readable with the generic key (probe in PR 507). No gateway is known that reads the pack of this form.
- The `subDev` form is for older W06 class modules (seen: `362001067012+U-W06AV30.bin`, ver `V1.1.0.0`). They do not answer `subList` at all.
- With V1, `_get_sub_devices_list()` sends all three forms in the order of the table and joins the lists by `mac`, in the order the units were first seen. On the GR-Gcloud V3.2.M gateway from PR 507 the counts were device key 4, generic key 3, subDev 4, joined 4. One debug line per gateway shows the count per form and the joined count.
- With V2 (GCM) only the `device-key` form is sent. It is the only form known to work with V2.
- The list is at the top level of the reply on some firmwares and inside the pack on others. Both are read.
- A form that gets no answer, or an answer that cannot be decrypted or holds no list, is skipped. Each form uses the retries and the timeout of the transport. With the discovery defaults (2 attempts, 2 s) a silent form costs about 4.5 s, so a gateway that answers only the last form takes about 9 s longer.
- If no form answers, one warning is logged and the gateway gives no units. Discovery of the other devices goes on. If the joined list has another length than `subCnt`, a warning says so.
- Before this, the request was one hybrid form: envelope `subList` with `i: 0` and the pack of the `generic-key` form, with the reply read with the device key. It was never confirmed on hardware, and it is no longer sent.
- Discovery handles the scan replies side by side (`asyncio.gather`), so gateways do not wait for each other. Each gateway gets its own `GreeUdpTransport`, which uses a connected socket, so a reply from one gateway cannot reach the request of another.

### Stale state after a command

A gateway keeps a cached copy of the state of every indoor unit. For a few seconds after a command it can answer a status request from that cache, with the old values. Without a guard, the UI would jump back to the old value.

- After a successful command to a sub-unit, `push_device_status()` calls `DeviceState.hold()` with the values it sent. While a prop is held, `get()` returns the sent value instead of the reported one.
- A hold ends when the device reports the sent value. That check uses the value the device reported, never the held value.
- A hold also ends after `HELD_VALUE_TTL` (8 s) seconds. After that the reported value wins, so a command the device rejected is not shown for ever.
- Props that are not polled, like the beeper, are not held, because they are never reported.
- Only sub-units are held (`GreeDevice.is_sub_unit`, true when the device MAC differs from the controller MAC). The stale cache was only seen on VRF gateways. A standalone unit is not held, because a hold has a cost there: when the unit corrects a value it cannot take, for example a swing mode it does not support, it reports its own value, and a hold would keep the refused value on screen for up to 8 s.
- If a standalone unit or the MQTT transport turns out to cache as well, the UI shows the old value for a moment after a command, as it did before the hold existed. For every device, `push_device_status()` logs at debug level when the read right after a command does not report the sent value, with the transport and whether it is a sub-unit. That line is how to find out, before the hold is extended.
- While a hold is open after a command, the coordinator polls again every 2 s (`FOLLOW_UP_REFRESH_DELAY`), so the UI shows the confirmed value soon instead of at the next scan interval. The polls stop when the device confirms, or with the first poll after the hold ends. That poll shows what the device really reports, so a rejected command is visible within about 8 s. A standalone unit is never held, so it gets no extra poll.

## Zone controllers

A zone controller (seen: LE60-13/GH with a ME31-00/C13 WiFi module, firmware `362001062617+U-W05SAV1.27.bin`) drives the dampers of a ducted unit. It answers the scan like a VRF gateway, with `subCnt` above zero, so discovery handles it the same way. Its sub-units are not indoor units, though.

- The scan reply has no `cid`, see [Discovery and network](#discovery-and-network).
- It answers only the `subDev` form of the sub-device list. Every unit in the list is called `zone`. The ducted unit has model id `5000` and MAC suffix `00`. The zones have model id `5001` and suffixes `01` to `08`. Discovery names them `AC unit` and `Zone 1`, `Zone 2` and so on.
- A sub-unit answers the info request with the name of the controller, which starts with `GR-ZCntrlr`. `GreeDevice._detect_zone_role()` uses that and the MAC suffix to set `zone_role` after the info fetch. A zone also gets `StTem` added to its poll.
- The ducted unit answers `Pow`, `Mod`, `WdSpd` and `AllErr`, nothing more. `Pow` of the ducted unit is the power of the whole system. The zones keep their own `Pow` while it is off, and get it back when it is turned on.
- `Mod` uses its own numbers: 1 Cool, 2 Heat, 3 Dry, 4 Fan, 5 Auto (`ZONE_CONTROLLER_MODES`). Read with the normal numbers, Fan shows as Heat and Auto raises. `operation_mode` and `set_operation_mode()` convert for every unit with a zone role.
- There is no `Tur` column. Turbo is `WdSpd` 6, only in Cool and Heat. Dry forces `WdSpd` 1.
- A zone answers `Pow` (the damper), `StTem` (its target temperature) and a copy of `Mod` and `WdSpd` of the ducted unit. `StTem` is the temperature in degrees Celsius minus 16 (`ZONE_TEMPERATURE_OFFSET`), so 0 to 14 for 16 to 30 degrees. The controller itself also answers `StTem1` to `StTem8`.
- The full list of columns is a table in the WiFi module firmware. There is no column for the room temperature of a zone, in any released firmware, so it cannot be shown.
- The status column limit measured by `probe_device_limits()` is 29. Requests far above the limit (about 40 columns and more) made the module reboot.

## MAC addresses

MACs are written in lower case with no separators. Talking to a device needs two MACs: the device MAC (the unit to control) and the controller MAC (the unit that manages it).

- Normal units: both MACs are the same.
- VRF units, local (UDP): the device MAC is 14 characters, a normal 12 character MAC plus 2 characters, and comes from discovery. The controller MAC is a normal 12 character MAC.
- VRF units, cloud (MQTT): the device MAC is the same 14 character value. The controller MAC is the first 12 characters of it.

## Cloud

- Login and device list go over HTTPS to a regional `*grih.gree.com` host. Control goes over MQTT to the matching `mqtt-*.gree.com` broker. Both are picked from `GreeRegion`.
- The MQTT transport sends each request once. There are no retries at the transport level.
- Pushed status arrives on a `status` topic and goes through the same `gree_process_status_pack()` as polled status.
