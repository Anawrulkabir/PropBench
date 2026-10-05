"""CoolProp backend adapter (MIT; https://coolprop.org).

Uses CoolProp's low-level ``AbstractState`` interface. Input pairs are CoolProp's own names (e.g. ``PT_INPUTS``,
whose values are ordered pressure then temperature); outputs are CoolProp parameter names (e.g. ``Dmass``).

Reference: I. H. Bell, J. Wronski, S. Quoilin, V. Lemort, "Pure and Pseudo-pure Fluid Thermophysical Property
Evaluation and the Open-Source Thermophysical Property Library CoolProp", Ind. Eng. Chem. Res. 53 (2014) 2498-2508,
doi:10.1021/ie4033999.
"""

import math

import CoolProp
import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents

from propbench.backends import BackendError, PropertyResult


class CoolPropBackend:
    """CoolProp with a chosen equation-of-state family (default ``HEOS``, the reference multiparameter EoS)."""

    def __init__(self, eos: str = "HEOS") -> None:
        self.eos = eos
        self.name = f"CoolProp::{eos}"

    def property(self, fluid: str, pair: str, values: tuple[float, float], output: str) -> PropertyResult:
        if len(values) != 2:
            raise BackendError(f"an input pair needs exactly two values, got {len(values)}")
        v1, v2 = (float(v) for v in values)
        if not (math.isfinite(v1) and math.isfinite(v2)):
            raise BackendError("input values must be finite numbers")
        pair_index = _input_pair_index(pair)
        try:
            param_index = CP.get_parameter_index(output)
        except (ValueError, RuntimeError) as exc:
            raise BackendError(f"unknown output property '{output}'") from exc
        try:
            state = CP.AbstractState(self.eos, fluid)
        except (ValueError, RuntimeError) as exc:
            raise BackendError(f"unknown fluid '{fluid}' for {self.name}: {exc}") from exc
        try:
            state.update(pair_index, v1, v2)
            value = state.keyed_output(param_index)
        except (ValueError, RuntimeError) as exc:
            raise BackendError(str(exc)) from exc
        if not math.isfinite(value):
            raise BackendError(f"{output} is not defined at this state")
        return PropertyResult(value=value, output=output, backend=self.name, backend_version=CoolProp.__version__)


def _input_pair_index(pair: str) -> int:
    """Map a CoolProp input-pair name (e.g. ``PT_INPUTS``) to its index; CoolProp exposes them as module constants."""
    index = getattr(CoolProp, pair, None) if pair.endswith("_INPUTS") else None
    if not isinstance(index, int) or index == CP.INPUT_PAIR_INVALID:
        raise BackendError(f"unknown input pair '{pair}'")
    return index
