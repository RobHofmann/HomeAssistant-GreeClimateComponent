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
- The limit differs per firmware, so `DeviceApiClient` learns it per session instead of using a constant. The first status goes out as one request. If the reply is empty and the request held `STATUS_CANARY_PROP` (`Pow`, which every unit answers), the request was too big: the batch size is halved and the same props are asked again, down to `MIN_PACK_PROPS`. The size that worked is kept. A later request that sits between the known good and the known bad size is tried as one packet once, so a device that can take more gets back to one request per poll.
- Probe requests (the first one of a session and the single packet tries) use one attempt and `PROBE_TIMEOUT` (5 s) instead of the configured timeout and retries, so a unit that goes silent on a too large request does not stall the bind. Every retry after a shrink uses the normal retries.
- A unit can have both limits at once. The `U-CS532Z(LT)V3.75` unit caps at 29 columns and also stops replying at about 800 bytes in one packet, which matches the "about 760 bytes unencrypted" note above `MAX_PACK_SIZE`. The 512 byte cap keeps normal polls far below the size limit; the learned column limit handles the other one.
- To measure a unit, run `tools/probe_status_limit.py --host <ip>` from the repo root. It sends `Pow` repeated N times (growing count, tiny packets) and then 10 columns with padded names (growing bytes, fixed count), each as exactly one packet, and prints where each run first fails. See [development.md](development.md#tools).
- A device may return fewer columns than asked. That is normal. The missing columns are reported in `StatusResult.missing_props`. Because of this, values and columns can only be matched inside one response, never across responses.
- A device may return `r=200` with empty `cols` and `dat`. That means "no data", not "nothing is supported". `_remove_unsupported_props()` raises `GreeProtocolError` when the very first status comes back empty, so setup fails and retries instead of leaving a device with nothing to poll.
- Some props are never answered at all, not even with an empty result. The request times out and the device is fine right after. Seen on one firmware: `ElcDatDte`, `ElcDatHor`, `ElcDatMth`. This is why the diagnostic services pass `max_attempts=1` (one timeout per ignored prop instead of timeout x retries), and why `query_props()` stops after `MAX_UNANSWERED_IN_A_ROW` (5) unanswered requests in a row.
- Request rate is not a problem. 600 back-to-back single-prop requests were answered without a drop.
- The device does not type its values. `InfoProp` values can come back as `int` (seen: `ModelType` as `32768`) while others are `str`. `gree_process_status_pack()` casts every column and value to `str` for that reason.

## Temperature

- `SetTem` is a whole number of degrees. `TemRec` adds the half degree.
- Some devices report sensor temperatures with a +40 offset. `TempOffsetResolver` in `aiogree/helpers.py` detects this from the values it sees.
- Fahrenheit uses the protocol's own lookup table, not a formula.

## Discovery and network

- Local discovery is a plain text `{"t": "scan"}` UDP broadcast. The device answers with a `dev` pack encrypted with the generic key.
- `extra_scan_networks` and `extra_scan_hosts` exist for devices on another subnet, where a broadcast does not reach. Those are probed with unicast.
- A device that does not answer the scan cannot be bound. Setup retries the scan with the normal transport retries.

## MAC addresses

MACs are written in lower case with no separators. Talking to a device needs two MACs: the device MAC (the unit to control) and the controller MAC (the unit that manages it).

- Normal units: both MACs are the same.
- VRF units, local (UDP): the device MAC is 14 characters, a normal 12 character MAC plus 2 characters, and comes from discovery. The controller MAC is a normal 12 character MAC.
- VRF units, cloud (MQTT): the device MAC is the same 14 character value. The controller MAC is the first 12 characters of it.

## Cloud

- Login and device list go over HTTPS to a regional `*grih.gree.com` host. Control goes over MQTT to the matching `mqtt-*.gree.com` broker. Both are picked from `GreeRegion`.
- The MQTT transport sends each request once. There are no retries at the transport level.
- Pushed status arrives on a `status` topic and goes through the same `gree_process_status_pack()` as polled status.
