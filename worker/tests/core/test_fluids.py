import pytest

from propbench.core import UnknownFluidError, identify_fluid


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        ("R134a", "R134a"),
        ("r134a", "R134a"),  # CoolProp's own lookup is case-sensitive here
        ("CF3I", "R13I1"),
        ("R13I1", "R13I1"),
        ("2314-97-8", "R13I1"),  # CAS number of CF3I
        ("811-97-2", "R134a"),  # CAS number of R134a
        (" nitrogen ", "Nitrogen"),
    ],
)
def test_identify_fluid(identifier, expected):
    assert identify_fluid(identifier) == expected


@pytest.mark.parametrize("identifier", ["", "unobtainium", "99999-99-9"])
def test_unknown_fluid(identifier):
    with pytest.raises(UnknownFluidError):
        identify_fluid(identifier)
