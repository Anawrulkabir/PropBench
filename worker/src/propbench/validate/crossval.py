"""Cross-validation: refit on each training set, report deviations on the held-out points.

Folds run in separate worker processes when ``workers > 1`` (CLAUDE.md rule 7: parallelise only fitting/validation
loops). Each fold is deterministic, so the result is identical for any number of workers.
"""

from __future__ import annotations

import multiprocessing
from collections.abc import Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from propbench.fit import Deviations, FitData, FitError, Prepared, ard, deviations, fit, prepare
from propbench.models import Model, ModelError
from propbench.validate.splits import Fold


@dataclass(frozen=True)
class FoldResult:
    name: str
    values: dict[str, float]
    success: bool
    train: Deviations
    test: Deviations
    test_ard: np.ndarray = field(repr=False)
    test_point_ids: np.ndarray = field(repr=False)
    test_dataset_index: np.ndarray = field(repr=False)
    message: str = ""


@dataclass(frozen=True)
class CrossValidation:
    method: str
    folds: tuple[FoldResult, ...]
    seed: int

    @property
    def pooled(self) -> Deviations:
        """Deviation statistics over all held-out points of all folds."""
        d = np.concatenate([f.test_ard for f in self.folds]) if self.folds else np.array([])
        if d.size == 0:
            return Deviations(0, float("nan"), float("nan"), float("nan"), float("nan"))
        return Deviations(
            int(d.size),
            float(np.mean(np.abs(d))),
            float(np.mean(d)),
            float(np.sqrt(np.mean(d**2))),
            float(np.max(np.abs(d))),
        )

    def parameters(self) -> dict[str, np.ndarray]:
        """Fitted value of each parameter in each successful fold (spread = parameter stability)."""
        ok = [f for f in self.folds if f.success]
        names = list(ok[0].values) if ok else []
        return {n: np.array([f.values[n] for f in ok]) for n in names}

    def summary(self) -> dict[str, Any]:
        params = self.parameters()
        return {
            "method": self.method,
            "seed": self.seed,
            "pooled": self.pooled.as_dict(),
            "folds": [
                {
                    "name": f.name,
                    "success": f.success,
                    "values": f.values,
                    "train": f.train.as_dict(),
                    "test": f.test.as_dict(),
                    "message": f.message,
                }
                for f in self.folds
            ],
            "parameters": {
                n: {"mean": float(np.mean(v)), "std": float(np.std(v, ddof=1)) if len(v) > 1 else 0.0}
                for n, v in params.items()
            },
        }


def _run_fold(
    model: Model,
    name: str,
    train: FitData,
    test: FitData,
    prepared_train: Prepared | None,
    prepared_test: Prepared | None,
    options: dict[str, Any],
) -> FoldResult:
    try:
        result = fit(model, train, prepared=prepared_train, **options)
        if prepared_test is not None:
            predicted = prepared_test.evaluate(result.values)
        else:
            predicted = result.model.predict(test.temperature, test.molar_density)
    except (FitError, ModelError) as exc:
        nan = Deviations(0, float("nan"), float("nan"), float("nan"), float("nan"))
        empty = np.array([])
        return FoldResult(name, {}, False, nan, nan, empty, empty.astype(np.int64), empty.astype(int), str(exc))
    # a held-out point of a dataset that had a fitted scale factor is compared with the scaled model
    scales = np.ones(len(test.dataset_names))
    for j, dataset in enumerate(test.dataset_names):
        scales[j] = result.scale_factors.get(dataset, 1.0)
    predicted = predicted * scales[test.dataset_index]
    return FoldResult(
        name,
        result.values,
        result.success,
        result.deviations,
        deviations(test.values, predicted),
        ard(test.values, predicted),
        test.point_ids,
        test.dataset_index,
        result.message,
    )


def cross_validate(
    model: Model,
    data: FitData,
    folds: Sequence[Fold],
    *,
    method: str = "custom",
    workers: int = 1,
    seed: int = 0,
    weighted: bool = True,
    scale_factors: bool = False,
    multistart: int = 0,
) -> CrossValidation:
    """Refit ``model`` on each fold's training rows; ``seed`` drives the multistart of every fold."""
    options = {"weighted": weighted, "scale_factors": scale_factors, "multistart": multistart, "seed": seed}
    full = prepare(model, data)  # state-dependent work (e.g. ECS conformal states) once for all folds
    jobs = []
    for f in folds:
        jobs.append(
            (
                model,
                f.name,
                data.select(f.train),
                data.select(f.test),
                None if full is None else full.subset(f.train),
                None if full is None else full.subset(f.test),
                options,
            )
        )
    if workers > 1 and len(jobs) > 1:
        # spawn on every OS so behaviour does not depend on the platform's default start method
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=min(workers, len(jobs)), mp_context=context) as pool:
            results = list(pool.map(_run_fold, *zip(*jobs, strict=True)))
    else:
        results = [_run_fold(*job) for job in jobs]
    return CrossValidation(method, tuple(results), seed)
