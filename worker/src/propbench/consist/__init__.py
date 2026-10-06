"""Data consistency (README §2): overlap finder, model-free checks at equal temperature, dataset offsets with
uncertainty, z-scores against stated uncertainties. Deviations follow 100·(exp - reference)/reference."""

from propbench.consist.compare import ComparisonRow, compare_models
from propbench.consist.offsets import Offset, ZScores, relative_offset, z_scores
from propbench.consist.overlap import (
    Comparison,
    IsothermTrend,
    Overlap,
    TrendCheck,
    compare_to_trends,
    find_overlaps,
    isotherm_trends,
    isotherms,
    pressure_trend_checks,
    relative_standard_uncertainty,
)
from propbench.consist.report import ConsistencyReport, consistency_report

__all__ = [
    "Comparison",
    "ComparisonRow",
    "ConsistencyReport",
    "IsothermTrend",
    "Offset",
    "Overlap",
    "TrendCheck",
    "ZScores",
    "compare_models",
    "compare_to_trends",
    "consistency_report",
    "find_overlaps",
    "isotherm_trends",
    "isotherms",
    "pressure_trend_checks",
    "relative_offset",
    "relative_standard_uncertainty",
    "z_scores",
]
