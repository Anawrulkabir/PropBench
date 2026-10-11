"""Validation (README §2): cross-validation splits, physics checks and model selection with a pre-locked rule."""

from propbench.validate.crossval import CrossValidation, FoldResult, cross_validate
from propbench.validate.physics import (
    PhysicsCheck,
    StateGrid,
    check_dilute_limit,
    check_extrapolation,
    check_monotonic_density,
    check_monotonic_temperature,
    physics_checks,
    state_grid,
)
from propbench.validate.selection import (
    METRICS,
    Candidate,
    Selection,
    SelectionError,
    SelectionRule,
    information_criteria,
    select,
)
from propbench.validate.splits import Fold, SplitError, bootstrap, kfold, loso, lostate, loto, state_groups

SPLITS = {"lostate": lostate, "loso": loso, "loto": loto, "kfold": kfold, "bootstrap": bootstrap}

__all__ = [
    "METRICS",
    "SPLITS",
    "Candidate",
    "CrossValidation",
    "Fold",
    "FoldResult",
    "PhysicsCheck",
    "Selection",
    "SelectionError",
    "SelectionRule",
    "SplitError",
    "StateGrid",
    "bootstrap",
    "check_dilute_limit",
    "check_extrapolation",
    "check_monotonic_density",
    "check_monotonic_temperature",
    "cross_validate",
    "information_criteria",
    "kfold",
    "loso",
    "lostate",
    "loto",
    "physics_checks",
    "select",
    "state_grid",
    "state_groups",
]
