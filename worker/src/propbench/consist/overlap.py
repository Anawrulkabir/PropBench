"""Model-free consistency between datasets (README §2: overlap finder, pressure trend at equal T).

Datasets overlap where their temperature ranges intersect. On a shared isotherm, the local pressure trend of one
dataset (ln y linear in p, fitted with its stated uncertainties) is extended to the points of the other dataset; the
difference is compared with the combined expanded uncertainty of both sources, without any property model.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

import numpy as np

from propbench.core import Dataset, DatasetError, Phase
from propbench.fit import bayesian_linear_fit


@dataclass(frozen=True)
class Overlap:
    """Two datasets whose temperature ranges intersect (widened by the isotherm tolerance)."""

    a: str
    b: str
    t_range: tuple[float, float]
    a_points: np.ndarray = field(repr=False)  # point ids of a inside the overlap
    b_points: np.ndarray = field(repr=False)

    def as_dict(self) -> dict[str, object]:
        return {
            "a": self.a,
            "b": self.b,
            "t_range": list(self.t_range),
            "a_points": self.a_points.tolist(),
            "b_points": self.b_points.tolist(),
        }


_PHASE_CLASS = {
    Phase.LIQUID: "liquid",
    Phase.SUPERCRITICAL_LIQUID: "liquid",
    Phase.VAPOR: "vapor",
    Phase.SUPERCRITICAL_GAS: "vapor",
    Phase.SUPERCRITICAL: "supercritical",
}


def phase_classes(dataset: Dataset) -> np.ndarray:
    """Liquid-like, vapour-like or supercritical for each point ("any" when the dataset has no phases). A pressure
    trend is only meaningful within one phase: it must never be drawn across the saturation curve."""
    if dataset.phase is None:
        return np.full(len(dataset), "any", dtype=object)
    return np.array([_PHASE_CLASS.get(ph, ph.value) for ph in dataset.phase], dtype=object)


def _phase_isotherms(dataset: Dataset, tol: float) -> list[np.ndarray]:
    """Isotherms split by phase class."""
    classes = phase_classes(dataset)
    groups = []
    for idx in isotherms(dataset.temperature, tol):
        for cls in dict.fromkeys(classes[idx]):
            groups.append(idx[classes[idx] == cls])
    return groups


def relative_standard_uncertainty(dataset: Dataset) -> np.ndarray | None:
    """Stated expanded uncertainty divided by the coverage factor and by the value (k = 1, relative)."""
    rel = dataset.relative_uncertainty
    return None if rel is None else rel / dataset.coverage_factor


def find_overlaps(datasets: Sequence[Dataset], t_tol: float = 1.0) -> list[Overlap]:
    """Every pair of datasets of one fluid and property whose temperature ranges overlap."""
    if t_tol < 0:
        raise DatasetError("the temperature tolerance must not be negative")
    out = []
    for i, a in enumerate(datasets):
        for b in datasets[i + 1 :]:
            if a.fluid != b.fluid or a.quantity != b.quantity:
                continue
            lo = max(a.temperature.min(), b.temperature.min()) - t_tol
            hi = min(a.temperature.max(), b.temperature.max()) + t_tol
            if lo > hi:
                continue
            in_a = (a.temperature >= lo) & (a.temperature <= hi)
            in_b = (b.temperature >= lo) & (b.temperature <= hi)
            if in_a.any() and in_b.any():
                t = np.concatenate([a.temperature[in_a], b.temperature[in_b]])
                out.append(
                    Overlap(a.name, b.name, (float(t.min()), float(t.max())), a.point_ids[in_a], b.point_ids[in_b])
                )
    return out


def isotherms(temperature: np.ndarray, tol: float = 1.0) -> list[np.ndarray]:
    """Row indices grouped into isotherms: sorted temperatures within ``tol`` of a group's first member."""
    order = np.argsort(temperature, kind="stable")
    groups: list[list[int]] = []
    start = None
    for i in order:
        if start is None or temperature[i] - start > tol:
            groups.append([])
            start = temperature[i]
        groups[-1].append(int(i))
    return [np.array(g) for g in groups]


@dataclass(frozen=True)
class IsothermTrend:
    """ln y = c₀ + c₁·(p - p̄) on one isotherm of one dataset, with the covariance of (c₀, c₁)."""

    dataset: str
    temperature: float
    p_mean: float
    coef: np.ndarray
    covariance: np.ndarray
    p_range: tuple[float, float]
    n: int
    u_stated: float | None  # mean relative standard uncertainty stated for these points
    phase: str = "any"

    def predict(self, pressure: float) -> tuple[float, float]:
        """Value and relative standard uncertainty of the trend at ``pressure``."""
        x = np.array([1.0, pressure - self.p_mean])
        return float(np.exp(x @ self.coef)), float(np.sqrt(max(x @ self.covariance @ x, 0.0)))

    @property
    def slope_significant(self) -> bool:
        sd = np.sqrt(max(self.covariance[1, 1], 0.0))
        return bool(abs(self.coef[1]) > 2.0 * sd) if sd > 0 else bool(self.coef[1] != 0)


def isotherm_trends(dataset: Dataset, tol: float = 1.0) -> list[IsothermTrend]:
    """Trends on every isotherm (within one phase class) of ``dataset`` with at least two pressures."""
    if dataset.pressure is None:
        raise DatasetError(f"{dataset.name}: the pressure trend needs pressures")
    u = relative_standard_uncertainty(dataset)
    classes = phase_classes(dataset)
    trends = []
    for idx in _phase_isotherms(dataset, tol):
        p = dataset.pressure[idx]
        if len(np.unique(p)) < 2:
            continue
        y = np.log(dataset.values[idx])
        p_mean = float(np.mean(p))
        design = np.column_stack([np.ones(len(idx)), p - p_mean])
        if u is not None:
            fit = bayesian_linear_fit(design, y, u[idx])
            cov = fit.covariance
        else:
            # no stated uncertainty: scatter about the line, if there are spare degrees of freedom
            fit = bayesian_linear_fit(design, y, np.ones(len(idx)))
            dof = len(idx) - 2
            resid = y - design @ fit.mean
            cov = fit.covariance * (float(resid @ resid) / dof if dof > 0 else 0.0)
        trends.append(
            IsothermTrend(
                dataset.name,
                float(np.mean(dataset.temperature[idx])),
                p_mean,
                fit.mean,
                cov,
                (float(p.min()), float(p.max())),
                len(idx),
                None if u is None else float(np.mean(u[idx])),
                str(classes[idx[0]]),
            )
        )
    return trends


@dataclass(frozen=True)
class Comparison:
    """A point of dataset ``b`` against the isotherm trend of dataset ``a`` (model-free)."""

    a: str
    b: str
    point_id: int
    temperature: float  # of the point
    delta_t: float  # point temperature - isotherm temperature
    pressure: float
    value: float
    trend_value: float
    difference: float  # %, 100 (y_b - ŷ_a) / ŷ_a
    u_combined: float  # %, expanded (k = 2): stated uncertainties of a and b and the trend uncertainty
    extrapolated: bool  # pressure outside the isotherm's pressure range in a
    u_point: float  # relative standard uncertainty stated for the point of b
    u_trend: float  # relative standard uncertainty of the trend value (statistical)
    u_a: float  # mean relative standard uncertainty stated for the isotherm of a (systematic)
    # Monotonicity bound without extrapolation: outside a's pressure range, a property monotonic in p is bounded by
    # its value at the nearest measured end, so the difference is at least (or at most) ``bound`` %.
    bound: float | None = None
    bound_kind: str | None = None  # "at least" or "at most"

    @property
    def z(self) -> float:
        return self.difference / (self.u_combined / 2.0) if self.u_combined > 0 else float("nan")

    @property
    def consistent(self) -> bool:
        return abs(self.difference) <= self.u_combined

    def as_dict(self) -> dict[str, object]:
        return {
            "a": self.a,
            "b": self.b,
            "point_id": self.point_id,
            "temperature": self.temperature,
            "delta_t": self.delta_t,
            "pressure": self.pressure,
            "value": self.value,
            "trend_value": self.trend_value,
            "difference": self.difference,
            "u_combined": self.u_combined,
            "z": self.z,
            "consistent": self.consistent,
            "extrapolated": self.extrapolated,
            "bound": self.bound,
            "bound_kind": self.bound_kind,
        }


def compare_to_trends(b: Dataset, a: Dataset, t_tol: float = 1.0) -> list[Comparison]:
    """Points of ``b`` within ``t_tol`` of an isotherm of ``a``, compared with that isotherm's pressure trend."""
    if b.pressure is None:
        raise DatasetError(f"{b.name}: the comparison needs pressures")
    trends = isotherm_trends(a, t_tol)
    u_b = relative_standard_uncertainty(b)
    classes = phase_classes(b)
    out = []
    for i in range(len(b)):
        same_phase = [tr for tr in trends if "any" in (tr.phase, classes[i]) or tr.phase == classes[i]]
        if not same_phase:
            continue
        nearest = min(same_phase, key=lambda tr: abs(tr.temperature - b.temperature[i]))
        delta = float(b.temperature[i] - nearest.temperature)
        if abs(delta) > t_tol:
            continue
        p = float(b.pressure[i])
        predicted, u_trend = nearest.predict(p)
        u_a = nearest.u_stated or 0.0
        u_point = 0.0 if u_b is None else float(u_b[i])
        bound, kind = _monotonic_bound(nearest, p, float(b.values[i]))
        out.append(
            Comparison(
                a.name,
                b.name,
                int(b.point_ids[i]),
                float(b.temperature[i]),
                delta,
                p,
                float(b.values[i]),
                predicted,
                100.0 * (float(b.values[i]) - predicted) / predicted,
                200.0 * float(np.sqrt(u_a**2 + u_point**2 + u_trend**2)),
                not (nearest.p_range[0] <= p <= nearest.p_range[1]),
                u_point,
                u_trend,
                u_a,
                bound,
                kind,
            )
        )
    return out


def _monotonic_bound(trend: IsothermTrend, pressure: float, value: float) -> tuple[float | None, str | None]:
    """Difference of ``value`` from the trend at the nearest end of the measured pressure range, and whether it is a
    lower or an upper bound of the true difference (needs a significant slope, i.e. a known direction)."""
    lo, hi = trend.p_range
    if lo <= pressure <= hi or not trend.slope_significant:
        return None, None
    end = lo if pressure < lo else hi
    end_value, _ = trend.predict(end)
    rising = trend.coef[1] > 0
    # below the range of a rising property the true value is lower than at the end: difference at least ...
    at_least = (pressure < lo) == rising
    return 100.0 * (value - end_value) / end_value, "at least" if at_least else "at most"


@dataclass(frozen=True)
class TrendCheck:
    """Monotonicity in pressure at equal temperature across two datasets: does ``b`` follow the trend of ``a``?"""

    a: str
    b: str
    temperature: float
    slope_sign: int
    violations: list[tuple[int, int]]  # (point id in a, point id in b) ordered against the trend

    @property
    def passed(self) -> bool:
        return not self.violations

    def as_dict(self) -> dict[str, object]:
        return {
            "a": self.a,
            "b": self.b,
            "temperature": self.temperature,
            "slope_sign": self.slope_sign,
            "violations": [list(v) for v in self.violations],
            "passed": self.passed,
        }


def pressure_trend_checks(a: Dataset, b: Dataset, t_tol: float = 1.0) -> list[TrendCheck]:
    """On each isotherm of ``a`` with a significant pressure slope, every point of ``b`` at that temperature must lie
    on the side of each point of ``a`` that the slope implies (higher pressure → higher value if the slope is
    positive). A violation means the two sources cannot both be right, whatever the model."""
    if a.pressure is None or b.pressure is None:
        raise DatasetError("the pressure trend check needs pressures")
    checks = []
    for trend, idx in zip(isotherm_trends(a, t_tol), _trend_rows(a, t_tol), strict=True):
        if not trend.slope_significant:
            continue
        sign = 1 if trend.coef[1] > 0 else -1
        b_classes = phase_classes(b)
        same = np.array([trend.phase == "any" or c in ("any", trend.phase) for c in b_classes], dtype=bool)
        near = np.flatnonzero((np.abs(b.temperature - trend.temperature) <= t_tol) & same)
        if len(near) == 0:
            continue
        violations = []
        for j in near:
            for i in idx:
                dp = b.pressure[j] - a.pressure[i]
                dy = b.values[j] - a.values[i]
                if dp != 0 and np.sign(dy) != 0 and np.sign(dy) != sign * np.sign(dp):
                    violations.append((int(a.point_ids[i]), int(b.point_ids[j])))
        checks.append(TrendCheck(a.name, b.name, trend.temperature, sign, violations))
    return checks


def _trend_rows(dataset: Dataset, tol: float) -> list[np.ndarray]:
    """Row indices of the isotherms that ``isotherm_trends`` keeps (same order)."""
    pressure = dataset.pressure
    if pressure is None:
        return []
    return [idx for idx in _phase_isotherms(dataset, tol) if len(np.unique(pressure[idx])) >= 2]
