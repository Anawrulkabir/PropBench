"""Model selection with a rule fixed before fitting (README §2: no choosing the criterion after seeing the results).

A ``SelectionRule`` is locked by the SHA-256 of its canonical JSON. The study stores the hash before any fit runs, and
``select`` refuses a rule whose hash differs, so the criterion cannot be changed after the fits are known.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import asdict, dataclass

METRICS = ("cv_aard", "cv_rms", "fit_aard", "aic", "bic")


class SelectionError(ValueError):
    """The selection rule is invalid, was changed after locking, or no candidate qualifies."""


@dataclass(frozen=True)
class SelectionRule:
    """Pick the candidate with the lowest ``metric``; candidates within ``tie_tolerance`` (relative) of the best count
    as tied, and ties go to the fewest parameters. Candidates failing any physics check are excluded if
    ``require_physics``."""

    metric: str = "cv_aard"
    validation: str = "loso"
    tie_tolerance: float = 0.05
    require_physics: bool = True
    notes: str = ""

    def __post_init__(self) -> None:
        if self.metric not in METRICS:
            raise SelectionError(f"unknown metric {self.metric!r} (known: {', '.join(METRICS)})")
        if not 0 <= self.tie_tolerance < 1:
            raise SelectionError("tie_tolerance must be in [0, 1)")

    def canonical(self) -> str:
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":"))

    def sha256(self) -> str:
        return hashlib.sha256(self.canonical().encode()).hexdigest()

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SelectionRule:
        return cls(**data)  # type: ignore[arg-type]


@dataclass(frozen=True)
class Candidate:
    name: str
    n_parameters: int
    metrics: dict[str, float]
    physics_passed: bool = True


@dataclass(frozen=True)
class Selection:
    chosen: str
    ranking: tuple[str, ...]
    excluded: tuple[str, ...]
    rule_sha256: str
    reason: str


def information_criteria(n_points: int, n_parameters: int, weighted_sse: float) -> dict[str, float]:
    """AIC and BIC of a least-squares fit with Gaussian errors (up to a common constant)."""
    if n_points <= 0 or weighted_sse <= 0:
        return {"aic": math.nan, "bic": math.nan}
    base = n_points * math.log(weighted_sse / n_points)
    return {"aic": base + 2 * n_parameters, "bic": base + n_parameters * math.log(n_points)}


def select(rule: SelectionRule, locked_sha256: str, candidates: Sequence[Candidate]) -> Selection:
    if rule.sha256() != locked_sha256:
        raise SelectionError("the selection rule differs from the one locked before fitting")
    excluded = []
    usable = []
    for c in candidates:
        value = c.metrics.get(rule.metric, math.nan)
        if (rule.require_physics and not c.physics_passed) or not math.isfinite(value):
            excluded.append(c.name)
        else:
            usable.append((value, c))
    if not usable:
        raise SelectionError("no candidate qualifies under the locked rule")
    usable.sort(key=lambda vc: (vc[0], vc[1].n_parameters, vc[1].name))
    best = usable[0][0]
    # AIC/BIC can be negative: tolerance relative to |best|
    tied = [c for v, c in usable if v <= best + rule.tie_tolerance * abs(best)]
    chosen = min(tied, key=lambda c: (c.n_parameters, c.metrics[rule.metric], c.name))
    reason = f"lowest {rule.metric} = {best:.6g}"
    if chosen is not usable[0][1]:
        reason += f"; {chosen.name} is within {rule.tie_tolerance:.0%} with fewer parameters"
    return Selection(chosen.name, tuple(c.name for _, c in usable), tuple(excluded), locked_sha256, reason)
