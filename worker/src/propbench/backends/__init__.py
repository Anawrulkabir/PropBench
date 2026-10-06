"""Thermodynamic backends behind one interface (README §2i; CLAUDE.md backend rules)."""

from propbench.backends.base import Backend, BackendError, BatchResult, PhaseResult, PropertyResult
from propbench.backends.coolprop import CoolPropBackend
from propbench.backends.feos import PCSAFT_PARAMETERS, FeOsBackend, PcSaftParameters
from propbench.backends.registry import BACKENDS, assign_phases, get_backend

__all__ = [
    "BACKENDS",
    "PCSAFT_PARAMETERS",
    "Backend",
    "BackendError",
    "BatchResult",
    "CoolPropBackend",
    "FeOsBackend",
    "PcSaftParameters",
    "PhaseResult",
    "PropertyResult",
    "assign_phases",
    "get_backend",
]
