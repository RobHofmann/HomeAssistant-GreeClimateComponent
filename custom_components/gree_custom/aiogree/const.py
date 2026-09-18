"""Constants for the aiogree."""

MAX_PACK_SIZE = 512

# Some firmwares cap a status request by column count, not by size.
# Measured on a U-CS532Z V3.75 unit: 29 props answered, 30 returned an empty
# result and 31 or more got no reply at all, independent of the pack size.
# The limit differs per firmware, so it is learned per session (see
# DeviceApiClient) instead of fixed. Batches never go below this size.
MIN_PACK_PROPS = 5

# A prop every unit answers. When a request holds it and the reply is empty,
# the request had too many columns.
STATUS_CANARY_PROP = "Pow"

# Probe requests (learning the column limit) wait this long, once, instead of
# the configured device timeout and retries, so a unit that goes silent on a
# too large request does not stall the bind.
PROBE_TIMEOUT = 5.0

# Diagnostic sweeps ask one prop per request. Some props are never answered by
# some firmwares (seen: ElcDatDte, ElcDatHor, ElcDatMth), and a few of those in a
# row are normal. This many in a row means the device stopped talking.
MAX_UNANSWERED_IN_A_ROW = 5

MIN_TEMP_C = 16
MAX_TEMP_C = 30

MIN_TEMP_F = 61
MAX_TEMP_F = 86

MIN_HUM_COOL_P = 40
MAX_HUM_COOL_P = 80

MIN_HUM_DRY_P = 30
MAX_HUM_DRY_P = 70

DEFAULT_DEVICE_USERID = 0
DEFAULT_DEVICE_PORT = 7000
