"""Exact Bayesian fit of a linear model y = X b + e, e ~ N(0, diag σ²), with a Gaussian prior b ~ N(m0, S0).

Posterior: S_n = (S0⁻¹ + Xᵀ Σ⁻¹ X)⁻¹,  m_n = S_n (S0⁻¹ m0 + Xᵀ Σ⁻¹ y). Without a prior (S0⁻¹ = 0) this is generalized
least squares. The log marginal likelihood (evidence) supports model comparison. C. M. Bishop, Pattern Recognition and
Machine Learning (2006), §3.3; for a flat prior the evidence is not defined and is returned as NaN.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BayesianLinearFit:
    mean: np.ndarray
    covariance: np.ndarray
    log_evidence: float

    @property
    def standard_errors(self) -> np.ndarray:
        return np.sqrt(np.diag(self.covariance))

    def predict(self, design: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Posterior predictive mean and standard deviation of the model (without the noise term)."""
        x = np.atleast_2d(design)
        return x @ self.mean, np.sqrt(np.einsum("ij,jk,ik->i", x, self.covariance, x))


def bayesian_linear_fit(
    design: np.typing.ArrayLike,
    y: np.typing.ArrayLike,
    sigma: np.typing.ArrayLike,
    prior_mean: np.typing.ArrayLike | None = None,
    prior_covariance: np.typing.ArrayLike | None = None,
) -> BayesianLinearFit:
    x = np.atleast_2d(np.asarray(design, dtype=float))
    yv = np.asarray(y, dtype=float)
    s = np.broadcast_to(np.asarray(sigma, dtype=float), yv.shape)
    if x.shape[0] != yv.shape[0]:
        raise ValueError("design and y must have the same number of rows")
    if np.any(s <= 0):
        raise ValueError("sigma must be positive")
    p = x.shape[1]
    w = 1.0 / s**2
    xtwx = x.T @ (x * w[:, None])
    xtwy = x.T @ (w * yv)
    if prior_covariance is None:
        prior_precision = np.zeros((p, p))
        m0 = np.zeros(p)
    else:
        s0 = np.asarray(prior_covariance, dtype=float)
        prior_precision = np.linalg.inv(s0)
        m0 = np.zeros(p) if prior_mean is None else np.asarray(prior_mean, dtype=float)
    precision = prior_precision + xtwx
    cov = np.linalg.inv(precision)
    mean = cov @ (prior_precision @ m0 + xtwy)
    if prior_covariance is None:
        log_evidence = float("nan")
    else:
        # y ~ N(X m0, Σ + X S0 Xᵀ)
        marginal = np.diag(s**2) + x @ np.asarray(prior_covariance, dtype=float) @ x.T
        resid = yv - x @ m0
        _, logdet = np.linalg.slogdet(marginal)
        log_evidence = float(-0.5 * (resid @ np.linalg.solve(marginal, resid) + logdet + len(yv) * np.log(2 * np.pi)))
    return BayesianLinearFit(mean, cov, log_evidence)
