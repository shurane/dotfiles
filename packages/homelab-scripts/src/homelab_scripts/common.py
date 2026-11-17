"""Common helper functions for homelab media processing scripts."""

from __future__ import annotations

__all__ = ["parse_range_spec"]


def parse_range_spec(range_str: str, max_all: int = 600) -> set[int]:
    """Parse comma/hyphen range string like '1', '1,2,3', '1-20', or 'all' into a set of integers."""
    cleaned = range_str.strip().lower()
    if cleaned in ("all", "*"):
        return set(range(1, max_all + 1))

    numbers: set[int] = set()
    for part in cleaned.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start, end = int(start_s), int(end_s)
            if start > end:
                raise ValueError(f"Invalid inverted range: '{part}' (start {start} must be <= end {end})")
            numbers.update(range(start, end + 1))
        else:
            try:
                numbers.add(int(part))
            except ValueError as err:
                raise ValueError(f"Invalid range specification: invalid literal for int: {part}") from err
    return numbers

