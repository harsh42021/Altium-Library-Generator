"""
Lightweight fuzzy string matching using stdlib difflib only.
Avoids requiring rapidfuzz as a dependency for a fairly small need
(header/keyword matching, not bulk fuzzy search).
"""
from __future__ import annotations
from difflib import SequenceMatcher


def partial_ratio(a: str, b: str) -> float:
    """Approximates rapidfuzz's partial_ratio: best match of the shorter
    string against substrings of the longer one, scored 0-100."""
    a, b = a.lower().strip(), b.lower().strip()
    if not a or not b:
        return 0.0
    if a == b:
        return 100.0

    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    if not shorter:
        return 0.0

    best = 0.0
    matcher = SequenceMatcher(None, shorter, longer)
    for block in matcher.get_matching_blocks():
        if block.size == 0:
            continue
        start = max(0, block.b - (len(shorter) - block.a))
        window = longer[start:start + len(shorter)]
        ratio = SequenceMatcher(None, shorter, window).ratio()
        best = max(best, ratio)
    return round(best * 100, 2)
