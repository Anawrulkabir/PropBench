"""Cross-check of the FeOs backend against an independent implementation (CLAUDE.md backend rule).

FeOs and CoolProp contain separate implementations of PC-SAFT (Gross & Sadowski 2001). With the same published
parameters both must give the same states to near machine precision; CoolProp's PC-SAFT library uses these same
parameters, so the test also checks that ``PCSAFT_PARAMETERS`` were transcribed correctly. A second check compares
PC-SAFT with the reference multiparameter EoS within PC-SAFT's published accuracy.
"""

import os

import numpy as np
import pytest

from propbench.backends import PCSAFT_PARAMETERS, BackendError, CoolPropBackend, FeOsBackend
from propbench.core import Phase

if os.environ.get("PB_REQUIRE_FEOS"):
    import feos  # noqa: F401  # CI installs the component: a missing FeOs must fail, not skip
else:
    pytest.importorskip("feos", reason="FeOs component not installed (uv sync --group feos)")

pytestmark = pytest.mark.feos

# (fluid, T / K, p / Pa): subcritical liquid and vapour states (CoolProp's PC-SAFT does not converge above Tc)
STATES = [
    ("n-Propane", 300.0, 5.0e6),
    ("n-Propane", 250.0, 1.0e6),
    ("n-Propane", 300.0, 2.0e5),
    ("n-Propane", 200.0, 1.0e5),
    ("Methane", 120.0, 2.0e6),
    ("Ethane", 200.0, 2.0e6),
    ("Ethane", 300.0, 2.0e6),
    ("n-Butane", 300.0, 2.0e6),
    ("n-Butane", 400.0, 2.0e6),
]


@pytest.fixture(scope="module")
def backends():
    return FeOsBackend(), CoolProp_pcsaft()


def CoolProp_pcsaft():  # noqa: N802 - reads as the backend's name
    return CoolPropBackend("PCSAFT")


@pytest.mark.parametrize(("fluid", "t", "p"), STATES)
def test_feos_agrees_with_coolprop_pcsaft(backends, fluid, t, p):
    feos_backend, coolprop = backends
    outputs = ["Dmolar", "Smolar_residual", "Z"]
    a = feos_backend.properties(fluid, "PT_INPUTS", [p], [t], outputs)
    b = coolprop.properties(fluid, "PT_INPUTS", [p], [t], outputs)
    assert not a.failed.any(), a.errors
    assert not b.failed.any(), b.errors
    assert a["Dmolar"][0] == pytest.approx(b["Dmolar"][0], rel=1e-8)
    assert a["Z"][0] == pytest.approx(b["Z"][0], rel=1e-8)
    assert a["Smolar_residual"][0] == pytest.approx(b["Smolar_residual"][0], abs=1e-6)  # J/(mol K)


def test_density_inputs_round_trip(backends):
    feos_backend, _ = backends
    rho = feos_backend.properties("n-Propane", "PT_INPUTS", [5.0e6], [300.0], ["Dmolar"])["Dmolar"][0]
    p = feos_backend.properties("n-Propane", "DmolarT_INPUTS", [rho], [300.0], ["P"])["P"][0]
    assert p == pytest.approx(5.0e6, rel=1e-9)


def test_pcsaft_is_close_to_the_reference_eos_for_propane_liquid(backends):
    # Gross & Sadowski (2001) report liquid densities of n-alkanes within about 1-2 %; check 2 %.
    feos_backend, _ = backends
    pcsaft = feos_backend.properties("n-Propane", "PT_INPUTS", [5.0e6], [300.0], ["Dmass"])["Dmass"][0]
    reference = CoolPropBackend("HEOS").property("n-Propane", "PT_INPUTS", (5.0e6, 300.0), "Dmass").value
    assert abs(pcsaft / reference - 1) < 0.02


def test_phases(backends):
    feos_backend, _ = backends
    result = feos_backend.phases("propane", [300.0, 300.0, 400.0], [2.0e6, 2.0e5, 1.0e6])
    assert result.phases == (Phase.LIQUID, Phase.VAPOR, Phase.SUPERCRITICAL)


def test_failures_and_unsupported_requests(backends):
    feos_backend, _ = backends
    batch = feos_backend.properties("n-Propane", "PT_INPUTS", [5.0e6, -1.0], [300.0, 300.0], ["Dmolar"])
    np.testing.assert_array_equal(batch.failed, [False, True])
    with pytest.raises(BackendError, match="no PC-SAFT parameters"):
        feos_backend.properties("R134a", "PT_INPUTS", [1e6], [300.0], ["Dmolar"])
    with pytest.raises(BackendError, match="not supported"):
        feos_backend.properties("n-Propane", "HmolarP_INPUTS", [1.0], [1e6], ["Dmolar"])
    with pytest.raises(BackendError, match="not supported"):
        feos_backend.properties("n-Propane", "PT_INPUTS", [1e6], [300.0], ["viscosity"])


def test_parameter_table_cites_its_source():
    assert all("Gross & Sadowski" in p.reference for p in PCSAFT_PARAMETERS.values())
