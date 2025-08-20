"""Helper functions and classes for Gree integration."""

from .const import TEMSEN_OFFSET


class TempOffsetResolver:
    """
    Detect whether this sensor reports temperatures in °C
    or in (°C + 40).  Continues to check, and bases decision
    on historical min and max raw values, since there are extreme
    cases which would result in a switch. Two running values are
    stored (min & max raw).

    Note: This could be simplified by just using 40C as a max point
    for the unoffset case and a min point for the offset case. But
    this doesn't account for the marginal cases around 40C as well.

    Example:

    if raw < 40:
        return raw
    else:
        return raw - 40
    """

    def __init__(
        self,
        indoor_min: float = -15.0,  # coldest plausible indoor °C
        indoor_max: float = 40.0,  # hottest plausible indoor °C
        offset: float = TEMSEN_OFFSET,  # device's fixed offset
        margin: float = 2.0,  # tolerance before "impossible":
    ):
        self._lo_lim = indoor_min - margin
        self._hi_lim = indoor_max + margin
        self._offset = offset

        self._min_raw: float | None = None
        self._max_raw: float | None = None
        self._has_offset: bool | None = None  # undecided until True/False

    def __call__(self, raw: float) -> float:
        if self._min_raw is None or raw < self._min_raw:
            self._min_raw = raw
        if self._max_raw is None or raw > self._max_raw:
            self._max_raw = raw
        self._evaluate()  # evaluate every time, so it can change it's mind as needed
        return raw - self._offset if self._has_offset else raw

    def _evaluate(self) -> None:
        lo, hi = self._min_raw, self._max_raw
        penalty_no = self._penalty(lo, hi)
        penalty_off = self._penalty(lo - self._offset, hi - self._offset)
        if penalty_no == penalty_off:
            return  # still ambiguous – keep collecting data
        self._has_offset = penalty_off < penalty_no

    def _penalty(self, lo: float, hi: float) -> float:
        pen = 0.0
        if lo < self._lo_lim:
            pen += self._lo_lim - lo
        if hi > self._hi_lim:
            pen += hi - self._hi_lim
        return pen


def gree_f_to_c(desired_temp_f):
    # Convert to fractional C values for AC
    # See: https://github.com/tomikaa87/gree-remote
    SetTem = round((desired_temp_f - 32.0) * 5.0 / 9.0)
    TemRec = (int)((((desired_temp_f - 32.0) * 5.0 / 9.0) - SetTem) > -0.001)

    return SetTem, TemRec


def gree_c_to_f(SetTem, TemRec):
    # Convert SetTem back to the minimum and maximum Fahrenheit before rounding
    # We consider the worst case scenario: SetTem could be the result of rounding from any value in a range
    # If TemRec is 1, it indicates the value was closer to the upper range of the rounding
    # If TemRec is 0, it indicates the value was closer to the lower range

    if TemRec == 1:
        # SetTem is closer to its higher bound, so we consider SetTem as the lower limit
        min_celsius = SetTem
        max_celsius = SetTem + 0.4999  # Just below the next rounding threshold
    else:
        # SetTem is closer to its lower bound, so we consider SetTem-1 as the potential lower limit
        min_celsius = SetTem - 0.4999  # Just above the previous rounding threshold
        max_celsius = SetTem

    # Convert these Celsius values back to Fahrenheit
    min_fahrenheit = (min_celsius * 9.0 / 5.0) + 32.0
    max_fahrenheit = (max_celsius * 9.0 / 5.0) + 32.0

    int_fahrenheit = round((min_fahrenheit + max_fahrenheit) / 2.0)

    return int_fahrenheit


def encode_temp_c(T):
    """
    Used for encoding 1/2 degree Celsius values.
    Encode any floating‐point temperature T into:
      ‣ temp_int: the integer (°C) portion of the nearest 0.0/0.5 step,
      ‣ half_bit: 1 if the nearest step has a ".5", else 0.

    This "finds the closest multiple of 0.5" to T, then:
      n = round(T * 2)
      temp_int = n >> 1      (i.e. floor(n/2))
      half_bit = n & 1       (1 if it's an odd half‐step)
    """
    # 1) Compute "twice T" and round to nearest integer:
    #    math.floor(T * 2 + 0.5) is equivalent to rounding ties upward.
    n = int(round(T * 2))

    # 2) The low bit of n says ".5" (odd) versus ".0" (even):
    TemRec = n & 1

    # 3) Shifting right by 1 gives floor(n/2), i.e. the integer °C of that nearest half‐step:
    SetTem = n >> 1

    return SetTem, TemRec


def decode_temp_c(SetTem: int, TemRec: int) -> float:
    """
    Given:
      SetTem = the "rounded-down" integer (⌊T⌋ or for negatives, floor(T))
      TemRec = 0 or 1, where 1 means "there was a 0.5"
    Returns the original temperature as a float.
    """
    return SetTem + (0.5 if TemRec else 0.0)
