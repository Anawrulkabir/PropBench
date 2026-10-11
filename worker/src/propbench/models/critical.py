"""Critical enhancement of the thermal conductivity, simplified Olchowy-Sengers crossover model.

G.A. Olchowy, J.V. Sengers, Int. J. Thermophys. 10 (1989) 417; simplified form as used in the NIST correlations:
R.A. Perkins, J.V. Sengers, I.M. Abdulagatov, M.L. Huber, Int. J. Thermophys. 34 (2013) 191, Eqs. (6)-(10):

    λ_c = ρ c_p R_D k_B T / (6π η ξ) · (Ω - Ω₀)
    Ω   = (2/π) [ (c_p - c_v)/c_p · arctan(q_D ξ) + c_v/c_p · q_D ξ ]
    Ω₀  = (2/π) [ 1 - exp( -1 / ((q_D ξ)⁻¹ + (q_D ξ ρ_c/ρ)²/3) ) ]
    ξ   = ξ₀ (Δχ̃ / Γ)^(ν/γ),  Δχ̃ = p_c ρ/ρ_c² [ (∂ρ/∂p)_T(T, ρ) - (T_ref/T) (∂ρ/∂p)_T(T_ref, ρ) ]

λ_c = 0 where Δχ̃ ≤ 0. Molar densities, Pa, Pa·s, J/(mol·K); the result is in W/(m·K).

As in REFPROP and CoolProp, T_c and ρ_c in these equations (and T_ref = 1.5 T_c) are the reducing parameters of the
equation of state; p_c is its critical pressure. With the true critical point instead, λ_c differs by up to ~1 %.
"""

from __future__ import annotations

from dataclasses import dataclass

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np

K_BOLTZMANN = 1.380649e-23  # J/K (exact, SI 2019)


@dataclass(frozen=True)
class CriticalEnhancement:
    """Parameters of the simplified Olchowy-Sengers model; ``t_ref_factor`` × T_c gives T_ref."""

    q_d: float  # 1/m (the reports give q_D⁻¹ in m)
    xi0: float = 1.94e-10  # m
    gamma0: float = 0.0496  # Γ
    r0: float = 1.03  # R_D
    nu: float = 0.63
    gamma: float = 1.239
    t_ref_factor: float = 1.5

    def value(self, state: CP.AbstractState, viscosity: float) -> float:
        """λ_c at the state ``state`` (a pure fluid) is updated to, for a total viscosity ``viscosity`` in Pa·s."""
        t = state.T()
        rho = state.rhomolar()
        tc, rhoc, pc = state.T_reducing(), state.rhomolar_reducing(), state.p_critical()
        t_ref = self.t_ref_factor * tc
        drho_dp = state.first_partial_deriv(CP.iDmolar, CP.iP, CP.iT)
        cp, cv = state.cpmolar(), state.cvmolar()
        ref = CP.AbstractState(state.backend_name(), state.fluid_names()[0])
        try:
            ref.update(CP.DmolarT_INPUTS, rho, t_ref)
            drho_dp_ref = ref.first_partial_deriv(CP.iDmolar, CP.iP, CP.iT)
        except ValueError:
            return 0.0
        delta_chi = pc * rho / rhoc**2 * (drho_dp - t_ref / t * drho_dp_ref)
        if not delta_chi > 0:
            return 0.0
        xi = self.xi0 * (delta_chi / self.gamma0) ** (self.nu / self.gamma)
        qx = self.q_d * xi
        omega = 2.0 / np.pi * ((cp - cv) / cp * np.arctan(qx) + cv / cp * qx)
        omega0 = 2.0 / np.pi * (1.0 - np.exp(-1.0 / (1.0 / qx + (qx * rhoc / rho) ** 2 / 3.0)))
        return float(rho * cp * self.r0 * K_BOLTZMANN * t / (6.0 * np.pi * viscosity * xi) * (omega - omega0))
