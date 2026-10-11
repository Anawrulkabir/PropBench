"""FeOs backend adapter: PC-SAFT (MIT OR Apache-2.0; https://github.com/feos-org/feos).

FeOs is an on-demand component (README §2b): it is imported only when this backend is used, and the rest of
PropBench works without it.

PC-SAFT: J. Gross, G. Sadowski, "Perturbed-Chain SAFT: An Equation of State Based on a Perturbation Theory for Chain
Molecules", Ind. Eng. Chem. Res. 40 (2001) 1244-1260, doi:10.1021/ie0003887. FeOs: P. Rehner, G. Bauer, J. Gross,
"FeOs: An Open-Source Framework for Equations of State and Classical Density Functional Theory", Ind. Eng. Chem. Res.
62 (2023) 5347-5357, doi:10.1021/acs.iecr.2c04561.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import cached_property
from typing import Any

import numpy as np

from propbench.backends.base import BackendError, BatchResult, PhaseResult, PropertyResult, as_pairs
from propbench.core import Phase, UnknownFluidError, identify_fluid


@dataclass(frozen=True)
class PcSaftParameters:
    """Pure-component PC-SAFT parameters of a non-associating, non-polar fluid."""

    m: float  # segment number
    sigma: float  # segment diameter, Å
    epsilon_k: float  # dispersion energy ε/k, K
    molar_mass: float  # g/mol
    reference: str


_GROSS_SADOWSKI_2001 = "Gross & Sadowski, Ind. Eng. Chem. Res. 40 (2001) 1244, Table 1"

# Published parameters (keys are the fluid library's canonical names).
PCSAFT_PARAMETERS: dict[str, PcSaftParameters] = {
    "Methane": PcSaftParameters(1.0000, 3.7039, 150.03, 16.043, _GROSS_SADOWSKI_2001),
    "Ethane": PcSaftParameters(1.6069, 3.5206, 191.42, 30.070, _GROSS_SADOWSKI_2001),
    "n-Propane": PcSaftParameters(2.0020, 3.6184, 208.11, 44.096, _GROSS_SADOWSKI_2001),
    "n-Butane": PcSaftParameters(2.3316, 3.7086, 222.88, 58.123, _GROSS_SADOWSKI_2001),
}


def available_parameters() -> dict[str, PcSaftParameters]:
    """``PCSAFT_PARAMETERS`` plus parameters of installed ``parameters`` components (``pcsaft.json``: canonical
    fluid name → {m, sigma, epsilon_k, molar_mass, reference}); bundled values win on conflicts."""
    import json

    from propbench import components

    out: dict[str, PcSaftParameters] = {}
    for path in components.files("parameters", "pcsaft.json"):
        try:
            for name, p in json.loads(path.read_text(encoding="utf-8")).items():
                out[str(name)] = PcSaftParameters(
                    float(p["m"]), float(p["sigma"]), float(p["epsilon_k"]), float(p["molar_mass"]), str(p["reference"])
                )
        except (ValueError, KeyError, TypeError, AttributeError):
            continue
    out.update(PCSAFT_PARAMETERS)
    return out


_PAIRS = {"PT_INPUTS", "DmolarT_INPUTS"}
OUTPUTS = ("T", "P", "Dmolar", "Dmass", "Z", "Smolar_residual")


class FeOsBackend:
    """PC-SAFT through FeOs. Parameters come from ``PCSAFT_PARAMETERS`` or are passed in (e.g. fitted ones)."""

    def __init__(self, parameters: Mapping[str, PcSaftParameters] | None = None) -> None:
        self.name = "FeOs::PC-SAFT"
        self._parameters = dict(available_parameters() if parameters is None else parameters)
        self._eos_cache: dict[str, Any] = {}

    @cached_property
    def version(self) -> str:
        return str(self._feos.__version__)

    @cached_property
    def _feos(self) -> Any:
        try:
            import feos
        except ImportError as exc:  # pragma: no cover - exercised only without the component
            raise BackendError("the FeOs component is not installed") from exc
        return feos

    @cached_property
    def _si(self) -> Any:
        import si_units

        return si_units

    def property(self, fluid: str, pair: str, values: tuple[float, float], output: str) -> PropertyResult:
        if len(values) != 2:
            raise BackendError(f"an input pair needs exactly two values, got {len(values)}")
        batch = self.properties(fluid, pair, [values[0]], [values[1]], [output])
        if batch.failed[0]:
            raise BackendError(batch.errors[0])
        return PropertyResult(float(batch[output][0]), output, self.name, self.version)

    def properties(
        self,
        fluid: str,
        pair: str,
        values1: np.typing.ArrayLike,
        values2: np.typing.ArrayLike,
        outputs: Sequence[str],
    ) -> BatchResult:
        if pair not in _PAIRS:
            raise BackendError(f"input pair '{pair}' is not supported by {self.name} (use {sorted(_PAIRS)})")
        unknown = [o for o in outputs if o not in OUTPUTS]
        if unknown or not outputs:
            raise BackendError(f"outputs {unknown or '[]'} are not supported by {self.name} (use {list(OUTPUTS)})")
        a, b = as_pairs(values1, values2)
        eos, molar_mass = self._eos(fluid)
        result = {o: np.full(len(a), np.nan) for o in outputs}
        errors: dict[int, str] = {}
        for i, (v1, v2) in enumerate(zip(a, b, strict=True)):
            if not (math.isfinite(v1) and math.isfinite(v2)) or v1 <= 0 or v2 <= 0:
                errors[i] = "input values must be positive finite numbers"
                continue
            try:
                state = self._state(eos, pair, v1, v2)
                for output in outputs:
                    result[output][i] = self._output(state, output, molar_mass)
            except (RuntimeError, ValueError) as exc:
                errors[i] = str(exc)
                for output in outputs:
                    result[output][i] = np.nan
        failed = np.zeros(len(a), dtype=bool)
        failed[list(errors)] = True
        for output in outputs:
            result[output].flags.writeable = False
        return BatchResult(result, failed, errors, self.name, self.version)

    def phases(self, fluid: str, temperature: np.typing.ArrayLike, pressure: np.typing.ArrayLike) -> PhaseResult:
        """Above the critical temperature: supercritical; below: liquid if p > psat(T), else vapour."""
        t, p = as_pairs(temperature, pressure)
        eos, _ = self._eos(fluid)
        si, feos = self._si, self._feos
        critical = feos.State.critical_point(eos)
        t_c = critical.temperature / si.KELVIN
        phases: list[Phase] = []
        errors: dict[int, str] = {}
        for i, (ti, pi) in enumerate(zip(t, p, strict=True)):
            if ti >= t_c:
                phases.append(Phase.SUPERCRITICAL)
                continue
            try:
                vle = feos.PhaseEquilibrium.pure(eos, ti * si.KELVIN)
                p_sat = vle.liquid.pressure() / si.PASCAL
                phases.append(Phase.LIQUID if pi > p_sat else Phase.VAPOR)
            except RuntimeError as exc:
                phases.append(Phase.UNKNOWN)
                errors[i] = str(exc)
        return PhaseResult(tuple(phases), errors)

    def _eos(self, fluid: str) -> tuple[Any, float]:
        try:
            key = identify_fluid(fluid)
        except UnknownFluidError:
            key = fluid
        params = self._parameters.get(key)
        if params is None:
            raise BackendError(f"no PC-SAFT parameters for '{fluid}' (known: {sorted(self._parameters)})")
        if key not in self._eos_cache:
            feos = self._feos
            record = feos.PureRecord(
                feos.Identifier(name=key), params.molar_mass, m=params.m, sigma=params.sigma, epsilon_k=params.epsilon_k
            )
            self._eos_cache[key] = feos.EquationOfState.pcsaft(feos.Parameters.new_pure(record))
        return self._eos_cache[key], params.molar_mass

    def _state(self, eos: Any, pair: str, v1: float, v2: float) -> Any:
        si, feos = self._si, self._feos
        if pair == "PT_INPUTS":
            return feos.State(eos, temperature=v2 * si.KELVIN, pressure=v1 * si.PASCAL)
        return feos.State(eos, temperature=v2 * si.KELVIN, density=v1 * si.MOL / si.METER**3)

    def _output(self, state: Any, output: str, molar_mass: float) -> float:
        si, feos = self._si, self._feos
        if output == "T":
            return state.temperature / si.KELVIN
        if output == "P":
            return state.pressure() / si.PASCAL
        molar_density = state.density / (si.MOL / si.METER**3)
        if output == "Dmolar":
            return molar_density
        if output == "Dmass":
            return molar_density * molar_mass / 1000.0
        if output == "Z":
            return state.compressibility()
        return state.molar_entropy(feos.Contributions.Residual) / (si.JOULE / si.MOL / si.KELVIN)
