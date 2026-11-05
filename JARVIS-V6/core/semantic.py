from __future__ import annotations

import hashlib
import math

from .retrieval import normalize, terms


def _features(text: str, dimensions: int = 256) -> dict[int, float]:
    clean = normalize(text)
    values: dict[int, float] = {}
    tokens = terms(clean, 2)
    for token in tokens:
        units = {token}
        padded = f"^{token}$"
        units.update(padded[index:index + 3] for index in range(max(0, len(padded) - 2)))
        for unit in units:
            digest = hashlib.blake2b(unit.encode("utf-8"), digest_size=4).digest()
            slot = int.from_bytes(digest, "big") % dimensions
            values[slot] = values.get(slot, 0.0) + (2.0 if unit == token else 0.55)
    return values


def similarity(left: str, right: str) -> float:
    """Deterministic local semantic-ish similarity without a model download.

    Word and character features handle spelling variants and related inflections.
    It is used as a secondary signal; exact lexical relevance remains dominant.
    """
    a, b = _features(left), _features(right)
    if not a or not b:
        return 0.0
    dot = sum(value * b.get(slot, 0.0) for slot, value in a.items())
    denominator = math.sqrt(sum(value * value for value in a.values())) * \
        math.sqrt(sum(value * value for value in b.values()))
    return round(dot / denominator, 6) if denominator else 0.0
