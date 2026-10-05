import numpy as np
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from propbench.core import Dataset, DatasetError, Phase, Provenance, Quantity


def viscosity_dataset(**overrides):
    kwargs = {
        "name": "test",
        "fluid": "R134a",
        "quantity": Quantity.VISCOSITY,
        "temperature": [300.0, 310.0, 320.0],
        "values": [2.0e-4, 1.8e-4, 1.6e-4],
        "pressure": [1.0e6, 1.0e6, 2.0e6],
        "expanded_uncertainty": [4.0e-6, 3.6e-6, 3.2e-6],
        "phase": [Phase.LIQUID] * 3,
        "provenance": Provenance(doi="10.1000/example", method="vibrating wire"),
    }
    kwargs.update(overrides)
    return Dataset(**kwargs)


def test_arrays_are_float_read_only_and_ids_default_to_index():
    ds = viscosity_dataset()
    assert len(ds) == 3
    assert ds.temperature.dtype == float
    assert not ds.values.flags.writeable
    with pytest.raises(ValueError, match="read-only"):
        ds.values[0] = 1.0
    np.testing.assert_array_equal(ds.point_ids, [0, 1, 2])


def test_uncertainty_views():
    ds = viscosity_dataset()
    np.testing.assert_allclose(ds.relative_uncertainty, [0.02, 0.02, 0.02])
    np.testing.assert_allclose(ds.standard_uncertainty, [2.0e-6, 1.8e-6, 1.6e-6])
    assert viscosity_dataset(expanded_uncertainty=None).relative_uncertainty is None


def test_select_keeps_point_ids_and_all_columns():
    ds = viscosity_dataset()
    sub = ds.select(np.array([True, False, True]))
    np.testing.assert_array_equal(sub.point_ids, [0, 2])
    np.testing.assert_array_equal(sub.temperature, [300.0, 320.0])
    np.testing.assert_array_equal(sub.pressure, [1e6, 2e6])
    assert sub.phase == (Phase.LIQUID, Phase.LIQUID)
    assert ds.select([1]).point_ids.tolist() == [1]


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"values": [1.0, 2.0]}, "values has 2 values"),
        ({"temperature": [300.0, -1.0, 320.0]}, "temperatures must be positive"),
        ({"pressure": [1e6, 0.0, 1e6]}, "pressures must be positive"),
        ({"values": [1.0, float("nan"), 1.0]}, "non-finite"),
        ({"expanded_uncertainty": [1.0, -1.0, 1.0]}, "must not be negative"),
        ({"pressure": None}, "need pressure or molar density"),
        ({"phase": [Phase.LIQUID]}, "phase has 1 entries"),
        ({"phase": ["plasma", "liquid", "liquid"]}, "plasma"),
        ({"point_ids": [0, 0, 1]}, "unique"),
        ({"coverage_factor": 0.0}, "coverage factor"),
        ({"name": " "}, "needs a name"),
        ({"temperature": [], "values": [], "pressure": [], "expanded_uncertainty": [], "phase": None}, "at least one"),
        ({"values": ["a", "b", "c"]}, "must contain numbers"),
    ],
)
def test_validation(overrides, message):
    with pytest.raises((DatasetError, ValueError), match=message):
        viscosity_dataset(**overrides)


def test_vapor_pressure_needs_temperature_only():
    ds = Dataset(name="psat", fluid="R134a", quantity=Quantity.VAPOR_PRESSURE, temperature=[300.0], values=[7.0e5])
    assert ds.pressure is None


def test_state_by_density():
    ds = viscosity_dataset(pressure=None, molar_density=[1.0e4, 1.0e4, 1.0e4])
    assert ds.molar_density is not None


def test_json_round_trip_and_schema_version():
    ds = viscosity_dataset(point_ids=[10, 11, 12])
    text = ds.to_json()
    assert '"schema_version": 1' in text
    back = Dataset.from_json(text)
    assert back == ds
    assert back.provenance.method == "vibrating wire"
    np.testing.assert_array_equal(back.point_ids, [10, 11, 12])


def test_unknown_schema_or_fields_are_rejected():
    data = viscosity_dataset().to_dict()
    with pytest.raises(DatasetError, match="schema version"):
        Dataset.from_dict({**data, "schema_version": 2})
    with pytest.raises(DatasetError, match="unknown dataset fields"):
        Dataset.from_dict({**data, "colour": "red"})


finite = st.floats(min_value=1e-6, max_value=1e9, allow_nan=False, allow_infinity=False)


@settings(max_examples=50, deadline=None)
@given(
    rows=st.lists(st.tuples(finite, finite, finite, finite), min_size=1, max_size=30),
    k=st.floats(min_value=1.0, max_value=3.0),
)
def test_json_round_trip_is_exact_for_any_valid_dataset(rows, k):
    t, v, p, u = (list(col) for col in zip(*rows, strict=True))
    ds = Dataset(
        name="h",
        fluid="R134a",
        quantity=Quantity.MASS_DENSITY,
        temperature=t,
        values=v,
        pressure=p,
        expanded_uncertainty=u,
        coverage_factor=k,
    )
    back = Dataset.from_json(ds.to_json())
    assert back == ds
    np.testing.assert_array_equal(back.values, ds.values)  # bit-exact: JSON floats round-trip
