"""Models side by side: deviation statistics of each model against each dataset (README §2, comparison)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from propbench.backends import Backend
from propbench.core import Dataset
from propbench.fit import Deviations, deviations, fit_data
from propbench.models import Model
from propbench.validate.physics import predict_each


@dataclass(frozen=True)
class ComparisonRow:
    model: str
    dataset: str  # "all" for the pooled row
    deviations: Deviations
    not_evaluated: int  # states where the model cannot be computed
    point_ids: np.ndarray | None = None  # per-point deviations of a dataset row (None for the pooled row)
    ard: np.ndarray | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            "model": self.model,
            "dataset": self.dataset,
            "deviations": self.deviations.as_dict(),
            "not_evaluated": self.not_evaluated,
            "point_ids": None if self.point_ids is None else self.point_ids.tolist(),
            "ard": None if self.ard is None else self.ard.tolist(),
        }


def compare_models(
    models: Mapping[str, Model], datasets: Sequence[Dataset], backend: Backend | None = None
) -> list[ComparisonRow]:
    """AARD, bias, RMS and max |ARD| of every model on every dataset and on all data pooled."""
    states = [(d, fit_data([d], backend)) for d in datasets]
    rows = []
    for name, model in models.items():
        pooled_y, pooled_m, missing = [], [], 0
        for d, data in states:
            predicted = predict_each(model, data.temperature, data.molar_density)
            ok = np.isfinite(predicted) & (predicted > 0)
            missing += int((~ok).sum())
            ard = np.full(len(data), np.nan)
            ard[ok] = 100.0 * (data.values[ok] - predicted[ok]) / predicted[ok]
            rows.append(
                ComparisonRow(
                    name, d.name, deviations(data.values[ok], predicted[ok]), int((~ok).sum()), data.point_ids, ard
                )
            )
            pooled_y.append(data.values[ok])
            pooled_m.append(predicted[ok])
        if len(states) > 1:
            rows.append(
                ComparisonRow(name, "all", deviations(np.concatenate(pooled_y), np.concatenate(pooled_m)), missing)
            )
    return rows
