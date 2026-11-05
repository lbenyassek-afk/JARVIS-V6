from __future__ import annotations


def silence_blocks(configured_ms: int, speech_blocks: int, adaptive: bool = True) -> int:
    """Return 50 ms blocks needed to close a turn without clipping natural pauses."""
    base = max(7, min(24, round(int(configured_ms) / 50)))
    if not adaptive:
        return base
    if speech_blocks <= 10:       # Short commands such as “Hi Jarvis”.
        return max(7, base - 3)
    if speech_blocks >= 120:      # Long dictation contains longer thinking pauses.
        return min(24, base + 3)
    return base


def valid_capture(floor: float, peak: float, speech_blocks: int, minimum_ms: int = 150) -> bool:
    minimum_blocks = max(2, round(int(minimum_ms) / 50))
    signal_ratio = float(peak) / max(float(floor), .0008)
    return speech_blocks >= minimum_blocks and peak >= .0018 and signal_ratio >= 1.65
