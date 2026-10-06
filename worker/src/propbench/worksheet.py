"""Worksheets (README §2e.1): a dataset as columns, formula columns, a row filter and column statistics.

Columns of a dataset (SI): ``T`` (K), ``p`` (Pa), ``rho`` (mol/m³), ``y`` (the property), ``U`` (expanded
uncertainty), ``u`` (standard uncertainty), ``u_rel`` (relative standard uncertainty), ``id`` (point id). Formula
columns are evaluated in order, so a formula may use earlier ones, e.g.
``rho_mass = eos("Dmass", T, p, fluid="R13I1")`` then ``nu = y / rho_mass``. Masked points are kept and computed
but left out of the statistics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from propbench.core import Dataset
from propbench.expr import FormulaError, evaluate


def dataset_columns(ds: Dataset) -> dict[str, np.ndarray]:
    n = len(ds)
    nan = np.full(n, np.nan)
    cols = {
        "id": np.asarray(ds.point_ids, dtype=float),
        "T": np.asarray(ds.temperature, dtype=float),
        "p": nan if ds.pressure is None else np.asarray(ds.pressure, dtype=float),
        "rho": nan if ds.molar_density is None else np.asarray(ds.molar_density, dtype=float),
        "y": np.asarray(ds.values, dtype=float),
        "U": nan if ds.expanded_uncertainty is None else np.asarray(ds.expanded_uncertainty, dtype=float),
    }
    cols["u"] = cols["U"] / ds.coverage_factor  # standard uncertainty (absolute)
    cols["u_rel"] = cols["u"] / cols["y"]
    cols["U_pct"] = 100.0 * cols["U"] / np.abs(cols["y"])  # expanded uncertainty in % of the value
    return cols


def statistics(values: np.ndarray) -> dict[str, float | int | None]:
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"n": 0, "mean": None, "std": None, "min": None, "max": None, "median": None, "sum": None, "rsd": None}
    std = float(np.std(v, ddof=1)) if v.size > 1 else None
    mean = float(np.mean(v))
    if std is not None and std <= 1e-12 * max(abs(mean), 1e-300):
        std = 0.0  # constant column: no rounding noise
    return {
        "n": int(v.size),
        "mean": mean,
        "std": std,
        "min": float(np.min(v)),
        "max": float(np.max(v)),
        "median": float(np.median(v)),
        "sum": float(np.sum(v)),
        "rsd": None if std is None or mean == 0 else 100.0 * std / abs(mean),
    }


def compute(
    ds: Dataset,
    formulas: Sequence[Mapping[str, str]] = (),
    row_filter: str | None = None,
    masked: Sequence[int] = (),
) -> dict[str, Any]:
    """Formula columns, the filter result per row and statistics of every column over unmasked, filtered rows."""
    cols = dataset_columns(ds)
    added = []
    for f in formulas:
        name, text = str(f.get("name", "")).strip(), str(f.get("formula", ""))
        if not name.isidentifier() or name in ("id",):
            raise FormulaError(f"invalid column name {name!r}")
        value = np.broadcast_to(np.asarray(evaluate(text, cols), dtype=float), (len(ds),)).copy()
        cols[name] = value
        added.append(name)
    keep = np.ones(len(ds), dtype=bool)
    if row_filter and row_filter.strip():
        keep = np.broadcast_to(np.asarray(evaluate(row_filter, cols), dtype=bool), (len(ds),)).copy()
    in_stats = keep & ~np.isin(np.asarray(ds.point_ids), np.asarray(list(masked), dtype=int))
    return {
        "columns": {k: cols[k] for k in added},
        "filter": keep,
        "statistics": {k: statistics(v[in_stats]) for k, v in cols.items() if k != "id"},
    }
