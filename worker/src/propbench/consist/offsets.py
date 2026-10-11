"""Dataset offsets with uncertainty and z-scores against stated uncertainties (README §2, data consistency).

Offset model: y_i = (1 + δ)·r_i·(1 + ε_i), ε_i ~ N(0, u_i²), where r_i is a reference value (a model prediction or
the isotherm trend of another dataset). For ln(y/r) the exact conjugate result with a flat prior is the weighted
mean (Bishop 2006, §3.3; computed with ``propbench.fit.bayesian_linear_fit``). When the scatter exceeds the stated
uncertainties (Birge ratio R > 1) the interval is widened by R (Birge, Phys. Rev. 40 (1932) 207).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from propbench.fit import bayesian_linear_fit

Z95 = 1.959963984540054  # two-sided 95 % quantile of the standard normal distribution


@dataclass(frozen=True)
class Offset:
    """Relative offset of ``dataset`` from ``reference``, in %."""

    dataset: str
    reference: str
    n: int
    offset: float  # %
    ci95: tuple[float, float]  # %, statistical (Birge-widened)
    u_reference: float  # %, relative standard uncertainty of the reference added in quadrature (systematic)
    ci95_total: tuple[float, float]  # %, including the reference's stated uncertainty
    birge: float
    extrapolated: int  # points whose reference value is an extrapolation

    @property
    def significant(self) -> bool:
        """The total 95 % interval excludes zero."""
        return self.ci95_total[0] > 0 or self.ci95_total[1] < 0

    def as_dict(self) -> dict[str, object]:
        return {
            "dataset": self.dataset,
            "reference": self.reference,
            "n": self.n,
            "offset": self.offset,
            "ci95": list(self.ci95),
            "u_reference": self.u_reference,
            "ci95_total": list(self.ci95_total),
            "birge": self.birge,
            "significant": self.significant,
            "extrapolated": self.extrapolated,
        }


def relative_offset(
    values: np.ndarray,
    reference: np.ndarray,
    u_rel: np.ndarray | None,
    *,
    dataset: str,
    reference_name: str,
    u_reference: float = 0.0,
    extrapolated: int = 0,
) -> Offset:
    """Constant relative offset of ``values`` from ``reference`` (standard relative uncertainties ``u_rel``).

    Without stated uncertainties every point gets weight 1 and the interval comes from the scatter alone.
    """
    y = np.log(np.asarray(values, dtype=float) / np.asarray(reference, dtype=float))
    ok = np.isfinite(y)
    y = y[ok]
    n = len(y)
    if n == 0:
        raise ValueError(f"{dataset}: no points to compare with {reference_name}")
    sigma = np.ones(n) if u_rel is None else np.asarray(u_rel, dtype=float)[ok]
    if np.any(sigma <= 0):
        sigma = np.where(sigma > 0, sigma, np.min(sigma[sigma > 0]) if np.any(sigma > 0) else 1.0)
    fit = bayesian_linear_fit(np.ones((n, 1)), y, sigma)
    mean = float(fit.mean[0])
    sd = float(np.sqrt(fit.covariance[0, 0]))
    chi2 = float(np.sum(((y - mean) / sigma) ** 2))
    birge = float(np.sqrt(chi2 / (n - 1))) if n > 1 else float("nan")
    if u_rel is None:
        # no stated uncertainty: the scatter is the only information about the precision
        sd = float(np.std(y, ddof=1) / np.sqrt(n)) if n > 1 else float("nan")
    elif n > 1 and birge > 1.0:
        sd *= birge
    total = float(np.sqrt(sd**2 + u_reference**2))

    def pct(x: float) -> float:
        return 100.0 * float(np.expm1(x))

    return Offset(
        dataset,
        reference_name,
        n,
        pct(mean),
        (pct(mean - Z95 * sd), pct(mean + Z95 * sd)),
        100.0 * u_reference,
        (pct(mean - Z95 * total), pct(mean + Z95 * total)),
        birge,
        extrapolated,
    )


@dataclass(frozen=True)
class ZScores:
    """z_i = (y_i/r_i - 1)/u_i of one dataset against one reference."""

    dataset: str
    reference: str
    point_ids: np.ndarray
    z: np.ndarray

    @property
    def n_outside(self) -> int:
        """Points with |z| > 2 (outside the 95 % expanded uncertainty)."""
        return int(np.sum(np.abs(self.z) > 2.0))

    def as_dict(self) -> dict[str, object]:
        finite = self.z[np.isfinite(self.z)]
        return {
            "dataset": self.dataset,
            "reference": self.reference,
            "point_ids": self.point_ids.tolist(),
            "z": self.z.tolist(),
            "n_outside": self.n_outside,
            "max_abs": float(np.max(np.abs(finite))) if finite.size else None,
        }


def z_scores(
    values: np.ndarray,
    reference: np.ndarray,
    u_rel: np.ndarray,
    point_ids: np.ndarray,
    *,
    dataset: str,
    reference_name: str,
) -> ZScores:
    with np.errstate(divide="ignore", invalid="ignore"):
        z = (np.asarray(values) / np.asarray(reference) - 1.0) / np.asarray(u_rel)
    return ZScores(dataset, reference_name, np.asarray(point_ids), z)
