"""CF3I reference regression case (CLAUDE.md; expected values in README §7), on the published data only.

Covered here: the NISTIR 8209 check values and the model-free 333 K difference. The REFPROP-model AARD values and
the ECS ψ+k fit (README §7) are added once their computation is confirmed with the manuscript's author.
"""

import numpy as np
import pytest

from propbench.consist import consistency_report
from propbench.models.reference import load_registry


def test_published_data(cf3i):
    assert {k: len(v) for k, v in cf3i.items()} == {
        "tuhin2024_liquid": 24,
        "tuhin2024_vapor": 21,
        "duan1999_satliq": 18,
    }
    assert cf3i["tuhin2024_liquid"].provenance.doi == "10.1007/s10765-024-03332-4"
    assert cf3i["duan1999_satliq"].provenance.doi == "10.1016/S0378-3812(99)00216-2"


def test_nistir_8209_check_values():
    """README §7: CF3I viscosity 168.5169 µPa·s (and thermal conductivity 40.8518 mW/(m·K), NISTIR 8209 Table 7) at
    356.8 K and 8.724 mol/L."""
    models = {e.id: e.model() for e in load_registry()}
    eta = models["nistir8209-r13i1-viscosity"].predict([356.8], [8724.0])[0]
    lam = models["nistir8209-r13i1-conductivity"].predict([356.8], [8724.0])[0]
    assert eta * 1e6 == pytest.approx(168.5169, rel=1e-5)
    assert lam * 1e3 == pytest.approx(40.8518, rel=1e-5)


def test_model_free_333_k_difference(cf3i):
    """README §7: the 1999 saturated-liquid value at 333 K is at least 4.9 % above the 2024 liquid data, without any
    model: viscosity rises with pressure, so the 2024 value at the lowest measured pressure (2 MPa) bounds the value
    at the saturation pressure (1.18 MPa) from above."""
    report = consistency_report([cf3i["tuhin2024_liquid"], cf3i["duan1999_satliq"]], t_tol=1.0)
    [c] = [c for c in report.comparisons if c.a == "tuhin2024_liquid" and c.b == "duan1999_satliq"]
    assert c.temperature == pytest.approx(333.15)
    assert c.bound_kind == "at least"
    assert round(c.bound, 1) >= 4.9
    # combined stated expanded uncertainty of the two sources (2.22 % and 3 %): ± 3.7 %
    assert np.hypot(200 * c.u_a, 200 * c.u_point) == pytest.approx(3.7, abs=0.05)
    assert not c.consistent
    assert any(not t.passed for t in report.trend_checks)  # pressure trend at equal T fails
