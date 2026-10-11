"""General curve fitting (README §2e.4–5): any user equation, bounds, fixed parameters, weights, global fits with
shared and per-dataset parameters, per-dataset scale factors, multi-start, and diagnostics.

The equation is a formula (``propbench.expr``) of the independent variables and the parameters, e.g.
``a * exp(b / T) + c``. Several datasets are fitted together: a parameter is shared by all of them unless it is
listed in ``local``, in which case each dataset gets its own copy (``name[dataset]``). Minimised:
Σ w_i (y_i − s_d · f(x_i; θ))², with weights w_i = 1/σ_i² from the stated uncertainties (or 1) and optional scale
factors s_d per dataset (the first dataset is the reference, s = 1). Solved with SciPy ``least_squares`` (trust
region reflective with bounds, finite-difference Jacobian); ``multistart`` adds starts drawn uniformly within
finite bounds from a seeded PCG64 (CLAUDE.md rule 6) and keeps the lowest cost.

Diagnostics: standard errors and correlation matrix (from the Jacobian, scaled by the reduced χ² when no
uncertainties are given), AIC/BIC, residuals, studentised residuals with |r| > 3 flagged as outliers, and the
F-test of two nested fits.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import stats
from scipy.optimize import least_squares

from propbench.expr import FormulaError, compile_function, names


class CurveFitError(ValueError):
    """The fit problem is not well defined (unknown names, too few points, bad bounds)."""


@dataclass(frozen=True)
class Series:
    """One dataset of a fit: independent variables by name, observations and their standard uncertainties."""

    name: str
    x: Mapping[str, np.ndarray]
    y: np.ndarray
    sigma: np.ndarray | None = None


@dataclass(frozen=True)
class ParameterSpec:
    value: float
    lower: float = -math.inf
    upper: float = math.inf
    fixed: bool = False


@dataclass
class CurveFit:
    values: dict[str, float]
    errors: dict[str, float | None]
    correlation: list[list[float]]
    free: list[str]
    scale_factors: dict[str, float]
    residuals: dict[str, list[float]]
    fitted: dict[str, list[float]]
    studentized: dict[str, list[float]]
    outliers: dict[str, list[int]]
    chi2: float
    dof: int
    reduced_chi2: float
    aic: float
    bic: float
    r2: float
    n: int
    success: bool
    message: str
    starts: int
    extra: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}


def _names(series: Sequence[Series], local: Sequence[str], params: Mapping[str, ParameterSpec]) -> list[str]:
    out = []
    for p in params:
        if p in local:
            out += [f"{p}[{s.name}]" for s in series]
        else:
            out.append(p)
    return out


def fit(
    equation: str,
    series: Sequence[Series],
    parameters: Mapping[str, ParameterSpec],
    *,
    local: Sequence[str] = (),
    scale_factors: bool = False,
    weighted: bool = True,
    multistart: int = 0,
    seed: int = 0,
) -> CurveFit:
    if not series:
        raise CurveFitError("no data to fit")
    variables = sorted(set(series[0].x))
    unknown = names(equation) - set(variables) - set(parameters)
    if unknown:
        raise CurveFitError(f"the equation uses {sorted(unknown)}, which are neither variables nor parameters")
    if any(set(s.x) != set(variables) for s in series):
        raise CurveFitError("every dataset needs the same independent variables")
    for p in local:
        if p not in parameters:
            raise CurveFitError(f"local parameter {p!r} is not a parameter")
    f = compile_function(equation, [*variables, *parameters])

    all_names = _names(series, local, parameters)
    base = {p: parameters[p.split("[")[0]] for p in all_names}
    free = [p for p in all_names if not base[p].fixed]
    n_scale = len(series) - 1 if scale_factors else 0
    lower = np.array([base[p].lower for p in free] + [0.0] * n_scale)
    upper = np.array([base[p].upper for p in free] + [np.inf] * n_scale)
    x0 = np.array([base[p].value for p in free] + [1.0] * n_scale)
    if np.any(lower >= upper) or np.any(x0 < lower) or np.any(x0 > upper):
        raise CurveFitError("every start value must lie within lower < upper bounds")
    n = sum(len(s.y) for s in series)
    if n <= len(x0):
        raise CurveFitError(f"{n} points cannot determine {len(x0)} free parameters")
    weights = [
        (1.0 / np.asarray(s.sigma, float)) if (weighted and s.sigma is not None) else np.ones(len(s.y)) for s in series
    ]

    def values_of(theta: np.ndarray) -> dict[str, float]:
        v = {p: base[p].value for p in all_names}
        v.update(dict(zip(free, theta[: len(free)], strict=True)))
        return v

    def model(theta: np.ndarray) -> list[np.ndarray]:
        v = values_of(theta)
        out = []
        for j, s in enumerate(series):
            args = [s.x[name] for name in variables]
            pars = [v[f"{p}[{s.name}]" if p in local else p] for p in parameters]
            yhat = np.broadcast_to(np.asarray(f(*args, *pars), dtype=float), s.y.shape)
            scale = theta[len(free) + j - 1] if (scale_factors and j > 0) else 1.0
            out.append(scale * yhat)
        return out

    def residuals(theta: np.ndarray) -> np.ndarray:
        r = np.concatenate([(m - s.y) * w for m, s, w in zip(model(theta), series, weights, strict=True)])
        return np.where(np.isfinite(r), r, 1e10)

    starts = [x0]
    if multistart > 0:
        rng = np.random.Generator(np.random.PCG64(seed))
        finite = np.isfinite(lower) & np.isfinite(upper)
        for _ in range(multistart):
            x = x0.copy()
            x[finite] = rng.uniform(lower[finite], upper[finite])
            starts.append(x)
    best = None
    for x in starts:
        try:
            r = least_squares(
                residuals, x, bounds=(lower, upper), x_scale="jac", method="trf", ftol=1e-12, xtol=1e-12, gtol=1e-12
            )
        except ValueError as exc:
            raise CurveFitError(str(exc)) from exc
        if best is None or r.cost < best.cost:
            best = r
    assert best is not None

    theta = best.x
    resid_w = best.fun
    chi2 = float(resid_w @ resid_w)
    k = len(theta)
    dof = n - k
    has_sigma = weighted and all(s.sigma is not None for s in series)
    red = chi2 / dof if dof > 0 else math.nan
    jac = best.jac
    # Columns can differ by many orders of magnitude (a ≈ 1e-5 next to b ≈ 1e3): invert JᵀJ with normalised
    # columns, then scale back, so no singular value is lost to the pseudo-inverse cut-off.
    norms = np.linalg.norm(jac, axis=0)
    norms[norms == 0] = 1.0
    js = jac / norms
    try:
        cov = np.linalg.pinv(js.T @ js) / np.outer(norms, norms)
        if not has_sigma and dof > 0:
            cov = cov * red  # uncertainties from the scatter when no stated uncertainties are used
        err = np.sqrt(np.clip(np.diag(cov), 0, None))
        corr = cov / np.outer(err, err)
    except np.linalg.LinAlgError:  # pragma: no cover - pinv does not raise for finite matrices
        err, corr = np.full(k, np.nan), np.full((k, k), np.nan)
    # leverage for studentised residuals: h = diag(J (JᵀJ)⁻¹ Jᵀ)
    try:
        lev = np.einsum("ij,jk,ik->i", js, np.linalg.pinv(js.T @ js), js)
    except np.linalg.LinAlgError:  # pragma: no cover
        lev = np.zeros(n)
    s_hat = math.sqrt(red) if (not has_sigma and dof > 0) else 1.0
    stud = resid_w / (s_hat * np.sqrt(np.clip(1 - lev, 1e-12, None)))

    fitted = model(theta)
    names_out = [s.name for s in series]
    out_res, out_fit, out_stud, outliers = {}, {}, {}, {}
    pos = 0
    for s, m in zip(series, fitted, strict=True):
        n_s = len(s.y)
        out_res[s.name] = (s.y - m).tolist()
        out_fit[s.name] = m.tolist()
        out_stud[s.name] = stud[pos : pos + n_s].tolist()
        outliers[s.name] = [int(i) for i in np.flatnonzero(np.abs(stud[pos : pos + n_s]) > 3)]
        pos += n_s
    y_all = np.concatenate([s.y for s in series])
    ss_res = float(np.sum((y_all - np.concatenate(fitted)) ** 2))
    ss_tot = float(np.sum((y_all - np.mean(y_all)) ** 2))
    # AIC/BIC from the weighted sum of squares (Gaussian errors, σ known or estimated)
    log_term = chi2 if has_sigma else n * math.log(max(chi2, 1e-300) / n)
    values = values_of(theta)
    return CurveFit(
        values=values,
        errors={
            **{p: float(e) for p, e in zip(free, err[: len(free)], strict=True)},
            **{p: None for p in all_names if p not in free},
        },
        correlation=np.nan_to_num(corr[: len(free), : len(free)]).tolist(),
        free=free,
        scale_factors={names_out[j]: float(theta[len(free) + j - 1]) for j in range(1, len(series))} if n_scale else {},
        residuals=out_res,
        fitted=out_fit,
        studentized=out_stud,
        outliers=outliers,
        chi2=chi2,
        dof=dof,
        reduced_chi2=red,
        aic=log_term + 2 * k,
        bic=log_term + k * math.log(n),
        r2=1.0 - ss_res / ss_tot if ss_tot > 0 else math.nan,
        n=n,
        success=bool(best.success),
        message=str(best.message),
        starts=len(starts),
    )


def f_test(simple: CurveFit, full: CurveFit) -> dict[str, float]:
    """F-test of two nested fits on the same data (``full`` has more free parameters): p < 0.05 means the extra
    parameters are justified."""
    k1, k2 = len(simple.free), len(full.free)
    if k2 <= k1 or simple.n != full.n:
        raise CurveFitError("the F-test needs nested fits of the same data, the second with more parameters")
    df1, df2 = k2 - k1, full.dof
    f_value = ((simple.chi2 - full.chi2) / df1) / (full.chi2 / df2)
    return {"F": float(f_value), "df1": df1, "df2": df2, "p": float(stats.f.sf(f_value, df1, df2))}


def series_from_columns(name: str, columns: Mapping[str, Any], x: Sequence[str], y: str, sigma: str | None) -> Series:
    try:
        xs = {v: np.asarray(columns[v], dtype=float) for v in x}
        yv = np.asarray(columns[y], dtype=float)
        sv = None if not sigma else np.asarray(columns[sigma], dtype=float)
    except KeyError as exc:
        raise FormulaError(f"{name}: no column {exc}") from None
    ok = np.isfinite(yv) & np.all([np.isfinite(v) for v in xs.values()], axis=0)
    if sv is not None:
        ok &= np.isfinite(sv) & (sv > 0)
    return Series(name, {k: v[ok] for k, v in xs.items()}, yv[ok], None if sv is None else sv[ok])
