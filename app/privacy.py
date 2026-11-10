"""Reject obvious direct identifiers before storing or forwarding contract text."""

import re


# shortcut: Patterns miss names, addresses and account numbers; add reviewed client-side checks before promising complete masking.
DIRECT_IDENTIFIER = re.compile(
    r"\b\d{6}\s*[-]?\s*[1-8]\d{6}\b"  # resident registration number
    r"|\b01[016789]\s*[-.]?\s*\d{3,4}\s*[-.]?\s*\d{4}\b"  # mobile phone
    r"|\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"
)


def has_direct_identifier(text: str) -> bool:
    return bool(DIRECT_IDENTIFIER.search(text))
