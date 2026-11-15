from enum import Enum


class DriftType(str, Enum):
    D0 = "D0"  # None (control)
    D1 = "D1"  # Numeric format (10 -> 10.0 / "10.00" / "$10")
    D2 = "D2"  # Structure noise (key order, whitespace, extra optional fields)
    D3 = "D3"  # Free-text paraphrase (reworded subject or body)
    D4 = "D4"  # Volatile fields (regenerated reference, timestamp, nonce, uuid)
    D5 = "D5"  # Encoding aliases (email case, casing)
    D6 = "D6"  # Structural (stretch: batch vs single)


class NegativeType(str, Enum):
    N1 = "N1"  # Different amount (distinct legitimate action)
    N2 = "N2"  # Different recipient (distinct legitimate action)
    N3 = "N3"  # Ambiguous control (explicit second identical request)
