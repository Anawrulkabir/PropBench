"""Dilute-gas and generalized viscosity models.

- Collision integral Ω(2,2)*: P. D. Neufeld, A. R. Janzen, R. A. Aziz, "Empirical Equations to Calculate 16 of the
  Transport Collision Integrals Ω(l,s)* for the Lennard-Jones (12-6) Potential", J. Chem. Phys. 57 (1972) 1100-1102,
  doi:10.1063/1.1678363.
- Chapman-Enskog dilute-gas viscosity with Lennard-Jones parameters, η* = 26.692 √(M T) / (σ² Ω) μPa·s with M in
  g/mol, T in K, σ in Å (e.g. B. E. Poling, J. M. Prausnitz, J. P. O'Connell, The Properties of Gases and Liquids,
  5th ed., Eq. 9-3.9). This is the dilute-gas term of the ECS model of Huber et al. (2003).
- Chung method: T.-H. Chung, M. Ajlan, L. L. Lee, K. E. Starling, "Generalized Multiparameter Correlation for
  Nonpolar and Polar Fluid Transport Properties", Ind. Eng. Chem. Res. 27 (1988) 671-679, doi:10.1021/ie00076a024.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Self

import numpy as np

from propbench.core import Quantity
from propbench.models.base import CheckValue, Parameter, Validity, as_states, free_bounds, updated


def omega22_neufeld(t_star: np.typing.ArrayLike, *, sine_term: bool = False) -> np.ndarray:
    """Reduced collision integral Ω(2,2)* of the Lennard-Jones 12-6 potential (Neufeld et al. 1972).

    The full Neufeld equation has a small sine correction (used by Chung et al. 1988); the three-term form without it is
    the one used for dilute-gas viscosity in ECS models (Huber et al. 2003; CoolProp). Valid for 0.3 ≤ T* ≤ 100.
    """
    t = np.asarray(t_star, dtype=float)
    omega = 1.16145 * t**-0.14874 + 0.52487 * np.exp(-0.77320 * t) + 2.16178 * np.exp(-2.43787 * t)
    if sine_term:
        omega = omega - 6.435e-4 * t**0.14874 * np.sin(18.0323 * t**-0.76830 - 7.27371)
    return omega


def chapman_enskog_viscosity(
    temperature: np.typing.ArrayLike, molar_mass: float, sigma: float, epsilon_k: float
) -> np.ndarray:
    """Dilute-gas viscosity in Pa·s. ``molar_mass`` in kg/mol, ``sigma`` in m, ``epsilon_k`` (ε/k) in K."""
    t = np.asarray(temperature, dtype=float)
    sigma_nm = sigma * 1e9
    return 26.692e-9 * np.sqrt(molar_mass * 1000.0 * t) / (sigma_nm**2 * omega22_neufeld(t / epsilon_k))


@dataclass(frozen=True)
class LennardJonesDiluteGas:
    """Chapman-Enskog dilute-gas viscosity η*(T) with Lennard-Jones σ and ε/k; ``k`` scales the result (default 1)."""

    fluid: str
    molar_mass: float  # kg/mol
    parameters: Mapping[str, Parameter] = field(default_factory=dict)
    name: str = "Chapman-Enskog dilute gas"
    quantity: Quantity = Quantity.VISCOSITY

    @classmethod
    def create(cls, fluid: str, molar_mass: float, sigma: float, epsilon_k: float, k: float = 1.0) -> Self:
        return cls(
            fluid,
            molar_mass,
            {
                "sigma": Parameter("sigma", sigma, 1e-10, 2e-9, fixed=True, unit="m", description="LJ diameter"),
                "epsilon_k": Parameter("epsilon_k", epsilon_k, 1.0, 5000.0, fixed=True, unit="K", description="ε/k"),
                "k": Parameter("k", k, 0.5, 2.0, fixed=True, description="dilute-gas scaling factor"),
            },
        )

    def predict(self, temperature: np.typing.ArrayLike, molar_density: np.typing.ArrayLike) -> np.ndarray:
        t, _ = as_states(temperature, molar_density)
        p = self.parameters
        return p["k"].value * chapman_enskog_viscosity(t, self.molar_mass, p["sigma"].value, p["epsilon_k"].value)

    def params(self) -> Mapping[str, Parameter]:
        return dict(self.parameters)

    def with_params(self, values: Mapping[str, float]) -> Self:
        return replace(self, parameters=updated(self.parameters, values))

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return free_bounds(self)

    def check_values(self) -> Sequence[CheckValue]:
        return ()

    def validity(self) -> Validity:
        eps = self.parameters["epsilon_k"].value
        return Validity(0.3 * eps, 100.0 * eps, 0.0, "dilute gas only; Neufeld fit range 0.3 ≤ T* ≤ 100")

    def reference(self) -> str:
        return "Chapman-Enskog with the Neufeld et al. (1972) collision integral"


# Chung et al. (1988), Table II: A_i = a0 + a1 ω + a2 μr⁴ + a3 κ  (i = 1..10)
_CHUNG_A = np.array(
    [
        [6.32402, 50.41190, -51.68010, 1189.02000],
        [0.12102e-2, -0.11536e-2, -0.62571e-2, 0.37283e-1],
        [5.28346, 254.20900, -168.48100, 3898.27000],
        [6.62263, 38.09570, -8.46414, 31.41780],
        [19.74540, 7.63034, -14.35440, 31.52670],
        [-1.89992, -12.53670, 4.98529, -18.15070],
        [24.27450, 3.44945, -11.29130, 69.34660],
        [0.79716, 1.11764, 0.12348e-1, -4.11661],
        [-0.23816, 0.67695e-1, -0.81630, 4.02528],
        [0.68629e-1, 0.34793, 0.59256, -0.72663],
    ]
)


@dataclass(frozen=True)
class ChungViscosity:
    """Chung et al. (1988) viscosity of dense and dilute fluids from Tc, Vc, ω, dipole moment and association κ."""

    fluid: str
    molar_mass: float  # kg/mol
    parameters: Mapping[str, Parameter] = field(default_factory=dict)
    name: str = "Chung et al. (1988)"
    quantity: Quantity = Quantity.VISCOSITY

    @classmethod
    def create(
        cls,
        fluid: str,
        *,
        molar_mass: float,
        t_critical: float,
        rhomolar_critical: float,
        acentric: float,
        dipole_moment: float = 0.0,
        kappa: float = 0.0,
    ) -> Self:
        """Critical temperature in K, critical molar density in mol/m³, dipole moment in debye."""
        return cls(
            fluid,
            molar_mass,
            {
                "t_critical": Parameter("t_critical", t_critical, 1.0, 2000.0, fixed=True, unit="K"),
                "rhomolar_critical": Parameter(
                    "rhomolar_critical", rhomolar_critical, 1.0, 1e6, fixed=True, unit="mol/m^3"
                ),
                "acentric": Parameter("acentric", acentric, -0.5, 2.0, fixed=True),
                "dipole_moment": Parameter("dipole_moment", dipole_moment, 0.0, 20.0, fixed=True, unit="D"),
                "kappa": Parameter("kappa", kappa, 0.0, 1.0, fixed=True, description="association factor"),
            },
        )

    def dilute(self, temperature: np.typing.ArrayLike) -> np.ndarray:
        """Low-density viscosity η₀ in Pa·s (Chung et al. 1988, Eq. 1)."""
        t = np.asarray(temperature, dtype=float)
        vc, t_star, f_c, _ = self._reduced(t)
        omega = omega22_neufeld(t_star, sine_term=True)
        return 4.0785e-6 * np.sqrt(self.molar_mass * 1000.0 * t) / (vc ** (2 / 3) * omega) * f_c

    def predict(self, temperature: np.typing.ArrayLike, molar_density: np.typing.ArrayLike) -> np.ndarray:
        t, rho = as_states(temperature, molar_density)
        vc, t_star, _, a = self._reduced(t)
        eta0 = self.dilute(t)
        y = rho / 1e6 * vc / 6.0
        g1 = (1.0 - 0.5 * y) / (1.0 - y) ** 3
        with np.errstate(divide="ignore", invalid="ignore"):
            # -expm1 avoids the cancellation of 1 - exp(-A4 y) at low density; the limit y → 0 is A1 A4
            first = np.where(y > 0, -a[0] * np.expm1(-a[3] * y) / y, a[0] * a[3])
        g2 = (first + a[1] * g1 * np.exp(a[4] * y) + a[2] * g1) / (a[0] * a[3] + a[1] + a[2])
        eta_k = eta0 * (1.0 / g2 + a[5] * y)
        tc = self.parameters["t_critical"].value
        eta_p = (
            3.6344e-6
            * np.sqrt(self.molar_mass * 1000.0 * tc)
            / vc ** (2 / 3)
            * a[6]
            * y**2
            * g2
            * np.exp(a[7] + a[8] / t_star + a[9] / t_star**2)
        )
        return eta_k + eta_p

    def _reduced(self, t: np.ndarray) -> tuple[float, np.ndarray, float, np.ndarray]:
        p = self.parameters
        vc = 1e6 / p["rhomolar_critical"].value  # cm³/mol
        tc, omega, kappa = p["t_critical"].value, p["acentric"].value, p["kappa"].value
        mu_r = 131.3 * p["dipole_moment"].value / np.sqrt(vc * tc)
        a = _CHUNG_A @ np.array([1.0, omega, mu_r**4, kappa])
        f_c = 1.0 - 0.2756 * omega + 0.059035 * mu_r**4 + kappa
        return vc, 1.2593 * t / tc, f_c, a

    def params(self) -> Mapping[str, Parameter]:
        return dict(self.parameters)

    def with_params(self, values: Mapping[str, float]) -> Self:
        return replace(self, parameters=updated(self.parameters, values))

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return free_bounds(self)

    def check_values(self) -> Sequence[CheckValue]:
        return ()

    def validity(self) -> Validity:
        tc = self.parameters["t_critical"].value
        return Validity(0.3 * tc / 1.2593, 100.0 * tc / 1.2593, notes="generalized correlation; typically ±5-10 %")

    def reference(self) -> str:
        return "T.-H. Chung et al., Ind. Eng. Chem. Res. 27 (1988) 671, doi:10.1021/ie00076a024"
