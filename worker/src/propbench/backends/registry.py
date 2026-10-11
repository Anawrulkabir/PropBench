"""Backend lookup by name, and phase assignment of datasets from an equation of state (README §2c, data check)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from propbench.backends.base import Backend, BackendError
from propbench.backends.coolprop import CoolPropBackend
from propbench.backends.feos import FeOsBackend
from propbench.core import Dataset, DatasetError, Phase

BACKENDS: dict[str, Callable[[], Backend]] = {
    "CoolProp::HEOS": lambda: CoolPropBackend("HEOS"),
    "CoolProp::PCSAFT": lambda: CoolPropBackend("PCSAFT"),
    "CoolProp::PR": lambda: CoolPropBackend("PR"),
    "CoolProp::SRK": lambda: CoolPropBackend("SRK"),
    "FeOs::PC-SAFT": FeOsBackend,
}


def get_backend(name: str = "CoolProp::HEOS") -> Backend:
    try:
        return BACKENDS[name]()
    except KeyError:
        raise BackendError(f"unknown backend '{name}' (available: {sorted(BACKENDS)})") from None


# Phases that count as agreeing with a phase stated in a file. Papers often call dense states above the critical
# point "liquid" (CoolProp: supercritical = T > Tc and p > pc; supercritical liquid = p > pc, T < Tc; supercritical
# gas = T > Tc, p < pc). Only liquid/vapour contradictions are flagged.
_COMPATIBLE = {
    Phase.LIQUID: {Phase.LIQUID, Phase.SUPERCRITICAL_LIQUID, Phase.SUPERCRITICAL},
    Phase.VAPOR: {Phase.VAPOR, Phase.SUPERCRITICAL_GAS, Phase.SUPERCRITICAL},
    Phase.SUPERCRITICAL: {Phase.SUPERCRITICAL, Phase.SUPERCRITICAL_LIQUID, Phase.SUPERCRITICAL_GAS},
}


@dataclass(frozen=True)
class PhaseCheck:
    """A dataset with EoS phases, and the point ids where the phase stated in the file disagrees."""

    dataset: Dataset
    stated: tuple[Phase, ...] | None
    mismatches: tuple[int, ...]
    errors: dict[int, str]


def assign_phases(dataset: Dataset, backend: Backend) -> PhaseCheck:
    """Assign each (T, p) point the phase from ``backend`` and compare with the phase stated in the source.

    On the saturation curve the EoS cannot tell liquid from vapour (two-phase or no answer): there the phase stated
    in the source (e.g. saturated liquid) is kept and not counted as a disagreement.
    """
    if dataset.pressure is None:
        raise DatasetError("phase assignment needs pressures")
    result = backend.phases(dataset.fluid, dataset.temperature, dataset.pressure)
    ambiguous = (Phase.UNKNOWN, Phase.TWO_PHASE)
    phases = list(result.phases)
    on_saturation = {
        i
        for i, computed in enumerate(result.phases)
        if computed is Phase.TWO_PHASE or "saturation" in result.errors.get(i, "").lower()
    }
    mismatches = []
    if dataset.phase is not None:
        for i, (pid, stated, computed) in enumerate(zip(dataset.point_ids, dataset.phase, result.phases, strict=True)):
            if i in on_saturation:
                if stated not in ambiguous:
                    phases[i] = stated
            elif stated in _COMPATIBLE and computed is not Phase.UNKNOWN and computed not in _COMPATIBLE[stated]:
                mismatches.append(int(pid))
    errors = {
        int(dataset.point_ids[i]): message
        for i, message in result.errors.items()
        if not (i in on_saturation and phases[i] not in ambiguous)
    }
    return PhaseCheck(dataset.with_phase(phases), dataset.phase, tuple(mismatches), errors)
