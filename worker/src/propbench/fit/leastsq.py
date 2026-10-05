"""Weighted least squares in relative deviation with bounds, seeded multi-start and per-dataset scale factors.

Residual of point i in dataset j:  r_i = w_i · (y_i - s_j·m_i) / (s_j·m_i),  w_i = 1/u_i (standard relative
uncertainty) when weighting is on, else 1. s_j are optional per-dataset scale factors (the first dataset is the
reference, s = 1). Minimised with scipy.optimize.least_squares (trust-region reflective, bounds respected).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import least_squares

from propbench.fit.data import FitData
from propbench.fit.stats import Deviations, ard, deviations
from propbench.models.base import Model, ModelError, free_bounds, free_names


class FitError(RuntimeError):
    """The fit could not be carried out (no free parameters, model failure at every start, ...)."""


@dataclass(frozen=True)
class FitResult:
    model: Any  # the fitted model (same type as the input model)
    values: dict[str, float]  # fitted free parameters
    standard_errors: dict[str, float]
    covariance: np.ndarray
    scale_factors: dict[str, float]
    deviations: Deviations
    ard: np.ndarray  # per point, %, with scale factors applied
    cost: float
    success: bool
    message: str
    nfev: int
    starts: int
    seed: int
    weighted: bool
    point_ids: np.ndarray = field(repr=False)

    def summary(self) -> dict[str, Any]:
        return {
            "values": self.values,
            "standard_errors": self.standard_errors,
            "scale_factors": self.scale_factors,
            "deviations": self.deviations.as_dict(),
            "cost": self.cost,
            "success": self.success,
            "message": self.message,
            "nfev": self.nfev,
            "starts": self.starts,
            "seed": self.seed,
            "weighted": self.weighted,
        }


def evaluator(model: Model, data: FitData) -> Callable[[Mapping[str, float]], np.ndarray]:
    """Fast evaluation for a fixed set of states: models may offer ``prepare`` (e.g. ECS caches conformal states)."""
    prepare = getattr(model, "prepare", None)
    if callable(prepare):
        prepared = prepare(data.temperature, data.molar_density)
        return prepared.evaluate
    return lambda values: model.with_params(values).predict(data.temperature, data.molar_density)


def fit(
    model: Model,
    data: FitData,
    *,
    weighted: bool = True,
    scale_factors: bool = False,
    multistart: int = 0,
    seed: int = 0,
    max_nfev: int | None = None,
) -> FitResult:
    """Fit the free parameters of ``model`` to ``data``. ``multistart`` extra starts are drawn with a seeded PCG64."""
    names = free_names(model)
    n_sets = len(data.dataset_names)
    use_scales = scale_factors and n_sets > 1
    if not names and not use_scales:
        raise FitError("the model has no free parameters")
    lower, upper = free_bounds(model)
    x0 = np.array([model.params()[n].value for n in names])
    if use_scales:
        lower = np.concatenate([lower, np.full(n_sets - 1, 0.5)])
        upper = np.concatenate([upper, np.full(n_sets - 1, 2.0)])
        x0 = np.concatenate([x0, np.ones(n_sets - 1)])
    if weighted and data.relative_uncertainty is not None:
        weights = 1.0 / data.relative_uncertainty
        is_weighted = True
    else:
        weights = np.ones(len(data))
        is_weighted = False
    evaluate = evaluator(model, data)
    k = len(names)

    def scales(x: np.ndarray) -> np.ndarray:
        if not use_scales:
            return np.ones(len(data))
        s = np.concatenate([[1.0], x[k:]])
        return s[data.dataset_index]

    def residuals(x: np.ndarray) -> np.ndarray:
        try:
            predicted = evaluate(dict(zip(names, x[:k], strict=True))) * scales(x)
        except ModelError:
            return np.full(len(data), 1e6)  # outside the model's domain: steer the optimiser away
        return weights * (data.values - predicted) / predicted

    starts = [x0]
    rng = np.random.Generator(np.random.PCG64(seed))
    for _ in range(multistart):
        lo = np.where(np.isfinite(lower), lower, x0 - np.maximum(1.0, np.abs(x0)))
        hi = np.where(np.isfinite(upper), upper, x0 + np.maximum(1.0, np.abs(x0)))
        starts.append(rng.uniform(lo, hi))

    best = None
    total_nfev = 0
    for start in starts:
        clipped = np.clip(start, lower, upper)
        try:
            result = least_squares(residuals, clipped, bounds=(lower, upper), method="trf", max_nfev=max_nfev)
        except (ValueError, ModelError):
            continue
        total_nfev += result.nfev
        if best is None or result.cost < best.cost:
            best = result
    if best is None:
        raise FitError("the fit failed from every start")

    values = dict(zip(names, (float(v) for v in best.x[:k]), strict=True))
    fitted = model.with_params(values)
    dof = max(len(data) - len(best.x), 1)
    jtj = best.jac.T @ best.jac
    try:
        cov = np.linalg.pinv(jtj) * (2.0 * best.cost / dof)
    except np.linalg.LinAlgError:
        cov = np.full((len(best.x), len(best.x)), np.nan)
    errors = np.sqrt(np.clip(np.diag(cov), 0.0, None))
    scale_values = {data.dataset_names[j]: float(best.x[k + j - 1]) for j in range(1, n_sets)} if use_scales else {}
    predicted = evaluate(values) * scales(best.x)
    return FitResult(
        model=fitted,
        values=values,
        standard_errors=dict(zip(names, (float(e) for e in errors[:k]), strict=True)),
        covariance=cov,
        scale_factors=scale_values,
        deviations=deviations(data.values, predicted),
        ard=ard(data.values, predicted),
        cost=float(best.cost),
        success=bool(best.success),
        message=str(best.message),
        nfev=total_nfev,
        starts=len(starts),
        seed=seed,
        weighted=is_weighted,
        point_ids=data.point_ids,
    )
