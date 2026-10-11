"""Extended corresponding states (ECS) thermal conductivity.

M.O. McLinden, S.A. Klein, R.A. Perkins, Int. J. Refrig. 23 (2000) 43; M.L. Huber, A. Laesecke, R.A. Perkins,
Ind. Eng. Chem. Res. 42 (2003) 3163; as used for the fluids of NISTIR 8209 (M.L. Huber, 2018,
doi:10.6028/NIST.IR.8209):

    λ(T, ρ)  = λ*(T) + λ_ref^r(T₀, ρ₀ χ(δ)) · F_λ + λ_c(T, ρ)
    λ*       = f_int η* (c_p⁰ - 5R/2)/M + 15 R η*/(4 M)            (modified Eucken; η* the dilute-gas viscosity)
    F_λ      = √f · h^(-2/3) · √(M₀/M),  f = T/T₀,  h = ρ₀/ρ
    f_int    = Σ aᵢ Tⁱ,  χ(δ) = Σ bᵢ δⁱ,  δ = ρ/ρ_red

(T₀, ρ₀) is the conformal state of the reference fluid (same αʳ and Z as the target, see ``conformal_state``);
λ_ref^r is the residual (background) conductivity of the reference fluid's own correlation, taken from CoolProp;
λ_c is the simplified Olchowy-Sengers enhancement of the target with the total viscosity of its ECS viscosity model.
f_int is in the units of the reports (η* in μPa·s, λ in mW/(m·K)), so in SI λ_int = 10³·f_int·η*·(c_p⁰ - 5R/2)/M.

Verified against the NISTIR 8209 check value for CF₃I (Table 7) in tests/models/test_reference.py.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import Self

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np

from propbench.core import Quantity
from propbench.models.base import CheckValue, ModelError, Parameter, Validity, as_states, free_bounds, updated
from propbench.models.critical import CriticalEnhancement
from propbench.models.ecs import ECSViscosity, conformal_state

GAS_CONSTANT = 8.314462618  # J/(mol·K), CODATA 2018


@dataclass(frozen=True)
class ECSConductivity:
    """ECS thermal conductivity of ``viscosity.fluid`` with the reference fluid of its viscosity model.

    Parameters: ``f_int_0 … f_int_n`` (coefficients of f_int in Tⁱ) and ``chi_0 … chi_n`` (χ in δⁱ); by default
    χ is fitted and f_int fixed. The dilute-gas viscosity (σ, ε/k, factor k) and the total viscosity in the critical
    term come from ``viscosity``.
    """

    viscosity: ECSViscosity
    chi_exponents: tuple[float, ...]
    chi_rhomolar_reducing: float  # mol/m³
    critical: CriticalEnhancement | None
    parameters: Mapping[str, Parameter] = field(default_factory=dict)
    source: str = "McLinden, Klein, Perkins, Int. J. Refrig. 23 (2000) 43; Huber et al., IECR 42 (2003) 3163"
    name: str = "ECS thermal conductivity"
    quantity: Quantity = Quantity.THERMAL_CONDUCTIVITY

    @classmethod
    def create(
        cls,
        viscosity: ECSViscosity,
        *,
        f_int: Sequence[float] = (1.32e-3,),
        chi: Sequence[float] = (1.0,),
        chi_exponents: Sequence[float] | None = None,
        chi_rhomolar_reducing: float | None = None,
        critical: CriticalEnhancement | None = None,
        fit_f_int: bool = False,
    ) -> Self:
        exponents = tuple(float(e) for e in (chi_exponents if chi_exponents is not None else range(len(chi))))
        if len(exponents) != len(chi):
            raise ModelError("chi and chi_exponents must have the same length")
        params: dict[str, Parameter] = {
            f"f_int_{i}": Parameter(
                f"f_int_{i}", float(a), -1.0, 1.0, fixed=not fit_f_int, description=f"f_int · T^{i}"
            )
            for i, a in enumerate(f_int)
        }
        for i, (b, e) in enumerate(zip(chi, exponents, strict=True)):
            params[f"chi_{i}"] = Parameter(f"chi_{i}", float(b), -10.0, 10.0, description=f"χ coefficient of δ^{e:g}")
        rho_red = chi_rhomolar_reducing or CP.PropsSI("rhomolar_critical", viscosity.fluid)
        return cls(viscosity, exponents, float(rho_red), critical, params)

    @property
    def fluid(self) -> str:
        return self.viscosity.fluid

    @property
    def reference_fluid(self) -> str:
        return self.viscosity.reference_fluid

    @cached_property
    def _molar_masses(self) -> tuple[float, float]:
        return CP.PropsSI("molar_mass", self.fluid), CP.PropsSI("molar_mass", self.reference_fluid)

    def f_int(self, temperature: np.ndarray) -> np.ndarray:
        n = sum(1 for k in self.parameters if k.startswith("f_int_"))
        return sum(self.parameters[f"f_int_{i}"].value * temperature**i for i in range(n)) * np.ones_like(temperature)

    def chi(self, molar_density: np.ndarray) -> np.ndarray:
        d = molar_density / self.chi_rhomolar_reducing
        return sum(self.parameters[f"chi_{i}"].value * d**e for i, e in enumerate(self.chi_exponents)) * np.ones_like(d)

    def dilute(self, temperature: np.typing.ArrayLike) -> np.ndarray:
        """λ*(T): modified Eucken internal part plus the translational part, W/(m·K)."""
        t = np.atleast_1d(np.asarray(temperature, dtype=float))
        m, _ = self._molar_masses
        eta = self.viscosity.dilute(t)
        state = CP.AbstractState("HEOS", self.fluid)
        cp0 = np.empty_like(t)
        for i, ti in enumerate(t):
            state.update(CP.DmolarT_INPUTS, 1e-6, ti)
            cp0[i] = state.cp0molar()
        internal = 1e3 * self.f_int(t) * eta * (cp0 - 2.5 * GAS_CONSTANT) / m  # f_int in report units, see above
        translational = 15.0 * GAS_CONSTANT * eta / (4.0 * m)
        return internal + translational

    def predict(self, temperature: np.typing.ArrayLike, molar_density: np.typing.ArrayLike) -> np.ndarray:
        t, rho = as_states(temperature, molar_density)
        target = CP.AbstractState("HEOS", self.fluid)
        reference = CP.AbstractState("HEOS", self.reference_fluid)
        m, m0 = self._molar_masses
        lam = self.dilute(t)
        chi = self.chi(rho)
        for i, (ti, rhoi) in enumerate(zip(t, rho, strict=True)):
            if rhoi == 0.0:
                continue
            try:
                target.update(CP.DmolarT_INPUTS, rhoi, ti)
                state = conformal_state(target, reference)
                reference.update(CP.DmolarT_INPUTS, state.rhomolar0 * chi[i], state.t0)
                parts = reference.conductivity_contributions()
                background = parts["residual"] + parts["initial_density"]
                f, h = ti / state.t0, state.rhomolar0 / rhoi
                lam[i] += background * np.sqrt(f) * h ** (-2.0 / 3.0) * np.sqrt(m0 / m)
                if self.critical is not None:
                    target.update(CP.DmolarT_INPUTS, rhoi, ti)
                    eta = float(self.viscosity.predict([ti], [rhoi])[0])
                    lam[i] += self.critical.value(target, eta)
            except ValueError as exc:
                raise ModelError(f"ECS conductivity failed at T={ti} K, rho={rhoi} mol/m3: {exc}") from exc
        return lam

    def params(self) -> Mapping[str, Parameter]:
        return dict(self.parameters)

    def with_params(self, values: Mapping[str, float]) -> Self:
        return replace(self, parameters=updated(self.parameters, values))

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return free_bounds(self)

    def check_values(self) -> Sequence[CheckValue]:
        return ()

    def validity(self) -> Validity:
        return self.viscosity.validity()

    def reference(self) -> str:
        return self.source
