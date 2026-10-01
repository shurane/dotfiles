"""Convert external timestamps to instants, requiring explicit DST decisions."""

from whenever import Instant, OffsetDateTime, PlainDateTime


def parse_timestamp(value: str, timezone: str = "UTC") -> Instant:
    iso = value.replace(" ", "T", 1)
    # The date contains '-', so inspect only the portion after the date.
    if iso.endswith("Z") or "+" in iso[10:] or "-" in iso[10:]:
        return OffsetDateTime.parse_iso(iso).to_instant()
    return PlainDateTime.parse_iso(iso).assume_tz(timezone, disambiguate="raise").to_instant()


def soju_timestamp(value: Instant) -> str:
    """Soju's database format has exactly three fractional digits (milliseconds)."""
    return value.format_iso(unit="millisecond")
