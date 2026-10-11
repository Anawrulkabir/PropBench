"""Uncertainty propagation (README §2e.6) after the GUM (JCGM 100:2008) and its Monte Carlo supplement
(JCGM 101:2008).

The measurement model is a formula of the input quantities (``propbench.expr``). Linear propagation (GUM §5):
sensitivity coefficients c_i = ∂f/∂x_i by central differences, u_c² = Σ c_i² u_i² + 2 Σ c_i c_j u_i u_j r_ij,
effective degrees of freedom by Welch–Satterthwaite (G.4), coverage factor from Student's t for the coverage
probability p (G.3; 95.45 % gives k = 2 for ν → ∞). Monte Carlo (JCGM 101): M draws (normal, scaled-and-shifted
t for finite ν, rectangular, triangular; correlated normals by Cholesky) from a seeded PCG64 (CLAUDE.md rule 6),
estimate, standard uncertainty and the probabilistically symmetric coverage interval.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import stats

from propbench.expr import FormulaError, compile_function, names

DISTRIBUTIONS = ("normal", "rectangular", "triangular")


@dataclass(frozen=True)
class Input:
    name: str
    value: float
    u: float  # standard uncertainty
    dof: float = math.inf
    distribution: str = "normal"  # shape used by Monte Carlo (u is always the standard uncertainty)

    def __post_init__(self) -> None:
        if self.u < 0 or not math.isfinite(self.u):
            raise FormulaError(f"{self.name}: standard uncertainty must be a non-negative number")
        if self.distribution not in DISTRIBUTIONS:
            raise FormulaError(f"{self.name}: distribution must be one of {DISTRIBUTIONS}")
        if not self.dof > 0:
            raise FormulaError(f"{self.name}: degrees of freedom must be positive")


def coverage_factor(dof: float, p: float = 0.9545) -> float:
    """k = t_p(ν) (GUM G.3); for ν = ∞ the normal quantile (2.00 for p = 95.45 %)."""
    q = 0.5 + p / 2
    return float(stats.norm.ppf(q) if not math.isfinite(dof) else stats.t.ppf(q, dof))


def linear(
    model: str,
    inputs: Sequence[Input],
    correlations: Mapping[tuple[str, str], float] | None = None,
    p: float = 0.9545,
) -> dict[str, Any]:
    names_ = [i.name for i in inputs]
    missing = names(model) - set(names_)
    if missing:
        raise FormulaError(f"the model uses {sorted(missing)}, which are not inputs")
    f = compile_function(model, names_)
    x = np.array([i.value for i in inputs], dtype=float)
    y = float(f(*x))
    c = np.zeros(len(x))
    for j, inp in enumerate(inputs):
        h = (abs(x[j]) * 1e-6 + inp.u * 1e-3) or 1e-9
        hi, lo = x.copy(), x.copy()
        hi[j] += h
        lo[j] -= h
        c[j] = (float(f(*hi)) - float(f(*lo))) / (2 * h)
    u = np.array([i.u for i in inputs])
    r = np.eye(len(x))
    for (a, b), rho in (correlations or {}).items():
        ia, ib = names_.index(a), names_.index(b)
        r[ia, ib] = r[ib, ia] = float(rho)
    contrib = c * u
    uc2 = float(contrib @ r @ contrib)
    uc = math.sqrt(max(uc2, 0.0))
    dofs = np.array([i.dof for i in inputs])
    finite = np.isfinite(dofs) & (contrib != 0)
    denom = float(np.sum(contrib[finite] ** 4 / dofs[finite]))
    nu_eff = uc**4 / denom if denom > 0 else math.inf
    # GUM G.4.1 note: truncate ν_eff to the next lower integer before taking t
    nu_used = math.floor(nu_eff) if math.isfinite(nu_eff) else math.inf
    k = coverage_factor(nu_used, p)
    budget = [
        {
            "name": inp.name,
            "value": inp.value,
            "u": inp.u,
            "dof": inp.dof if math.isfinite(inp.dof) else None,
            "sensitivity": float(c[j]),
            "contribution": float(abs(contrib[j])),
            "index": float(contrib[j] ** 2 / uc2) if uc2 > 0 else 0.0,
        }
        for j, inp in enumerate(inputs)
    ]
    return {
        "value": y,
        "u": uc,
        "dof": nu_eff if math.isfinite(nu_eff) else None,
        "k": k,
        "U": k * uc,
        "p": p,
        "interval": [y - k * uc, y + k * uc],
        "budget": budget,
    }


def monte_carlo(
    model: str,
    inputs: Sequence[Input],
    correlations: Mapping[tuple[str, str], float] | None = None,
    p: float = 0.9545,
    draws: int = 200_000,
    seed: int = 0,
) -> dict[str, Any]:
    names_ = [i.name for i in inputs]
    f = compile_function(model, names_)
    rng = np.random.Generator(np.random.PCG64(seed))
    n = len(inputs)
    r = np.eye(n)
    for (a, b), rho in (correlations or {}).items():
        ia, ib = names_.index(a), names_.index(b)
        r[ia, ib] = r[ib, ia] = float(rho)
    z = rng.standard_normal((draws, n)) @ np.linalg.cholesky(r).T
    samples = []
    for j, inp in enumerate(inputs):
        if inp.distribution == "rectangular":
            a = inp.u * math.sqrt(3)
            s = inp.value + rng.uniform(-a, a, draws)
        elif inp.distribution == "triangular":
            a = inp.u * math.sqrt(6)
            s = rng.triangular(inp.value - a, inp.value, inp.value + a, draws)
        elif math.isfinite(inp.dof) and inp.dof > 2:
            # scaled and shifted t (JCGM 101 6.4.9) with the same standard uncertainty
            t = rng.standard_t(inp.dof, draws)
            s = inp.value + inp.u * math.sqrt((inp.dof - 2) / inp.dof) * t
        else:
            s = inp.value + inp.u * z[:, j]
        samples.append(s)
    y = np.asarray(f(*samples), dtype=float)
    y = y[np.isfinite(y)]
    lo, hi = np.quantile(y, [(1 - p) / 2, (1 + p) / 2])
    return {
        "value": float(np.mean(y)),
        "u": float(np.std(y, ddof=1)),
        "interval": [float(lo), float(hi)],
        "p": p,
        "draws": int(y.size),
        "seed": seed,
        "histogram": np.histogram(y, bins=60)[0].tolist(),
        "edges": np.histogram_bin_edges(y, bins=60).tolist(),
    }
