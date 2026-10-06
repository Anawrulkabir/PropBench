"""The single interface through which all property calls go (CLAUDE.md, backend rules)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import numpy as np

from propbench.core import Phase


class BackendError(Exception):
    """A backend could not compute the requested property (unknown fluid, invalid state, ...)."""


@dataclass(frozen=True)
class PropertyResult:
    """One property value in SI units, with the provenance needed to reproduce it."""

    value: float
    output: str
    backend: str
    backend_version: str


@dataclass(frozen=True)
class BatchResult:
    """Properties at many states. Failed states are NaN in every output; ``errors`` maps their index to a reason."""

    outputs: dict[str, np.ndarray]
    failed: np.ndarray
    errors: dict[int, str]
    backend: str
    backend_version: str

    def __getitem__(self, output: str) -> np.ndarray:
        return self.outputs[output]


@dataclass(frozen=True)
class PhaseResult:
    phases: tuple[Phase, ...]
    errors: dict[int, str] = field(default_factory=dict)


class Backend(Protocol):
    """A thermodynamic backend (README §2i). All values are SI.

    Input pairs and outputs use CoolProp's names (e.g. ``PT_INPUTS`` with values pressure then temperature; ``Dmass``,
    ``Dmolar``, ``Smolar_residual``). A backend implements the subset it supports and raises ``BackendError`` for the
    rest.
    """

    name: str

    def property(self, fluid: str, pair: str, values: tuple[float, float], output: str) -> PropertyResult:
        """One property at one state; raises ``BackendError`` if the state cannot be computed."""
        ...

    def properties(
        self,
        fluid: str,
        pair: str,
        values1: np.typing.ArrayLike,
        values2: np.typing.ArrayLike,
        outputs: Sequence[str],
    ) -> BatchResult:
        """Several properties at many states in one call. Bad inputs raise; states that fail are NaN."""
        ...

    def phases(self, fluid: str, temperature: np.typing.ArrayLike, pressure: np.typing.ArrayLike) -> PhaseResult:
        """Phase of each (T, p) state according to this backend's equation of state."""
        ...


def as_pairs(values1: np.typing.ArrayLike, values2: np.typing.ArrayLike) -> tuple[np.ndarray, np.ndarray]:
    """Two equally long 1-D float arrays (scalars broadcast)."""
    first = np.atleast_1d(np.asarray(values1, dtype=float))
    second = np.atleast_1d(np.asarray(values2, dtype=float))
    a, b = np.broadcast_arrays(first, second)
    if a.ndim != 1:
        raise BackendError("state values must be 1-D")
    return np.array(a, dtype=float), np.array(b, dtype=float)
