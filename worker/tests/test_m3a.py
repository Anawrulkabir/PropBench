"""M3a acceptance and unit tests: safe formulas, worksheets, general curve fitting with global fits (recovers known
parameters on synthetic data), the GUM example of JCGM 100 Annex H.1, Monte Carlo, references."""

import math

import numpy as np
import pytest

from propbench import curvefit, expr, gum, refs, worksheet
from propbench.core import Dataset, Quantity
from propbench.curvefit import ParameterSpec, Series

# --- formulas ---


def test_formulas_compute_vectorised():
    v = expr.evaluate("a * exp(-b / T) + where(T > 300, 1, 0)", {"a": 2.0, "b": 100.0, "T": np.array([250.0, 350.0])})
    np.testing.assert_allclose(v, [2 * math.exp(-0.4), 2 * math.exp(-100 / 350) + 1])
    assert expr.names("nu * rho + pi") == {"nu", "rho"}


@pytest.mark.parametrize(
    "bad",
    ["__import__('os')", "x.__class__", "x[0]", "(lambda: 1)()", "open('f')", "[1, 2]", "a if b else c; d"],
)
def test_formulas_cannot_do_anything_but_compute(bad):
    with pytest.raises(expr.FormulaError):
        expr.evaluate(bad, {"x": 1.0, "a": 1, "b": 1, "c": 1, "d": 1})


def test_eos_function_in_formulas():
    rho = expr.evaluate("eos('Dmass', T, p, fluid='R134a')", {"T": np.array([300.0]), "p": np.array([1e6])})
    assert rho[0] == pytest.approx(1201.53, abs=0.005)


# --- worksheets ---


def test_worksheet_formula_columns_filter_and_statistics():
    ds = Dataset(
        "d",
        "R134a",
        Quantity.VISCOSITY,
        np.array([280.0, 300.0, 320.0, 340.0]),
        np.array([2.4e-4, 2.0e-4, 1.7e-4, 1.4e-4]),
        pressure=np.full(4, 2e6),
    )
    out = worksheet.compute(
        ds,
        [{"name": "rho_m", "formula": "eos('Dmass', T, p, fluid='R134a')"}, {"name": "nu", "formula": "y / rho_m"}],
        row_filter="T < 335",
        masked=[0],
    )
    assert set(out["columns"]) == {"rho_m", "nu"}
    assert out["filter"].tolist() == [True, True, True, False]
    st = out["statistics"]["T"]
    assert st["n"] == 2  # point 0 masked, point 3 filtered out
    assert st["mean"] == pytest.approx(310.0)
    assert st["std"] == pytest.approx(math.sqrt(200.0))
    with pytest.raises(expr.FormulaError):
        worksheet.compute(ds, [{"name": "1bad", "formula": "T"}])


# --- curve fitting ---


def synthetic(seed=0):
    """Two 'laboratories' measuring y = a·exp(b/T) with a shared b, their own a, and 0.5 % noise."""
    rng = np.random.Generator(np.random.PCG64(seed))
    truth = {"a[lab1]": 1.2e-5, "a[lab2]": 1.5e-5, "b": 850.0}
    out = []
    for lab in ("lab1", "lab2"):
        t = np.linspace(260.0, 380.0, 25)
        y = truth[f"a[{lab}]"] * np.exp(truth["b"] / t)
        sigma = 0.005 * y
        out.append(Series(lab, {"T": t}, y + rng.normal(0, sigma), sigma))
    return out, truth


def test_global_fit_recovers_known_parameters():
    series, truth = synthetic()
    params = {"a": ParameterSpec(1e-5, 0, 1), "b": ParameterSpec(500.0, 0, 5000)}
    r = curvefit.fit("a * exp(b / T)", series, params, local=["a"])
    assert r.success
    for name, value in truth.items():
        assert abs(r.values[name] - value) < 3 * r.errors[name], name
    assert r.reduced_chi2 == pytest.approx(1.0, abs=0.5)
    assert len(r.correlation) == 3
    assert r.outliers == {"lab1": [], "lab2": []}


def test_scale_factors_fixed_parameters_and_multistart_are_deterministic():
    series, _ = synthetic(1)
    biased = [series[0], Series("lab2", series[1].x, series[1].y * 1.03, series[1].sigma * 1.03)]
    params = {
        "a": ParameterSpec(1e-5, 1e-7, 1e-3),
        "b": ParameterSpec(800.0, 100, 2000),
        "c": ParameterSpec(0.0, fixed=True),
    }
    one = curvefit.fit("a * exp(b / T) + c", biased, params, scale_factors=True, multistart=5, seed=7)
    two = curvefit.fit("a * exp(b / T) + c", biased, params, scale_factors=True, multistart=5, seed=7)
    assert one.values == two.values
    assert one.starts == 6
    assert one.values["c"] == 0.0
    assert one.errors["c"] is None
    assert "lab2" in one.scale_factors


def test_f_test_and_outliers():
    rng = np.random.Generator(np.random.PCG64(3))
    x = np.linspace(0, 10, 40)
    y = 1.0 + 0.5 * x + 0.08 * x**2 + rng.normal(0, 0.05, x.size)
    y[17] += 2.0  # one gross outlier
    s = [Series("d", {"x": x}, y)]
    lin = curvefit.fit("c0 + c1 * x", s, {"c0": ParameterSpec(0.0), "c1": ParameterSpec(1.0)})
    quad = curvefit.fit(
        "c0 + c1 * x + c2 * x**2", s, {"c0": ParameterSpec(0.0), "c1": ParameterSpec(1.0), "c2": ParameterSpec(0.0)}
    )
    test = curvefit.f_test(lin, quad)
    assert test["p"] < 1e-6, "the quadratic term is justified"
    assert 17 in quad.outliers["d"]
    with pytest.raises(curvefit.CurveFitError):
        curvefit.f_test(quad, lin)
    with pytest.raises(curvefit.CurveFitError, match="neither variables nor parameters"):
        curvefit.fit("c0 + z", s, {"c0": ParameterSpec(0.0)})


# --- GUM (JCGM 100:2008 Annex H.1, calibration of an end gauge) ---

H1_MODEL = "ls + d - ls * (dalpha * theta + alpha_s * dtheta)"  # first-order model (H.1.2, eq. H.3), in mm
H1_INPUTS = [
    gum.Input("ls", 50.000623, 25e-6, 18),  # calibrated length of the standard (H.1.3.1)
    gum.Input("d", 215e-6, 9.7e-6, 25.6),  # measured difference in length (H.1.3.2)
    gum.Input("alpha_s", 11.5e-6, 1.2e-6),  # thermal expansion coefficient of the standard (H.1.3.3)
    gum.Input("theta", -0.1, 0.41),  # deviation of the temperature from 20 °C (H.1.3.4)
    gum.Input("dalpha", 0.0, 0.58e-6, 50),  # difference in expansion coefficients (H.1.3.5)
    gum.Input("dtheta", 0.0, 0.029, 2),  # difference in temperatures (H.1.3.6)
]


def test_jcgm_100_annex_h1_end_gauge():
    r = gum.linear(H1_MODEL, H1_INPUTS, p=0.99)
    assert r["value"] == pytest.approx(50.000838, abs=5e-7)  # l = 50.000 838 mm
    assert round(r["u"] * 1e6) == 32  # u_c(l) = 32 nm
    assert math.floor(r["dof"]) == 16  # ν_eff = 16
    assert r["k"] == pytest.approx(2.92, abs=0.005)  # k_99 = t_99(16) = 2.92
    assert round(r["U"] * 1e6) == 93  # U_99 = 93 nm
    contributions = {b["name"]: b["contribution"] * 1e6 for b in r["budget"]}
    assert contributions["ls"] == pytest.approx(25.0, abs=0.05)  # Table H.1: 25 nm
    assert contributions["dtheta"] == pytest.approx(16.7, abs=0.1)  # 16.6 nm (−575 nm/°C × 0.029 °C)
    assert contributions["dalpha"] == pytest.approx(2.9, abs=0.05)  # 2.9 nm
    assert contributions["theta"] == pytest.approx(0.0, abs=1e-9)  # zero to first order


@pytest.mark.parametrize(
    ("dof", "p", "k"), [(16, 0.95, 2.12), (16, 0.9545, 2.17), (16, 0.99, 2.92), (math.inf, 0.9545, 2.00)]
)
def test_coverage_factors_of_jcgm_100_table_g2(dof, p, k):
    assert gum.coverage_factor(dof, p) == pytest.approx(k, abs=0.005)


def test_monte_carlo_is_reproducible_and_agrees_with_linear_propagation():
    lin = gum.linear("a * b", [gum.Input("a", 10.0, 0.1), gum.Input("b", 5.0, 0.05)])
    one = gum.monte_carlo("a * b", [gum.Input("a", 10.0, 0.1), gum.Input("b", 5.0, 0.05)], draws=100_000, seed=11)
    two = gum.monte_carlo("a * b", [gum.Input("a", 10.0, 0.1), gum.Input("b", 5.0, 0.05)], draws=100_000, seed=11)
    assert one == two
    assert one["u"] == pytest.approx(lin["u"], rel=0.02)
    assert one["value"] == pytest.approx(lin["value"], rel=1e-3)
    rect = gum.monte_carlo("x", [gum.Input("x", 0.0, 1.0, distribution="rectangular")], draws=200_000, seed=1)
    assert rect["interval"][1] == pytest.approx(0.9545 * math.sqrt(3), rel=0.01)  # rectangular ± √3 u
    corr = gum.linear("a - b", [gum.Input("a", 1.0, 0.1), gum.Input("b", 1.0, 0.1)], {("a", "b"): 1.0})
    assert corr["u"] == pytest.approx(0.0, abs=1e-12), "fully correlated inputs cancel"


# --- references ---

BIB = r"""
@article{Tuhin2024,
  author = {Tuhin, Md. Anawrul Kabir and Morshed, A. and Kariya, Keishi and Miyara, Akio},
  title = {Viscosity of {CF3I}},
  journal = {Int. J. Thermophys.},
  volume = 45, pages = {41}, year = {2024},
  doi = {10.1007/s10765-024-03332-4}
}
@comment{ignored}
@article{Duan1999, author = "Duan, Y. Y. and Shi, L.", journal = {Fluid Phase Equilib.}, volume = {162},
  pages = {303--312}, year = 1999, doi = {10.1016/S0378-3812(99)00216-2}}
"""


def test_bibtex_round_trip_and_citations():
    entries = refs.parse_bibtex(BIB)
    assert [e["key"] for e in entries] == ["Tuhin2024", "Duan1999"]
    assert entries[0]["fields"]["title"] == "Viscosity of CF3I"
    assert refs.citation(entries[0]) == "Tuhin et al. (2024) Int. J. Thermophys. 45:41, doi:10.1007/s10765-024-03332-4"
    assert refs.citation(entries[1]).startswith("Duan and Shi (1999) Fluid Phase Equilib. 162:303--312")
    assert refs.parse_bibtex(refs.to_bibtex(entries)) == entries


def test_doi_lookup_offline():
    payload = (
        b'{"message": {"title": ["Viscosity of CF3I"], "author": [{"family": "Tuhin", "given": "M."}], '
        b'"short-container-title": ["Int. J. Thermophys."], "volume": "45", "article-number": "41", '
        b'"issued": {"date-parts": [[2024, 3]]}}}'
    )
    ref = refs.lookup_doi("https://doi.org/10.1007/s10765-024-03332-4", fetch=lambda url: payload)
    assert ref["key"] == "Tuhin2024"
    assert ref["fields"]["pages"] == "41"
    with pytest.raises(refs.RefError, match="not a DOI"):
        refs.lookup_doi("hello")
