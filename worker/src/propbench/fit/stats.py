"""Deviation statistics with the project-wide sign convention ARD = 100·(exp - model)/model."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def ard(experimental: np.typing.ArrayLike, model: np.typing.ArrayLike) -> np.ndarray:
    """Relative deviation in %, positive when the model is below the data."""
    exp, mod = np.asarray(experimental, dtype=float), np.asarray(model, dtype=float)
    return 100.0 * (exp - mod) / mod


@dataclass(frozen=True)
class Deviations:
    n: int
    aard: float  # mean |ARD|, %
    bias: float  # mean ARD, %
    rms: float  # root mean square ARD, %
    max_abs: float  # max |ARD|, %

    def as_dict(self) -> dict[str, float]:
        return {"n": self.n, "aard": self.aard, "bias": self.bias, "rms": self.rms, "max_abs": self.max_abs}


def deviations(experimental: np.typing.ArrayLike, model: np.typing.ArrayLike) -> Deviations:
    d = ard(experimental, model)
    if d.size == 0:
        return Deviations(0, float("nan"), float("nan"), float("nan"), float("nan"))
    return Deviations(
        n=int(d.size),
        aard=float(np.mean(np.abs(d))),
        bias=float(np.mean(d)),
        rms=float(np.sqrt(np.mean(d**2))),
        max_abs=float(np.max(np.abs(d))),
    )
