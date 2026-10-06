from pathlib import Path

import numpy as np
import pytest

from propbench.core import Phase, Quantity
from propbench.importers import ImportFileError, read_thermoml

SAMPLE = Path(__file__).parent.parent / "data" / "thermoml" / "r134a_sample.xml"


@pytest.fixture(scope="module")
def sample():
    return read_thermoml(SAMPLE)


def test_viscosity_block_with_variables_and_expanded_uncertainty(sample):
    viscosity = next(d for d in sample.datasets if d.quantity is Quantity.VISCOSITY)
    assert viscosity.fluid == "R134a"
    np.testing.assert_allclose(viscosity.temperature, [300.0, 280.0])
    np.testing.assert_allclose(viscosity.pressure, [1.0e6, 2.0e6])  # kPa -> Pa
    np.testing.assert_allclose(viscosity.values, [191.6e-6, 250.3e-6])
    np.testing.assert_allclose(viscosity.expanded_uncertainty, [3.8e-6, 5.0e-6])
    assert viscosity.coverage_factor == 2.0
    assert viscosity.phase == (Phase.LIQUID, Phase.LIQUID)
    assert viscosity.provenance.method == "Vibrating wire"
    assert viscosity.provenance.doi == "10.1000/test.0001"
    assert viscosity.provenance.citation.startswith("Doe, J., Roe, R. Example viscosity")


def test_density_block_with_pressure_constraint_and_standard_uncertainty(sample):
    density = next(d for d in sample.datasets if d.quantity is Quantity.MASS_DENSITY)
    np.testing.assert_allclose(density.pressure, [1.0e6, 1.0e6])
    np.testing.assert_allclose(density.values, [1201.53, 1274.52])
    np.testing.assert_allclose(density.expanded_uncertainty, [0.5, 0.5])  # standard 0.25 x k=2


def test_unsupported_blocks_are_reported_not_dropped(sample):
    assert len(sample.datasets) == 2
    assert any("mixtures are not supported" in w for w in sample.warnings)
    assert any("Refractive index" in w for w in sample.warnings)


def test_not_thermoml(tmp_path):
    path = tmp_path / "other.xml"
    path.write_text("<root/>", encoding="utf-8")
    with pytest.raises(ImportFileError, match="not a ThermoML file"):
        read_thermoml(path)


def test_invalid_xml(tmp_path):
    path = tmp_path / "broken.xml"
    path.write_text("<DataReport>", encoding="utf-8")
    with pytest.raises(ImportFileError, match="not a valid XML file"):
        read_thermoml(path)


def test_entity_expansion_is_refused(tmp_path):
    # "billion laughs": expat refuses runaway entity expansion, so a hostile file cannot exhaust memory
    entities = "".join(f'<!ENTITY l{i} "{f"&l{i - 1};" * 10}">' for i in range(1, 10))  # 10^9 x "lol"
    path = tmp_path / "bomb.xml"
    path.write_text(
        f'<?xml version="1.0"?><!DOCTYPE DataReport [<!ENTITY l0 "lol">{entities}]><DataReport>&l9;</DataReport>',
        encoding="utf-8",
    )
    with pytest.raises(ImportFileError, match="amplification"):
        read_thermoml(path)
