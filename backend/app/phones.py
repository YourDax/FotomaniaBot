from __future__ import annotations

import re


def phone_digits(value: str) -> str:
    """Return national 10-digit RU number when possible, else raw digits."""
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11 and digits[0] in {"7", "8"}:
        return digits[1:]
    return digits


def normalize_phone(value: str | None) -> str | None:
    """Store Russian mobiles as +7XXXXXXXXXX; empty / no digits -> None."""
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        # Excel stores numeric cells as float: 89099695363 arrives as 89099695363.0.
        text = str(int(value))
    else:
        text = str(value).strip()
        # Strip a spurious fractional zero tail such as "89099695363.0" or "89099695363.00".
        text = re.sub(r"^(\d+)\.0+$", r"\1", text)
    if not text:
        return None
    digits = phone_digits(text)
    if len(digits) == 10:
        return f"+7{digits}"
    if not digits:
        return None
    return text
