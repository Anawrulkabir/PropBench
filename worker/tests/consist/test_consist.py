"""Consistency analysis on synthetic data with known offsets (exact answers) and on noisy data (coverage)."""

import numpy as np
import pytest

from propbench.consist import (
    compare_to_trends,
    consistency_report,
    find_overlaps,
    isotherm_trends,
    isotherms,
    pressure_trend_checks,
    relative_offset,
    z_scores,
)
from propbench.core import Dataset, DatasetError, Quantity
from propbench.models import ECSViscosity


def trend_value(t, p):
    """A smooth liquid-like property: ln y linear in p on each isotherm, decreasing with T."""
    return 2e-4 * np.exp(-0.01 * (t - 300.0) + 0.02 * (p / 1e6))


def dataset(name, states, factor=1.0, u_pct=2.0, fluid="R236FA", noise=0.0, seed=0, ids=None):
    t = np.array([s[0] for s in states], dtype=float)
    p = np.array([s[1] for s in states], dtype=float)
    y = trend_value(t, p) * factor
    if noise:
        y = y * (1 + noise * np.random.Generator(np.random.PCG64(seed)).standard_normal(len(y)))
    u = None if u_pct is None else (u_pct / 100) * y  # expanded relative uncertainty u_pct %, k = 2
    return Dataset(name, fluid, Quantity.VISCOSITY, t, y, pressure=p, expanded_uncertainty=u, point_ids=ids)


LAB = [(t, p) for t in (333.0, 353.0, 373.0) for p in (2e6, 3e6, 4e6)]
OLD = [(333.2, 1.2e6), (333.1, 2.5e6), (300.0, 1e6)]


def test_find_overlaps():
    a = dataset("lab", LAB)
    b = dataset("old", OLD)
    far = dataset("far", [(450.0, 1e6), (460.0, 1e6)])
    other = dataset("other", LAB, fluid="R134a")
    overlaps = find_overlaps([a, b, far, other], t_tol=1.0)
    assert [(o.a, o.b) for o in overlaps] == [("lab", "old")]
    o = overlaps[0]
    assert o.t_range == (333.0, 333.2)  # intersection of 333-373 K and 300-333.2 K
    assert sorted(o.b_points.tolist()) == [0, 1]  # the 300 K point is outside
    assert len(o.a_points) == 3  # the 333 K isotherm of "lab"
    with pytest.raises(DatasetError):
        find_overlaps([a], t_tol=-1)


def test_isotherms_group_within_tolerance():
    groups = isotherms(np.array([333.0, 353.0, 333.4, 352.8, 373.0]), tol=0.5)
    assert [g.tolist() for g in groups] == [[0, 2], [3, 1], [4]]


def test_isotherm_trend_is_exact_for_exact_data():
    trends = isotherm_trends(dataset("lab", LAB), tol=1.0)
    assert [round(tr.temperature) for tr in trends] == [333, 353, 373]
    for tr in trends:
        assert tr.coef[1] == pytest.approx(0.02e-6, rel=1e-9)
        value, u = tr.predict(1.2e6)
        assert value == pytest.approx(trend_value(tr.temperature, 1.2e6), rel=1e-12)
        assert u > 0  # statistical uncertainty of the extrapolated trend
        assert tr.u_stated == pytest.approx(0.01)
        assert tr.slope_significant


def test_model_free_comparison_finds_planted_offset():
    a = dataset("lab", LAB, u_pct=2.0)
    b = dataset("old", OLD, factor=1.05, u_pct=3.0)
    comps = compare_to_trends(b, a, t_tol=1.0)
    assert [c.point_id for c in comps] == [0, 1]  # the 300 K point has no isotherm in "lab"
    for c in comps:
        # b is 5 % high, apart from the small temperature difference to the 333 K isotherm
        expected = 100 * (1.05 * np.exp(-0.01 * c.delta_t) - 1)
        assert c.difference == pytest.approx(expected, abs=1e-9)
        assert c.u_combined == pytest.approx(200 * np.sqrt(0.01**2 + 0.015**2 + c.u_trend**2), rel=1e-12)
        assert not c.consistent  # 5 % > combined U ≈ 3.6 %
    assert comps[0].extrapolated  # 1.2 MPa is below the 2-4 MPa of "lab"
    assert not comps[1].extrapolated


def test_pressure_trend_check_detects_reversed_order():
    a = dataset("lab", LAB)
    # value at 1.2 MPa higher than lab's value at 2 MPa while the property rises with pressure
    high = Dataset("old", "R236FA", Quantity.VISCOSITY, [333.0], [trend_value(333.0, 2.0e6) * 1.03], pressure=[1.2e6])
    checks = pressure_trend_checks(a, high, t_tol=1.0)
    assert len(checks) == 1
    assert checks[0].slope_sign == 1
    assert not checks[0].passed
    assert (0, 0) in checks[0].violations
    fine = dataset("fine", [(333.0, 1.2e6)])
    assert all(c.passed for c in pressure_trend_checks(a, fine, t_tol=1.0))


def test_relative_offset_exact_and_birge():
    y = np.full(10, 1.03)
    ref = np.ones(10)
    off = relative_offset(y, ref, np.full(10, 0.01), dataset="d", reference_name="r", u_reference=0.02)
    assert off.offset == pytest.approx(3.0, rel=1e-12)
    assert off.birge == pytest.approx(0.0)
    lo, hi = off.ci95
    assert lo < 3.0 < hi
    assert off.ci95_total[0] < lo  # the reference's own uncertainty widens the total interval
    assert not off.significant  # 3 % is within the reference's 2 % (k = 1) uncertainty at 95 %
    tight = relative_offset(y, ref, np.full(10, 0.01), dataset="d", reference_name="r", u_reference=0.005)
    assert tight.significant
    noisy = 1.03 * (1 + 0.05 * np.random.Generator(np.random.PCG64(1)).standard_normal(50))
    wide = relative_offset(noisy, np.ones(50), np.full(50, 0.01), dataset="d", reference_name="r")
    assert wide.birge > 3  # scatter of 5 % against a stated 1 %
    width = wide.ci95[1] - wide.ci95[0]
    assert width > 2 * 1.96 * 1.0 / np.sqrt(50) * 3  # widened by the Birge ratio
    plain = relative_offset(noisy, np.ones(50), None, dataset="d", reference_name="r")
    assert plain.ci95[0] < plain.offset < plain.ci95[1]


def test_offset_interval_covers_the_true_offset_95_percent_of_the_time():
    rng = np.random.Generator(np.random.PCG64(2026))
    hits = 0
    trials = 400
    for _ in range(trials):
        u = rng.uniform(0.005, 0.02, 12)
        y = 1.04 * np.exp(u * rng.standard_normal(12))
        off = relative_offset(y, np.ones(12), u, dataset="d", reference_name="r")
        hits += off.ci95[0] <= 4.0 <= off.ci95[1]
    assert 0.92 <= hits / trials <= 0.98


def test_z_scores():
    zs = z_scores(
        np.array([1.0, 1.03, 0.97]), np.ones(3), np.full(3, 0.01), np.arange(3), dataset="d", reference_name="r"
    )
    np.testing.assert_allclose(zs.z, [0.0, 3.0, -3.0], atol=1e-12)
    assert zs.n_outside == 2


def test_consistency_report_model_free_and_model_based():
    truth = ECSViscosity.from_coolprop("R236FA")
    import CoolProp.CoolProp as CP  # noqa: N817

    def from_model(name, states, factor, u_pct):
        t = np.array([s[0] for s in states])
        p = np.array([s[1] for s in states])
        rho = np.array([CP.PropsSI("Dmolar", "T", a, "P", b, "R236FA") for a, b in states])
        y = truth.predict(t, rho) * factor
        return Dataset(name, "R236FA", Quantity.VISCOSITY, t, y, pressure=p, expanded_uncertainty=y * u_pct / 100)

    lab = from_model("lab", LAB, 1.0, 2.0)
    old = from_model("old", [(333.0, 1.2e6), (333.0, 2.5e6), (353.0, 3.5e6)], 1.047, 3.0)
    report = consistency_report([lab, old], {"ECS (CoolProp)": truth})
    assert [(o.a, o.b) for o in report.overlaps] == [("lab", "old")]
    # model-based: lab agrees with the model, old is 4.7 % high
    by = {(o.dataset, o.reference): o for o in report.offsets}
    assert by[("lab", "ECS (CoolProp)")].offset == pytest.approx(0.0, abs=1e-9)
    assert by[("old", "ECS (CoolProp)")].offset == pytest.approx(4.7, abs=1e-9)
    assert by[("old", "ECS (CoolProp)")].significant
    # model-free: the pressure trend of lab carries old's offset within the trend's curvature
    assert by[("old", "lab")].offset == pytest.approx(4.7, abs=0.3)
    assert by[("old", "lab")].extrapolated == 1
    assert any("extrapolat" in w for w in report.warnings)
    assert any("|z| > 2" in w for w in report.warnings)
    d = report.as_dict()
    assert d["offsets"]
    assert d["comparisons"]
    assert d["z_scores"]


def test_report_requires_one_fluid_and_property():
    with pytest.raises(DatasetError):
        consistency_report([dataset("a", LAB), dataset("b", LAB, fluid="R134a")])
    with pytest.raises(DatasetError):
        consistency_report([])


def test_trends_never_cross_the_saturation_curve():
    from propbench.core import Phase

    # one isotherm with two liquid points and one vapour point: the trend uses the liquid points only
    t = [340.0, 340.0, 340.0]
    p = [1e5, 2e6, 1e7]
    y = [trend_value(340.0, 1e5) * 0.1, trend_value(340.0, 2e6), trend_value(340.0, 1e7)]
    mixed = Dataset(
        "mixed", "R236FA", Quantity.VISCOSITY, t, y, pressure=p, phase=(Phase.VAPOR, Phase.LIQUID, Phase.LIQUID)
    )
    trends = isotherm_trends(mixed, 1.0)
    assert len(trends) == 1  # the single vapour point gives no trend
    assert trends[0].phase == "liquid"
    assert trends[0].coef[1] == pytest.approx(0.02e-6, rel=1e-9)
    probe = Dataset(
        "probe",
        "R236FA",
        Quantity.VISCOSITY,
        [340.0, 340.0],
        [trend_value(340.0, 5e6), trend_value(340.0, 2e5) * 0.1],
        pressure=[5e6, 2e5],
        phase=(Phase.LIQUID, Phase.VAPOR),
    )
    comps = compare_to_trends(probe, mixed, 1.0)
    assert [c.point_id for c in comps] == [0]  # the vapour point has no vapour trend to compare with
    assert comps[0].difference == pytest.approx(0.0, abs=1e-9)


def test_monotonic_bound_needs_no_extrapolation():
    a = dataset("lab", LAB)
    b = dataset("old", [(333.0, 1.2e6), (333.0, 5e6), (333.0, 3e6)], factor=1.05)
    c_low, c_high, c_inside = compare_to_trends(b, a, 1.0)
    end_low = trend_value(333.0, 2e6)
    assert c_low.bound_kind == "at least"  # rising with p: the 2 MPa value is an upper limit at 1.2 MPa
    assert c_low.bound == pytest.approx(100 * (trend_value(333.0, 1.2e6) * 1.05 / end_low - 1), rel=1e-9)
    assert c_low.bound < c_low.difference  # the bound is weaker than the extrapolated difference
    assert c_high.bound_kind == "at most"
    assert c_inside.bound is None
