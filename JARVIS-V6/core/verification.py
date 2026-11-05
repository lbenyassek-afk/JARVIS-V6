from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class VerificationResult:
    verified: bool
    detail: str
    observed: bool = True

    @classmethod
    def reported(cls, detail: str = "Action returned successfully") -> "VerificationResult":
        return cls(True, detail, False)


def verify(verifier: Callable[[str, str], object] | None, value: str,
           result: str, settle_seconds: float = 0.0) -> VerificationResult:
    """Run one bounded postcondition without allowing verifier failures to lie.

    A missing verifier is a successful *reported* outcome. It is deliberately
    different from an observed result so the UI/audit can remain honest.
    """
    if verifier is None:
        return VerificationResult.reported()
    if settle_seconds:
        time.sleep(max(0.0, min(float(settle_seconds), 2.0)))
    try:
        outcome = verifier(value, result)
    except Exception as exc:
        return VerificationResult(False, f"Postcondition could not be checked: {exc}")
    if isinstance(outcome, VerificationResult):
        return outcome
    if isinstance(outcome, bool):
        return VerificationResult(outcome, "Observed expected state" if outcome else "Expected state was not observed")
    return VerificationResult(False, "Verifier returned an invalid result")
