"""Residual entropy scaling of the viscosity with PC-SAFT, through FeOs (README §2, M1.4b).

    ln(η / η_CE) = A + B·s + C·s² + D·s³,   s = s_res / (R·m)

η_CE is the Chapman-Enskog viscosity of the PC-SAFT segment (σ, ε/k, Neufeld Ω₂₂) and s_res the residual molar
entropy from PC-SAFT. Both come from FeOs (``State.viscosity_reference`` and ``State.molar_entropy``); only the
polynomial A…D is fitted here, so the model is glue around FeOs rather than a re-implementation.

Method: O. Lötgering-Lin, J. Gross, "Group Contribution Method for Viscosities Based on Entropy Scaling Using the
Perturbed-Chain Polar Statistical Associating Fluid Theory", Ind. Eng. Chem. Res. 54 (2015) 7942-7952,
doi:10.1021/acs.iecr.5b01698. FeOs: Rehner, Bauer, Gross, Ind. Eng. Chem. Res. 62 (2023) 5347,
doi:10.1021/acs.iecr.2c04561 (MIT OR Apache-2.0).

The model is evaluated at the given (T, ρ). Published entropy-scaling values are usually quoted at (T, p); to
reproduce them, pass the PC-SAFT density at (T, p) (``pcsaft_density``).

For a fluid without published PC-SAFT parameters, ``fit_pcsaft_to_eos`` fits m, σ and ε/k to the reference
equation of state's vapour pressure and saturated liquid density (the usual way PC-SAFT parameters are obtained,
Gross & Sadowski 2001), with a fixed, deterministic start.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import cache
from typing import Any, Self

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np
from scipy.optimize import least_squares

from propbench.backends.feos import PCSAFT_PARAMETERS, PcSaftParameters
from propbench.core import Quantity, identify_fluid
from propbench.models.base import (
    CheckValue,
    ModelError,
    Parameter,
    Validity,
    as_states,
    free_bounds,
    updated,
)

R = 8.31446261815324  # J/(mol·K)
NAMES = ("A", "B", "C", "D")
LOTGERING_LIN_2015 = "Lötgering-Lin & Gross, Ind. Eng. Chem. Res. 54 (2015) 7942, doi:10.1021/acs.iecr.5b01698"


def _feos() -> tuple[Any, Any]:
    try:
        import feos
        import si_units
    except ImportError as exc:  # pragma: no cover - exercised only without the component
        raise ModelError("residual entropy scaling needs the FeOs component") from exc
    return feos, si_units


def _eos(p: PcSaftParameters) -> Any:
    feos, _ = _feos()
    record = feos.PureRecord(feos.Identifier(name="fluid"), p.molar_mass, m=p.m, sigma=p.sigma, epsilon_k=p.epsilon_k)
    return feos.EquationOfState.pcsaft(feos.Parameters.new_pure(record))


def pcsaft_density(parameters: PcSaftParameters, temperature: float, pressure: float) -> float:
    """PC-SAFT molar density (mol/m³) at (T, p); the stable phase is chosen by FeOs."""
    feos, si = _feos()
    state = feos.State(_eos(parameters), temperature=temperature * si.KELVIN, pressure=pressure * si.PASCAL)
    return float(state.density / (si.MOL / si.METER**3))


@cache
def fit_pcsaft_to_eos(fluid: str, n_points: int = 15) -> PcSaftParameters:
    """PC-SAFT m, σ (Å), ε/k (K) fitted to the reference EoS: ln p_sat and saturated liquid density at ``n_points``
    temperatures between 0.55 and 0.9 T_c. Deterministic (fixed start from the critical point)."""
    feos, si = _feos()
    name = identify_fluid(fluid)
    tc, mm = CP.PropsSI("Tcrit", name), CP.PropsSI("molar_mass", name) * 1e3
    t_min = max(0.55 * tc, CP.PropsSI("Tmin", name) + 1.0)
    temps = np.linspace(t_min, 0.9 * tc, n_points)
    p_sat = np.array([CP.PropsSI("P", "T", t, "Q", 0, name) for t in temps])
    rho_l = np.array([CP.PropsSI("Dmolar", "T", t, "Q", 0, name) for t in temps])

    def residuals(x: np.ndarray) -> np.ndarray:
        eos = _eos(PcSaftParameters(x[0], x[1], x[2], mm, ""))
        out = []
        for t, p, rho in zip(temps, p_sat, rho_l, strict=True):
            try:
                vle = feos.PhaseEquilibrium.pure(eos, t * si.KELVIN)
                out.append(math.log(vle.liquid.pressure() / si.PASCAL / p))
                out.append(vle.liquid.density / (si.MOL / si.METER**3) / rho - 1.0)
            except RuntimeError:
                out.extend([1.0, 1.0])
        return np.array(out)

    rhoc = CP.PropsSI("rhomolar_critical", name)
    sigma0 = 0.809 * (1e6 / rhoc / 2.0) ** (1 / 3)  # Chung et al. 1988 σ (Å) shared by two segments
    start = np.array([2.0, sigma0, tc / 1.6])
    fit = least_squares(residuals, start, bounds=([1.0, 2.0, 50.0], [8.0, 6.0, 800.0]), x_scale="jac")
    if not fit.success or float(np.sqrt(np.mean(fit.fun**2))) > 0.05:
        raise ModelError(f"PC-SAFT parameters for {name} could not be fitted to the reference EoS")
    m, sigma, eps = (float(v) for v in fit.x)
    return PcSaftParameters(m, sigma, eps, mm, f"fitted to the {name} reference EoS (p_sat, ρ_liq), PropBench")


def pcsaft_parameters(fluid: str) -> PcSaftParameters:
    """Published PC-SAFT parameters when PropBench has them, otherwise parameters fitted to the reference EoS."""
    name = identify_fluid(fluid)
    return PCSAFT_PARAMETERS.get(name) or fit_pcsaft_to_eos(name)


@dataclass(frozen=True, eq=False)
class ResidualEntropyViscosity:
    """Entropy-scaling viscosity of ``fluid`` with PC-SAFT parameters ``pcsaft``; parameters A, B, C, D."""

    fluid: str
    pcsaft: PcSaftParameters
    parameters: Mapping[str, Parameter] = field(default_factory=dict)
    checks: tuple[CheckValue, ...] = ()
    source: str = LOTGERING_LIN_2015
    name: str = "Residual entropy scaling (viscosity)"
    quantity: Quantity = Quantity.VISCOSITY
    _cache: dict[bytes, tuple[np.ndarray, np.ndarray]] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def create(
        cls,
        fluid: str,
        pcsaft: PcSaftParameters | None = None,
        coefficients: Sequence[float] = (-0.8, -2.0, -0.3, -0.05),
        checks: Sequence[CheckValue] = (),
    ) -> Self:
        if len(coefficients) != 4:
            raise ModelError("entropy scaling needs four coefficients A, B, C, D")
        name = identify_fluid(fluid)
        params = {
            n: Parameter(n, float(v), -20.0, 20.0, description=f"coefficient of s^{i} in ln(η/η_CE)")
            for i, (n, v) in enumerate(zip(NAMES, coefficients, strict=True))
        }
        return cls(name, pcsaft or pcsaft_parameters(name), params, tuple(checks))

    def _scaling(self, t: np.ndarray, rho: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """η_CE (Pa·s) and s = s_res/(R·m) from FeOs, cached per state set (only A…D change during a fit)."""
        key = t.tobytes() + rho.tobytes()
        if key not in self._cache:
            feos, si = _feos()
            eos = _eos(self.pcsaft)
            eta_ce, s = np.full(len(t), np.nan), np.full(len(t), np.nan)
            for i, (ti, ri) in enumerate(zip(t, rho, strict=True)):
                try:
                    st = feos.State(eos, temperature=ti * si.KELVIN, density=ri * si.MOL / si.METER**3)
                    eta_ce[i] = st.viscosity_reference() / (si.PASCAL * si.SECOND)
                    s_res = st.molar_entropy(feos.Contributions.Residual) / (si.JOULE / si.MOL / si.KELVIN)
                    s[i] = s_res / (R * self.pcsaft.m)
                except (RuntimeError, ValueError):
                    pass
            if len(self._cache) > 64:
                self._cache.clear()
            self._cache[key] = (eta_ce, s)
        return self._cache[key]

    def predict(self, temperature: np.typing.ArrayLike, molar_density: np.typing.ArrayLike) -> np.ndarray:
        t, rho = as_states(temperature, molar_density)
        eta_ce, s = self._scaling(t, rho)
        a, b, c, d = (self.parameters[n].value for n in NAMES)
        return eta_ce * np.exp(a + b * s + c * s**2 + d * s**3)

    def params(self) -> Mapping[str, Parameter]:
        return self.parameters

    def with_params(self, values: Mapping[str, float]) -> Self:
        return type(self)(
            self.fluid,
            self.pcsaft,
            updated(self.parameters, values),
            self.checks,
            self.source,
            self.name,
            self.quantity,
            self._cache,  # same states and PC-SAFT parameters: the FeOs results stay valid
        )

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return free_bounds(self)

    def check_values(self) -> Sequence[CheckValue]:
        return self.checks

    def validity(self) -> Validity:
        return Validity(
            CP.PropsSI("Ttriple", self.fluid),
            2.0 * CP.PropsSI("Tcrit", self.fluid),
            notes="entropy scaling extrapolates smoothly in T and p; PC-SAFT state at the given density",
        )

    def reference(self) -> str:
        return f"{self.source}; PC-SAFT: {self.pcsaft.reference}"
