"""Datasets → the flat arrays a fit works on (states as T and molar density, values, weights, dataset index)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from propbench.backends import Backend, CoolPropBackend
from propbench.core import Dataset, DatasetError


@dataclass(frozen=True)
class FitData:
    """All points of one or more datasets of the same fluid and quantity, in SI."""

    temperature: np.ndarray
    molar_density: np.ndarray
    values: np.ndarray
    relative_uncertainty: np.ndarray | None  # standard (k = 1) relative uncertainty, or None if any is missing
    dataset_index: np.ndarray  # which dataset each point belongs to
    point_ids: np.ndarray
    dataset_names: tuple[str, ...]
    fluid: str

    def __len__(self) -> int:
        return len(self.values)

    def select(self, mask: np.typing.ArrayLike) -> FitData:
        idx = np.asarray(mask)
        u = None if self.relative_uncertainty is None else self.relative_uncertainty[idx]
        return FitData(
            self.temperature[idx],
            self.molar_density[idx],
            self.values[idx],
            u,
            self.dataset_index[idx],
            self.point_ids[idx],
            self.dataset_names,
            self.fluid,
        )


def fit_data(datasets: Sequence[Dataset], backend: Backend | None = None) -> FitData:
    """Combine datasets; pressures are converted to molar densities with ``backend`` (default CoolProp HEOS)."""
    if not datasets:
        raise DatasetError("fit_data needs at least one dataset")
    fluids = {d.fluid for d in datasets}
    quantities = {d.quantity for d in datasets}
    if len(fluids) != 1 or len(quantities) != 1:
        raise DatasetError(f"datasets must share one fluid and quantity (got {sorted(fluids)}, {sorted(quantities)})")
    backend = backend or CoolPropBackend()
    t, rho, y, u, idx, ids = [], [], [], [], [], []
    for j, d in enumerate(datasets):
        if d.molar_density is not None:
            density = d.molar_density
        elif d.pressure is not None:
            batch = backend.properties(d.fluid, "PT_INPUTS", d.pressure, d.temperature, ["Dmolar"])
            if batch.failed.any():
                bad = [int(d.point_ids[i]) for i in np.flatnonzero(batch.failed)]
                raise DatasetError(f"{d.name}: no density for points {bad}: {next(iter(batch.errors.values()))}")
            density = batch["Dmolar"]
        else:
            raise DatasetError(f"{d.name}: needs pressure or molar density")
        t.append(d.temperature)
        rho.append(density)
        y.append(d.values)
        rel = d.relative_uncertainty
        u.append(None if rel is None else rel / d.coverage_factor)
        idx.append(np.full(len(d), j))
        ids.append(d.point_ids)
    rel_u = None if any(x is None for x in u) else np.concatenate(u)  # type: ignore[arg-type]
    return FitData(
        np.concatenate(t),
        np.concatenate(rho),
        np.concatenate(y),
        rel_u,
        np.concatenate(idx),
        np.concatenate(ids),
        tuple(d.name for d in datasets),
        next(iter(fluids)),
    )
