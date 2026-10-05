"""Train/test splits for cross-validation (README §2): leave-one-source-out, leave-one-isotherm-out, k-fold, bootstrap.

Every split is a pure function of the data and an explicit seed (CLAUDE.md rule 6), so studies are reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from propbench.fit import FitData


class SplitError(ValueError):
    """The requested split is not possible for these data."""


@dataclass(frozen=True)
class Fold:
    """Row indices into a ``FitData`` for training and testing. Bootstrap training sets repeat rows."""

    name: str
    train: np.ndarray
    test: np.ndarray


def loso(data: FitData) -> list[Fold]:
    """Leave one source (dataset) out: fit to all other datasets, test on the one left out."""
    present = np.unique(data.dataset_index)
    if len(present) < 2:
        raise SplitError("leave-one-source-out needs at least two datasets")
    rows = np.arange(len(data))
    return [Fold(data.dataset_names[j], rows[data.dataset_index != j], rows[data.dataset_index == j]) for j in present]


def loto(data: FitData, tolerance: float = 0.5) -> list[Fold]:
    """Leave one isotherm out: temperatures within ``tolerance`` (K) of each other form one isotherm."""
    if tolerance <= 0:
        raise SplitError("the isotherm tolerance must be positive")
    order = np.argsort(data.temperature, kind="stable")
    groups = np.zeros(len(data), dtype=int)
    current, start = 0, data.temperature[order[0]] if len(data) else 0.0
    for i in order:
        if data.temperature[i] - start > tolerance:
            current += 1
            start = data.temperature[i]
        groups[i] = current
    if current < 1:
        raise SplitError("leave-one-isotherm-out needs at least two isotherms")
    rows = np.arange(len(data))
    folds = []
    for g in range(current + 1):
        mask = groups == g
        t = data.temperature[mask]
        folds.append(Fold(f"{np.mean(t):.2f} K", rows[~mask], rows[mask]))
    return folds


def kfold(data: FitData, k: int = 5, seed: int = 0) -> list[Fold]:
    """k-fold cross-validation with a seeded shuffle."""
    if not 2 <= k <= len(data):
        raise SplitError(f"k must be between 2 and the number of points ({len(data)})")
    rng = np.random.Generator(np.random.PCG64(seed))
    perm = rng.permutation(len(data))
    rows = np.arange(len(data))
    folds = []
    for i, test in enumerate(np.array_split(perm, k)):
        test = np.sort(test)
        folds.append(Fold(f"fold {i + 1}", np.setdiff1d(rows, test), test))
    return folds


def bootstrap(data: FitData, n: int = 100, seed: int = 0) -> list[Fold]:
    """``n`` bootstrap resamples (with replacement); the test set of each is its out-of-bag points."""
    if n < 1:
        raise SplitError("the number of bootstrap resamples must be positive")
    rng = np.random.Generator(np.random.PCG64(seed))
    rows = np.arange(len(data))
    folds = []
    for i in range(n):
        train = np.sort(rng.integers(0, len(data), len(data)))
        folds.append(Fold(f"resample {i + 1}", train, np.setdiff1d(rows, train)))
    return folds
