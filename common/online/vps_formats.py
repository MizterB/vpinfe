"""What VPS calls the program a table is for, in words a person would use."""

from __future__ import annotations

from common import i18n


def name(token: str) -> str:
    """`FP` as Future Pinball. A token the catalog has no words for comes back as it came,
    because VPS may file a format this build has not heard of."""
    wanted = str(token or "").strip().upper()
    if not wanted:
        return ""
    return i18n.literal_or("", f"vps.format.{wanted}", fallback=wanted)[0]
