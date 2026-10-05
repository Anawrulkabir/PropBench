"""Fitting (README §2: weighted least squares in relative deviation, bounds, multi-start, per-dataset scale factors,
exact Bayesian fit for linear models).

Deviation convention (CLAUDE.md): ARD = 100·(exp - model)/model, positive when the model is below the data.
"""

from propbench.fit.bayes import BayesianLinearFit, bayesian_linear_fit
from propbench.fit.data import FitData, fit_data
from propbench.fit.leastsq import FitError, FitResult, fit
from propbench.fit.stats import Deviations, ard, deviations

__all__ = [
    "BayesianLinearFit",
    "Deviations",
    "FitData",
    "FitError",
    "FitResult",
    "ard",
    "bayesian_linear_fit",
    "deviations",
    "fit",
    "fit_data",
]
