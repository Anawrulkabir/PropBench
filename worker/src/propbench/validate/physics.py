"""Physics checks of a fitted model (README §2): dilute-gas limit, monotonicity, sane extrapolation.

States come from the ``Backend`` equation of state at (T, p), so every checked state is a single-phase state.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from propbench.backends import Backend, CoolPropBackend
from propbench.models import Model, ModelError


@dataclass(frozen=True)
class PhysicsCheck:
    """``not_evaluated`` counts states where the model itself cannot be computed (e.g. the ECS conformal solve has no
    solution in the very dilute gas, as in CoolProp); they are reported but do not fail the check."""

    name: str
    passed: bool
    n_states: int
    message: str
    violations: list[tuple[float, float]] = field(default_factory=list)  # (T / K, molar density / mol m⁻³)
    not_evaluated: int = 0

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "n_states": self.n_states,
            "message": self.message,
            "violations": [list(v) for v in self.violations],
            "not_evaluated": self.not_evaluated,
        }


def predict_each(model: Model, temperature: np.ndarray, molar_density: np.ndarray) -> np.ndarray:
    """``model.predict`` with NaN at the states where the model cannot be evaluated."""
    try:
        return np.asarray(model.predict(temperature, molar_density), dtype=float)
    except ModelError:
        out = np.full(len(temperature), np.nan)
        for i, (t, rho) in enumerate(zip(temperature, molar_density, strict=True)):
            try:
                out[i] = model.predict([t], [rho])[0]
            except ModelError:
                continue
        return out


def _skipped(y: np.ndarray) -> str:
    n = int(np.isnan(y).sum())
    return f"; {n} states not computable by the model" if n else ""


@dataclass(frozen=True)
class StateGrid:
    """Single-phase states on isotherms: rows sorted by temperature, then pressure."""

    temperature: np.ndarray
    pressure: np.ndarray
    molar_density: np.ndarray
    t_critical: float
    rhomolar_critical: float


def state_grid(
    fluid: str,
    temperatures: Sequence[float],
    pressures: Sequence[float],
    backend: Backend | None = None,
) -> StateGrid:
    """Molar densities on a (T, p) grid; states the equation of state cannot compute are dropped."""
    backend = backend or CoolPropBackend()
    tt, pp = np.meshgrid(np.asarray(temperatures, dtype=float), np.asarray(pressures, dtype=float), indexing="ij")
    t, p = tt.ravel(), pp.ravel()
    batch = backend.properties(fluid, "PT_INPUTS", p, t, ["Dmolar"])
    ok = ~batch.failed
    crit = backend.properties(fluid, "PT_INPUTS", [1e5], [300.0], ["T_critical", "rhomolar_critical"])
    return StateGrid(
        t[ok], p[ok], batch["Dmolar"][ok], float(crit["T_critical"][0]), float(crit["rhomolar_critical"][0])
    )


def check_dilute_limit(model: Model, temperatures: Sequence[float], rel_tol: float = 1e-4) -> PhysicsCheck:
    """At zero density the model must be finite, positive and continuous (no density term left over).

    Continuity is checked against ρ = 10⁻³ mol/m³ where the model can be evaluated there; temperatures where it cannot
    (e.g. no ECS conformal state in the very dilute gas, as in CoolProp) are reported as not evaluated.
    """
    t = np.asarray(temperatures, dtype=float)
    zero = predict_each(model, t, np.zeros_like(t))
    small = predict_each(model, t, np.full_like(t, 1e-3))
    bad = ~(np.isfinite(zero) & (zero > 0))
    with np.errstate(invalid="ignore", divide="ignore"):
        bad |= np.isfinite(small) & ~(np.abs(small / zero - 1) < rel_tol)
    skipped = int((~np.isfinite(small) & ~bad).sum())
    violations = [(float(ti), 0.0) for ti in t[bad]]
    message = "finite, positive and continuous at zero density" if not bad.any() else f"{bad.sum()} temperatures fail"
    if skipped:
        message += f"; continuity not evaluated at {skipped} temperatures"
    return PhysicsCheck("dilute-gas limit", not bad.any(), len(t), message, violations, skipped)


def check_monotonic_density(model: Model, grid: StateGrid) -> PhysicsCheck:
    """Along every isotherm, the property must increase with density in the dense fluid (ρ above ρ_c)."""
    return _monotonic(model, grid, "increases with density (dense fluid)", along="isotherm")


def check_monotonic_temperature(model: Model, grid: StateGrid) -> PhysicsCheck:
    """Along every isobar, the liquid property must decrease with temperature (T below T_c, ρ above ρ_c)."""
    return _monotonic(model, grid, "decreases with temperature (liquid)", along="isobar")


def _monotonic(model: Model, grid: StateGrid, name: str, along: str) -> PhysicsCheck:
    dense = grid.molar_density > grid.rhomolar_critical
    if along == "isobar":
        dense &= grid.temperature < grid.t_critical
    t, p, rho = grid.temperature[dense], grid.pressure[dense], grid.molar_density[dense]
    y = predict_each(model, t, rho)
    violations: list[tuple[float, float]] = []
    keys, coords = (t, rho) if along == "isotherm" else (p, t)
    sign = 1.0 if along == "isotherm" else -1.0
    checked = 0
    for key in np.unique(keys):
        idx = np.flatnonzero((keys == key) & np.isfinite(y))
        if len(idx) < 2:
            continue
        idx = idx[np.argsort(coords[idx])]
        step = sign * np.diff(y[idx])
        checked += len(step)
        for i in np.flatnonzero(step <= 0):
            violations.append((float(t[idx[i + 1]]), float(rho[idx[i + 1]])))
    message = f"{checked} steps checked" + (f", {len(violations)} violations" if violations else "") + _skipped(y)
    return PhysicsCheck(name, not violations, checked, message, violations, int(np.isnan(y).sum()))


def check_extrapolation(model: Model, grid: StateGrid, max_ratio: float = 100.0) -> PhysicsCheck:
    """Outside the data, predictions must stay finite, positive and within ``max_ratio`` of their neighbours in the same
    phase on the same isotherm."""
    y = predict_each(model, grid.temperature, grid.molar_density)
    computed = ~np.isnan(y)
    bad = computed & ~(np.isfinite(y) & (y > 0))
    positive = np.where(bad | ~computed, np.nan, y)
    with np.errstate(invalid="ignore"):
        jumps = np.abs(np.diff(np.log(positive)))
    # neighbours on one isotherm and in one phase (crossing the saturation curve legitimately jumps by a factor > 100)
    dense = (grid.molar_density > grid.rhomolar_critical) | (grid.temperature >= grid.t_critical)
    same_t = (np.diff(grid.temperature) == 0) & (dense[1:] == dense[:-1])
    jump = np.zeros_like(bad)
    jump[1:] |= same_t & np.nan_to_num(jumps > np.log(max_ratio))
    bad |= jump
    violations = [(float(t), float(r)) for t, r in zip(grid.temperature[bad], grid.molar_density[bad], strict=True)]
    message = f"{len(y)} states" + (f", {len(violations)} non-physical" if violations else ", all finite and positive")
    return PhysicsCheck(
        "extrapolation", not violations, len(y), message + _skipped(y), violations, int((~computed).sum())
    )


def physics_checks(
    model: Model,
    data_temperature: np.ndarray,
    data_pressure: np.ndarray | None = None,
    backend: Backend | None = None,
    extend: float = 0.2,
    n: int = 9,
) -> list[PhysicsCheck]:
    """The standard checks on a grid that extends the data range by ``extend`` (fraction) on each side."""
    t_lo, t_hi = float(np.min(data_temperature)), float(np.max(data_temperature))
    temperatures = np.linspace(t_lo * (1 - extend), t_hi * (1 + extend), n)
    p_hi = float(np.max(data_pressure)) if data_pressure is not None and len(data_pressure) else 1e7
    pressures = np.geomspace(1e3, p_hi * (1 + extend) * 2, n)
    grid = state_grid(model.fluid, temperatures, pressures, backend)
    return [
        check_dilute_limit(model, temperatures),
        check_monotonic_density(model, grid),
        check_monotonic_temperature(model, grid),
        check_extrapolation(model, grid),
    ]
