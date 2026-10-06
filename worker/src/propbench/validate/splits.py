"""Train/test splits for cross-validation (README §2): leave-one-state-out, leave-one-source-out,
leave-one-isotherm-out, k-fold, bootstrap.

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


def state_groups(data: FitData, t_tolerance: float = 1.0, p_tolerance: float = 0.03) -> np.ndarray:
    """Group index per point: repeats of one measured state. Two points of the same dataset are linked when their
    temperatures differ by at most ``t_tolerance`` (K) and their pressures by at most ``p_tolerance`` (relative; molar
    densities when pressures are not known); a state is a connected group of linked points."""
    key = data.pressure if data.pressure is not None else data.molar_density
    n = len(data)
    parent = list(range(n))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if (
                data.dataset_index[i] == data.dataset_index[j]
                and abs(data.temperature[i] - data.temperature[j]) <= t_tolerance
                and abs(key[i] - key[j]) <= p_tolerance * max(abs(key[i]), abs(key[j]), 1e-12)
            ):
                parent[root(i)] = root(j)
    roots = [root(i) for i in range(n)]
    order = {r: g for g, r in enumerate(dict.fromkeys(roots))}  # numbered in data order: deterministic
    return np.array([order[r] for r in roots], dtype=int)


def lostate(data: FitData, t_tolerance: float = 1.0, p_tolerance: float = 0.03) -> list[Fold]:
    """Leave one state out (README §2): all repeats at one measured state form the test set."""
    groups = state_groups(data, t_tolerance, p_tolerance)
    n = int(groups.max()) + 1 if len(groups) else 0
    if n < 2:
        raise SplitError("leave-one-state-out needs at least two states")
    rows = np.arange(len(data))
    folds = []
    for g in range(n):
        mask = groups == g
        i = rows[mask][0]
        name = f"{data.dataset_names[data.dataset_index[i]]} {np.mean(data.temperature[mask]):.2f} K"
        where = (
            f"{np.mean(data.pressure[mask]) * 1e-6:.3g} MPa"
            if data.pressure is not None
            else f"{np.mean(data.molar_density[mask]):.0f} mol/m³"
        )
        folds.append(Fold(f"{name}, {where}", rows[~mask], rows[mask]))
    return folds


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
