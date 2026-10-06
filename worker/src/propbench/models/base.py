"""The Model protocol (CLAUDE.md conventions): fit, predict, params, bounds, check_values, validity, reference.

Models are immutable: fitting returns a new model with new parameter values (``with_params``). ``fit`` itself is
provided by ``propbench.fit`` (M1.5); every model here exposes what the fitter needs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, Self

import numpy as np

from propbench.core import Quantity


class ModelError(ValueError):
    """A model cannot be evaluated or configured as requested."""


@dataclass(frozen=True)
class Parameter:
    """A model parameter. Fixed parameters are not adjusted by the fitter."""

    name: str
    value: float
    lower: float = -math.inf
    upper: float = math.inf
    fixed: bool = False
    unit: str = "1"
    description: str = ""

    def __post_init__(self) -> None:
        if not self.lower <= self.value <= self.upper:
            raise ModelError(f"parameter {self.name}={self.value} is outside its bounds [{self.lower}, {self.upper}]")


@dataclass(frozen=True)
class CheckValue:
    """A published value the model must reproduce: ``expected`` at (T, molar density), within ``rel_tol``."""

    temperature: float  # K
    molar_density: float  # mol/m³
    expected: float  # SI
    rel_tol: float
    source: str


@dataclass(frozen=True)
class Validity:
    """Range in which the model is documented to be valid (README §8: every model documents its validity range)."""

    t_min: float  # K
    t_max: float  # K
    rhomolar_max: float = math.inf  # mol/m³
    notes: str = ""

    def contains(self, temperature: np.ndarray, molar_density: np.ndarray) -> np.ndarray:
        t, rho = np.asarray(temperature), np.asarray(molar_density)
        return (t >= self.t_min) & (t <= self.t_max) & (rho <= self.rhomolar_max)


class Model(Protocol):
    """A property model of one fluid. ``predict`` takes temperature (K) and molar density (mol/m³) and returns SI."""

    name: str
    fluid: str
    quantity: Quantity

    def predict(self, temperature: np.typing.ArrayLike, molar_density: np.typing.ArrayLike) -> np.ndarray: ...

    def params(self) -> Mapping[str, Parameter]: ...

    def with_params(self, values: Mapping[str, float]) -> Self: ...

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        """Lower and upper bounds of the free (not fixed) parameters, in ``free_names()`` order."""
        ...

    def check_values(self) -> Sequence[CheckValue]: ...

    def validity(self) -> Validity: ...

    def reference(self) -> str: ...


def free_names(model: Model) -> list[str]:
    return [name for name, p in model.params().items() if not p.fixed]


def free_bounds(model: Model) -> tuple[np.ndarray, np.ndarray]:
    params = [p for p in model.params().values() if not p.fixed]
    return np.array([p.lower for p in params]), np.array([p.upper for p in params])


def updated(params: Mapping[str, Parameter], values: Mapping[str, float]) -> dict[str, Parameter]:
    """Copy of ``params`` with new values (bounds are checked); unknown names are an error."""
    unknown = set(values) - set(params)
    if unknown:
        raise ModelError(f"unknown parameters: {sorted(unknown)} (known: {sorted(params)})")
    out = dict(params)
    for name, value in values.items():
        p = params[name]
        out[name] = Parameter(p.name, float(value), p.lower, p.upper, p.fixed, p.unit, p.description)
    return out


def as_states(temperature: np.typing.ArrayLike, molar_density: np.typing.ArrayLike) -> tuple[np.ndarray, np.ndarray]:
    t, rho = np.broadcast_arrays(
        np.atleast_1d(np.asarray(temperature, dtype=float)), np.atleast_1d(np.asarray(molar_density, dtype=float))
    )
    if t.ndim != 1:
        raise ModelError("states must be 1-D")
    if np.any(t <= 0) or np.any(rho < 0) or not (np.all(np.isfinite(t)) and np.all(np.isfinite(rho))):
        raise ModelError("states need positive finite temperatures and non-negative finite densities")
    return np.array(t), np.array(rho)
