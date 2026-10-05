"""Extended corresponding states (ECS) viscosity.

M. L. Huber, A. Laesecke, R. A. Perkins, "Model for the Viscosity and Thermal Conductivity of Refrigerants, Including
a New Correlation for the Viscosity of R134a", Ind. Eng. Chem. Res. 42 (2003) 3163-3178, doi:10.1021/ie0300880.

    η(T, ρ) = k · η*(T) + Δη_ref(T₀, ρ₀ ψ(ρ)) · F_η,   F_η = √f · h^(-2/3) · √(M / M₀),   f = T / T₀,  h = ρ₀ / ρ

η* is the Chapman-Enskog dilute-gas viscosity of the fluid (σ, ε/k), Δη_ref the background (non-dilute) viscosity of
the reference fluid, and ψ(ρ) = Σ aᵢ (ρ/ρ_red)^tᵢ the viscosity shape factor (CF₃I: ψ = β₀ + β₁ ρ_r). The conformal
state (T₀, ρ₀) of the reference fluid has the same residual Helmholtz energy αʳ and compressibility factor Z as the
fluid at (T, ρ) ("exact" shape factors); it is solved by Newton iteration with analytic derivatives from the
equations of state. ``k`` (default 1, fixed) scales the dilute-gas term.

The formulation and the conformal-state solver follow CoolProp's implementation of the same model, which the tests use
as the independent reference (fluids whose CoolProp viscosity is an ECS model, e.g. R236fa with R134a reference).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from functools import cached_property
from typing import Self

import CoolProp.CoolProp as CP  # noqa: N817 - the name CoolProp itself documents
import numpy as np

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
from propbench.models.dilute import chapman_enskog_viscosity

CONFORMAL_TOLERANCE = 1e-9  # Euclidean norm of the (αʳ, Z) residuals
_MAX_ITERATIONS = 50


@dataclass(frozen=True)
class ConformalState:
    t0: float  # K
    rhomolar0: float  # mol/m³
    residual: float
    iterations: int


def conformal_state(target: CP.AbstractState, reference: CP.AbstractState) -> ConformalState:
    """Solve (T₀, ρ₀) of ``reference`` with the same αʳ and Z as ``target`` (already updated to its state)."""
    alphar, z = target.alphar(), target.compressibility_factor()
    t0 = target.T() * reference.T_critical() / target.T_critical()
    rho0 = target.rhomolar() * reference.rhomolar_critical() / target.rhomolar_critical()
    reference.update(CP.DmolarT_INPUTS, rho0, t0)
    residual = float(np.hypot(reference.alphar() - alphar, reference.compressibility_factor() - z))
    for iteration in range(1, _MAX_ITERATIONS + 1):
        if residual <= CONFORMAL_TOLERANCE:
            return ConformalState(t0, rho0, residual, iteration - 1)
        dtau_dt = -reference.T_critical() / t0**2
        ddelta_drho = 1.0 / reference.rhomolar_critical()
        delta = reference.delta()
        r = np.array([reference.alphar() - alphar, reference.compressibility_factor() - z])
        jacobian = np.array(
            [
                [reference.dalphar_dTau() * dtau_dt, reference.dalphar_dDelta() * ddelta_drho],
                [
                    delta * reference.d2alphar_dDelta_dTau() * dtau_dt,
                    (delta * reference.d2alphar_dDelta2() + reference.dalphar_dDelta()) * ddelta_drho,
                ],
            ]
        )
        try:
            step = np.linalg.solve(jacobian, -r)
        except np.linalg.LinAlgError as exc:
            raise ModelError(f"conformal state: singular Jacobian at T0={t0}, rho0={rho0}") from exc
        # Newton step, halved until the residual decreases (as in CoolProp's conformal_state_solver)
        for fraction in 0.5 ** np.arange(11):
            t_new, rho_new = t0 + fraction * step[0], rho0 + fraction * step[1]
            if t_new <= 0 or rho_new <= 0:
                continue
            try:
                reference.update(CP.DmolarT_INPUTS, rho_new, t_new)
            except ValueError:
                continue
            new_residual = float(np.hypot(reference.alphar() - alphar, reference.compressibility_factor() - z))
            if new_residual <= residual:
                t0, rho0, residual = t_new, rho_new, new_residual
                break
        else:
            raise ModelError(f"conformal state did not converge (residual {residual:.3g})")
    if residual > CONFORMAL_TOLERANCE:
        raise ModelError(f"conformal state: no convergence in {_MAX_ITERATIONS} iterations (residual {residual:.3g})")
    return ConformalState(t0, rho0, residual, _MAX_ITERATIONS)


@dataclass(frozen=True)
class ECSViscosity:
    """ECS viscosity model of ``fluid`` relative to ``reference_fluid`` (Huber et al. 2003).

    Parameters: ``psi_0 … psi_n`` (coefficients aᵢ of ψ, exponents ``psi_exponents``), ``sigma`` and ``epsilon_k`` of
    the dilute-gas term, and the dilute-gas factor ``k``. By default the ψ coefficients are free and the others fixed.
    """

    fluid: str
    reference_fluid: str
    psi_exponents: tuple[float, ...]
    psi_rhomolar_reducing: float  # mol/m³
    parameters: Mapping[str, Parameter] = field(default_factory=dict)
    source: str = "Huber, Laesecke, Perkins, Ind. Eng. Chem. Res. 42 (2003) 3163, doi:10.1021/ie0300880"
    name: str = "ECS viscosity"
    quantity: Quantity = Quantity.VISCOSITY

    @classmethod
    def create(
        cls,
        fluid: str,
        reference_fluid: str,
        *,
        sigma: float,
        epsilon_k: float,
        psi: Sequence[float] = (1.0, 0.0),
        psi_exponents: Sequence[float] | None = None,
        psi_rhomolar_reducing: float | None = None,
        k: float = 1.0,
        fit_k: bool = False,
    ) -> Self:
        """ψ defaults to a linear polynomial in ρ/ρ_red; ρ_red defaults to the fluid's critical molar density."""
        fluid, reference_fluid = identify_fluid(fluid), identify_fluid(reference_fluid)
        exponents = tuple(float(e) for e in (psi_exponents if psi_exponents is not None else range(len(psi))))
        if len(exponents) != len(psi):
            raise ModelError("psi and psi_exponents must have the same length")
        rho_red = psi_rhomolar_reducing or CP.PropsSI("rhomolar_critical", fluid)
        params: dict[str, Parameter] = {
            f"psi_{i}": Parameter(f"psi_{i}", float(a), -10.0, 10.0, description=f"ψ coefficient of (ρ/ρ_red)^{e:g}")
            for i, (a, e) in enumerate(zip(psi, exponents, strict=True))
        }
        params["sigma"] = Parameter("sigma", sigma, 1e-10, 2e-9, fixed=True, unit="m", description="LJ diameter")
        params["epsilon_k"] = Parameter("epsilon_k", epsilon_k, 1.0, 5000.0, fixed=True, unit="K", description="ε/k")
        params["k"] = Parameter("k", k, 0.5, 2.0, fixed=not fit_k, description="dilute-gas factor")
        return cls(fluid, reference_fluid, exponents, float(rho_red), params)

    @classmethod
    def from_coolprop(cls, fluid: str) -> Self:
        """The ECS viscosity model stored in CoolProp's fluid library (e.g. R236fa, R116: Huber et al. 2003)."""
        name = identify_fluid(fluid)
        data = json.loads(CP.get_fluid_param_string(name, "JSON"))[0]["TRANSPORT"]["viscosity"]
        if not isinstance(data, dict) or data.get("type") != "ECS":
            raise ModelError(f"CoolProp's viscosity model of {name} is not an ECS model")
        model = cls.create(
            name,
            data["reference_fluid"],
            sigma=data["sigma_eta"],
            epsilon_k=data["epsilon_over_k"],
            psi=data["psi"]["a"],
            psi_exponents=data["psi"]["t"],
            psi_rhomolar_reducing=data["psi"]["rhomolar_reducing"],
        )
        return replace(model, source=f"CoolProp fluid library: {data.get('BibTeX', 'unknown')}")

    @cached_property
    def _molar_masses(self) -> tuple[float, float]:
        return CP.PropsSI("molar_mass", self.fluid), CP.PropsSI("molar_mass", self.reference_fluid)

    def psi(self, molar_density: np.typing.ArrayLike) -> np.ndarray:
        rho_r = np.asarray(molar_density, dtype=float) / self.psi_rhomolar_reducing
        return sum(
            self.parameters[f"psi_{i}"].value * rho_r**e for i, e in enumerate(self.psi_exponents)
        ) * np.ones_like(rho_r)

    def dilute(self, temperature: np.typing.ArrayLike) -> np.ndarray:
        p = self.parameters
        m, _ = self._molar_masses
        return p["k"].value * chapman_enskog_viscosity(temperature, m, p["sigma"].value, p["epsilon_k"].value)

    def predict(self, temperature: np.typing.ArrayLike, molar_density: np.typing.ArrayLike) -> np.ndarray:
        t, rho = as_states(temperature, molar_density)
        target = CP.AbstractState("HEOS", self.fluid)
        reference = CP.AbstractState("HEOS", self.reference_fluid)
        m, m0 = self._molar_masses
        psi = self.psi(rho)
        eta = self.dilute(t)
        for i, (ti, rhoi) in enumerate(zip(t, rho, strict=True)):
            if rhoi == 0.0:
                continue  # dilute-gas limit: no density-dependent contribution
            try:
                target.update(CP.DmolarT_INPUTS, rhoi, ti)
                state = conformal_state(target, reference)
                reference.update(CP.DmolarT_INPUTS, state.rhomolar0 * psi[i], state.t0)
                contributions = reference.viscosity_contributions()
            except ValueError as exc:
                raise ModelError(f"ECS failed at T={ti} K, rho={rhoi} mol/m3: {exc}") from exc
            background = contributions["initial_density"] + contributions["residual"]
            f, h = ti / state.t0, state.rhomolar0 / rhoi
            eta[i] += background * np.sqrt(f) * h ** (-2.0 / 3.0) * np.sqrt(m / m0)
        return eta

    def prepare(self, temperature: np.typing.ArrayLike, molar_density: np.typing.ArrayLike) -> PreparedECS:
        """Solve the conformal states once; the result evaluates the model for any parameter values quickly.

        The conformal state (T₀, ρ₀) depends only on the equations of state, not on ψ, σ, ε/k or k, so a fit needs it
        once per data point. Each evaluation then costs one reference-fluid viscosity call per point.
        """
        t, rho = as_states(temperature, molar_density)
        target = CP.AbstractState("HEOS", self.fluid)
        reference = CP.AbstractState("HEOS", self.reference_fluid)
        m, m0 = self._molar_masses
        t0 = np.zeros_like(t)
        rho0 = np.zeros_like(t)
        for i, (ti, rhoi) in enumerate(zip(t, rho, strict=True)):
            if rhoi == 0.0:
                continue
            try:
                target.update(CP.DmolarT_INPUTS, rhoi, ti)
                state = conformal_state(target, reference)
            except ValueError as exc:
                raise ModelError(f"ECS failed at T={ti} K, rho={rhoi} mol/m3: {exc}") from exc
            t0[i], rho0[i] = state.t0, state.rhomolar0
        with np.errstate(divide="ignore", invalid="ignore"):
            factor = np.where(rho > 0, np.sqrt(t / t0) * (rho0 / rho) ** (-2.0 / 3.0) * np.sqrt(m / m0), 0.0)
        return PreparedECS(self, t, rho, t0, rho0, factor, reference)

    def params(self) -> Mapping[str, Parameter]:
        return dict(self.parameters)

    def with_params(self, values: Mapping[str, float]) -> Self:
        return replace(self, parameters=updated(self.parameters, values))

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return free_bounds(self)

    def check_values(self) -> Sequence[CheckValue]:
        return ()

    def validity(self) -> Validity:
        t_triple = CP.PropsSI("Ttriple", self.fluid)
        t_max = CP.PropsSI("Tmax", self.fluid)
        return Validity(t_triple, t_max, notes=f"within the EoS range of {self.fluid} and {self.reference_fluid}")

    def reference(self) -> str:
        return self.source


@dataclass
class PreparedECS:
    """An ECS model with its conformal states solved for fixed states; ``evaluate`` takes new parameter values."""

    model: ECSViscosity
    temperature: np.ndarray
    molar_density: np.ndarray
    t0: np.ndarray
    rhomolar0: np.ndarray
    factor: np.ndarray  # F_eta per point (0 where rho = 0)
    _reference: CP.AbstractState

    def evaluate(self, values: Mapping[str, float] | None = None) -> np.ndarray:
        model = self.model.with_params(values) if values else self.model
        eta = model.dilute(self.temperature)
        psi = model.psi(self.molar_density)
        reference = self._reference
        for i in np.flatnonzero(self.molar_density > 0):
            try:
                reference.update(CP.DmolarT_INPUTS, self.rhomolar0[i] * psi[i], self.t0[i])
                c = reference.viscosity_contributions()
            except ValueError as exc:
                raise ModelError(f"reference viscosity failed at T0={self.t0[i]}: {exc}") from exc
            eta[i] += (c["initial_density"] + c["residual"]) * self.factor[i]
        return eta
