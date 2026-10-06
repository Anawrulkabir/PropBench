"""One consistency study of the datasets of one fluid and property: overlaps, model-free comparisons, trend checks,
offsets against other datasets and against models, z-scores, and warnings in plain words."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from propbench.backends import Backend, CoolPropBackend, assign_phases
from propbench.consist.offsets import Offset, ZScores, relative_offset, z_scores
from propbench.consist.overlap import (
    Comparison,
    Overlap,
    TrendCheck,
    compare_to_trends,
    find_overlaps,
    pressure_trend_checks,
    relative_standard_uncertainty,
)
from propbench.core import Dataset, DatasetError
from propbench.fit import fit_data
from propbench.models import Model
from propbench.validate.physics import predict_each


@dataclass(frozen=True)
class ConsistencyReport:
    overlaps: list[Overlap]
    comparisons: list[Comparison]
    trend_checks: list[TrendCheck]
    offsets: list[Offset]
    z_scores: list[ZScores]
    warnings: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "overlaps": [o.as_dict() for o in self.overlaps],
            "comparisons": [c.as_dict() for c in self.comparisons],
            "trend_checks": [t.as_dict() for t in self.trend_checks],
            "offsets": [o.as_dict() for o in self.offsets],
            "z_scores": [z.as_dict() for z in self.z_scores],
            "warnings": list(self.warnings),
        }


def _pairwise(a: Dataset, b: Dataset, t_tol: float, report: ConsistencyReport) -> None:
    """Both directions of one overlapping pair: b against the trends of a, and a against the trends of b."""
    for ref, other in ((a, b), (b, a)):
        if ref.pressure is None or other.pressure is None:
            continue
        comps = compare_to_trends(other, ref, t_tol)
        report.comparisons.extend(comps)
        report.trend_checks.extend(pressure_trend_checks(ref, other, t_tol))
        if not comps:
            continue
        values = np.array([c.value for c in comps])
        trend = np.array([c.trend_value for c in comps])
        has_u = relative_standard_uncertainty(other) is not None
        sigma = np.array([np.hypot(c.u_point, c.u_trend) for c in comps]) if has_u else None
        n_extra = sum(c.extrapolated for c in comps)
        report.offsets.append(
            relative_offset(
                values,
                trend,
                sigma,
                dataset=other.name,
                reference_name=ref.name,
                u_reference=float(np.mean([c.u_a for c in comps])),
                extrapolated=n_extra,
            )
        )
        bad = [c for c in comps if not c.consistent]
        if bad:
            worst = max(bad, key=lambda c: abs(c.difference))
            report.warnings.append(
                f"{other.name} differs from the pressure trend of {ref.name} beyond the combined uncertainty at "
                f"{len(bad)} of {len(comps)} points (largest {worst.difference:+.2f} % at {worst.temperature:.2f} K, "
                f"combined U {worst.u_combined:.2f} %)"
            )
        if n_extra:
            report.warnings.append(
                f"the offset of {other.name} against {ref.name} uses {n_extra} of {len(comps)} trend values "
                "extrapolated beyond the measured pressure range: it depends on the extrapolation"
            )
    for check in report.trend_checks:
        if check.a in (a.name, b.name) and check.b in (a.name, b.name) and not check.passed:
            message = (
                f"pressure trend at {check.temperature:.2f} K: {check.b} points lie against the trend of {check.a} "
                f"({len(check.violations)} pairs) — model-free, the two sources disagree"
            )
            if message not in report.warnings:
                report.warnings.append(message)


def consistency_report(
    datasets: Sequence[Dataset],
    models: Mapping[str, Model] | None = None,
    backend: Backend | None = None,
    t_tol: float = 1.0,
) -> ConsistencyReport:
    """Consistency of ``datasets`` with each other (model-free) and with each of ``models`` (model-based)."""
    if not datasets:
        raise DatasetError("the consistency study needs at least one dataset")
    if len({(d.fluid, d.quantity) for d in datasets}) != 1:
        raise DatasetError("the consistency study needs datasets of one fluid and one property")
    # pressure trends are drawn within one phase: give every dataset with pressures its EoS phases if it has none
    datasets = [
        assign_phases(d, backend or CoolPropBackend()).dataset if d.phase is None and d.pressure is not None else d
        for d in datasets
    ]
    report = ConsistencyReport(find_overlaps(datasets, t_tol), [], [], [], [], [])
    by_name = {d.name: d for d in datasets}
    for overlap in report.overlaps:
        _pairwise(by_name[overlap.a], by_name[overlap.b], t_tol, report)
    if len(datasets) > 1 and not report.overlaps:
        report.warnings.append("no datasets overlap in temperature: only model-based comparisons are possible")
    for d in datasets:
        if d.expanded_uncertainty is None:
            report.warnings.append(f"{d.name} states no uncertainty: z-scores and weighted offsets are not available")
    for name, model in (models or {}).items():
        for d in datasets:
            data = fit_data([d], backend)
            predicted = predict_each(model, data.temperature, data.molar_density)
            ok = np.isfinite(predicted) & (predicted > 0)
            if not ok.any():
                report.warnings.append(f"{name} cannot be evaluated at the states of {d.name}")
                continue
            u = relative_standard_uncertainty(d)
            offset = relative_offset(
                d.values[ok], predicted[ok], None if u is None else u[ok], dataset=d.name, reference_name=name
            )
            report.offsets.append(offset)
            if u is not None:
                zs = z_scores(d.values[ok], predicted[ok], u[ok], d.point_ids[ok], dataset=d.name, reference_name=name)
                report.z_scores.append(zs)
                if zs.n_outside:
                    report.warnings.append(
                        f"{d.name}: {zs.n_outside} of {len(zs.z)} points deviate from {name} by more than their "
                        "expanded uncertainty (|z| > 2)"
                    )
            if not ok.all():
                report.warnings.append(f"{name} cannot be evaluated at {int((~ok).sum())} states of {d.name}")
    return report
