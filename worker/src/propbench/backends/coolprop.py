"""CoolProp backend adapter (MIT; https://coolprop.org).

Uses CoolProp's low-level ``AbstractState`` interface. Input pairs are CoolProp's own names (e.g. ``PT_INPUTS``,
whose values are ordered pressure then temperature); outputs are CoolProp parameter names (e.g. ``Dmass``).

Reference: I. H. Bell, J. Wronski, S. Quoilin, V. Lemort, "Pure and Pseudo-pure Fluid Thermophysical Property
Evaluation and the Open-Source Thermophysical Property Library CoolProp", Ind. Eng. Chem. Res. 53 (2014) 2498-2508,
doi:10.1021/ie4033999.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

import CoolProp
import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np

from propbench.backends.base import BackendError, BatchResult, PhaseResult, PropertyResult, as_pairs
from propbench.core import Phase, UnknownFluidError, identify_fluid

_PHASES = {
    int(CP.iphase_liquid): Phase.LIQUID,
    int(CP.iphase_gas): Phase.VAPOR,
    int(CP.iphase_supercritical): Phase.SUPERCRITICAL,
    int(CP.iphase_supercritical_liquid): Phase.SUPERCRITICAL_LIQUID,
    int(CP.iphase_supercritical_gas): Phase.SUPERCRITICAL_GAS,
    int(CP.iphase_twophase): Phase.TWO_PHASE,
    int(CP.iphase_critical_point): Phase.SUPERCRITICAL,
}


class CoolPropBackend:
    """CoolProp with a chosen equation-of-state family (default ``HEOS``, the reference multiparameter EoS)."""

    def __init__(self, eos: str = "HEOS") -> None:
        self.eos = eos
        self.name = f"CoolProp::{eos}"
        self.version = CoolProp.__version__

    def property(self, fluid: str, pair: str, values: tuple[float, float], output: str) -> PropertyResult:
        if len(values) != 2:
            raise BackendError(f"an input pair needs exactly two values, got {len(values)}")
        v1, v2 = (float(v) for v in values)
        if not (math.isfinite(v1) and math.isfinite(v2)):
            raise BackendError("input values must be finite numbers")
        pair_index = _input_pair_index(pair)
        param_index = _parameter_index(output)
        state = self._state(fluid)
        try:
            state.update(pair_index, v1, v2)
            value = state.keyed_output(param_index)
        except (ValueError, RuntimeError) as exc:
            raise BackendError(str(exc)) from exc
        if not math.isfinite(value):
            raise BackendError(f"{output} is not defined at this state")
        return PropertyResult(value=value, output=output, backend=self.name, backend_version=self.version)

    def properties(
        self,
        fluid: str,
        pair: str,
        values1: np.typing.ArrayLike,
        values2: np.typing.ArrayLike,
        outputs: Sequence[str],
    ) -> BatchResult:
        if not outputs:
            raise BackendError("ask for at least one output")
        a, b = as_pairs(values1, values2)
        pair_index = _input_pair_index(pair)
        params = [_parameter_index(o) for o in outputs]
        state = self._state(fluid)
        result = {o: np.full(len(a), np.nan) for o in outputs}
        errors: dict[int, str] = {}
        for i, (v1, v2) in enumerate(zip(a, b, strict=True)):
            if not (math.isfinite(v1) and math.isfinite(v2)):
                errors[i] = "input values must be finite numbers"
                continue
            try:
                state.update(pair_index, v1, v2)
                for output, param in zip(outputs, params, strict=True):
                    result[output][i] = state.keyed_output(param)
            except (ValueError, RuntimeError) as exc:
                errors[i] = str(exc)
                for output in outputs:
                    result[output][i] = np.nan
        failed = np.zeros(len(a), dtype=bool)
        failed[list(errors)] = True
        for output in outputs:
            result[output].flags.writeable = False
        return BatchResult(result, failed, errors, self.name, self.version)

    def phases(self, fluid: str, temperature: np.typing.ArrayLike, pressure: np.typing.ArrayLike) -> PhaseResult:
        t, p = as_pairs(temperature, pressure)
        state = self._state(fluid)
        phases: list[Phase] = []
        errors: dict[int, str] = {}
        for i, (ti, pi) in enumerate(zip(t, p, strict=True)):
            try:
                state.update(CP.PT_INPUTS, pi, ti)
                phases.append(_PHASES.get(int(state.phase()), Phase.UNKNOWN))
            except (ValueError, RuntimeError) as exc:
                phases.append(Phase.UNKNOWN)
                errors[i] = str(exc)
        return PhaseResult(tuple(phases), errors)

    def _state(self, fluid: str) -> CP.AbstractState:
        try:
            return CP.AbstractState(self.eos, fluid)
        except (ValueError, RuntimeError) as exc:
            first_error = exc
        # Non-HEOS libraries (e.g. PC-SAFT) use their own names ("PROPANE" vs "n-Propane"): try CAS, then aliases.
        for candidate in _alternative_names(fluid):
            try:
                return CP.AbstractState(self.eos, candidate)
            except (ValueError, RuntimeError):
                continue
        raise BackendError(f"unknown fluid '{fluid}' for {self.name}: {first_error}") from first_error


def _alternative_names(fluid: str) -> list[str]:
    try:
        name = identify_fluid(fluid)
    except UnknownFluidError:
        return []
    aliases = CP.get_fluid_param_string(name, "aliases").split(",")
    return [CP.get_fluid_param_string(name, "CAS"), *(a.strip() for a in aliases if a.strip())]


def _input_pair_index(pair: str) -> int:
    """Map a CoolProp input-pair name (e.g. ``PT_INPUTS``) to its index; CoolProp exposes them as module constants."""
    index = getattr(CoolProp, pair, None) if pair.endswith("_INPUTS") else None
    if not isinstance(index, int) or index == CP.INPUT_PAIR_INVALID:
        raise BackendError(f"unknown input pair '{pair}'")
    return index


def _parameter_index(output: str) -> int:
    try:
        return CP.get_parameter_index(output)
    except (ValueError, RuntimeError) as exc:
        raise BackendError(f"unknown output property '{output}'") from exc
