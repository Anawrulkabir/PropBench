"""The single interface through which all property calls go (CLAUDE.md, backend rules)."""

from dataclasses import dataclass
from typing import Protocol


class BackendError(Exception):
    """A backend could not compute the requested property (unknown fluid, invalid state, ...)."""


@dataclass(frozen=True)
class PropertyResult:
    """One property value in SI units, with the provenance needed to reproduce it."""

    value: float
    output: str
    backend: str
    backend_version: str


class Backend(Protocol):
    """A thermodynamic backend (README §2i). All values are SI."""

    name: str

    def property(self, fluid: str, pair: str, values: tuple[float, float], output: str) -> PropertyResult:
        """Return ``output`` for ``fluid`` at the state given by input ``pair`` and ``values``."""
        ...
