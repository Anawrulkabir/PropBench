"""ThermoML import (IUPAC standard XML for thermophysical data; used by the NIST TRC archive and journals).

Supported subset: pure-compound data (``PureOrMixtureData`` with one component) of the properties in ``_PROPERTIES``,
with temperature and pressure given as variables or constraints, and expanded or standard uncertainties per value.
Anything else in a file is reported in ``ThermoMLImport.warnings``, never silently dropped.

Reference: M. Frenkel et al., "ThermoML — an XML-based approach for storage and exchange of experimental and
critically evaluated thermophysical and thermochemical property data", J. Chem. Eng. Data 48 (2003) 2-13 and later
parts; schema at https://trc.nist.gov/ThermoML/.

Parsing uses the standard library's ElementTree: it does not fetch external entities, and the bundled expat (≥ 2.4.1)
limits entity expansion, so untrusted files cannot trigger network access or exponential expansion.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from propbench.core import (
    Dataset,
    Phase,
    Provenance,
    Quantity,
    UnknownFluidError,
    difference_to_si,
    identify_fluid,
    to_si,
)
from propbench.importers.tabular import ImportFileError

# ThermoML property names ("name, unit") → quantity
_PROPERTIES: dict[str, Quantity] = {
    "viscosity": Quantity.VISCOSITY,
    "thermal conductivity": Quantity.THERMAL_CONDUCTIVITY,
    "mass density": Quantity.MASS_DENSITY,
    "molar density": Quantity.MOLAR_DENSITY,
    "speed of sound": Quantity.SPEED_OF_SOUND,
    "surface tension liquid-gas": Quantity.SURFACE_TENSION,
    "vapor or sublimation pressure": Quantity.VAPOR_PRESSURE,
}

_PHASES = {
    "liquid": Phase.LIQUID,
    "gas": Phase.VAPOR,
    "supercritical fluid": Phase.SUPERCRITICAL,
    "fluid (supercritical or subcritical phases)": Phase.UNKNOWN,
}

# Expanded uncertainties in ThermoML are stated at a level of confidence; 95 % corresponds to k = 2.
_COVERAGE_FACTOR = 2.0


@dataclass
class ThermoMLImport:
    datasets: list[Dataset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def read_thermoml(path: str | Path) -> ThermoMLImport:
    """Read all supported pure-compound datasets from a ThermoML file."""
    try:
        root = ET.parse(Path(path)).getroot()
    except ET.ParseError as exc:
        raise ImportFileError(f"not a valid XML file: {exc}") from exc
    _strip_namespaces(root)
    if root.tag != "DataReport":
        raise ImportFileError(f"not a ThermoML file (root element <{root.tag}>, expected <DataReport>)")

    provenance = _provenance(root)
    compounds = _compounds(root)
    result = ThermoMLImport()
    stem = Path(path).stem
    for block in root.findall("PureOrMixtureData"):
        number = _text(block, "nPureOrMixtureDataNumber") or str(len(result.datasets) + 1)
        components = [_text(c, "RegNum/nOrgNum") for c in block.findall("Component")]
        if len(components) != 1:
            result.warnings.append(f"data block {number}: mixtures are not supported yet (skipped)")
            continue
        names = compounds.get(components[0] or "", [])
        fluid = _identify(names)
        if fluid is None:
            result.warnings.append(f"data block {number}: compound {names or components} is not in the fluid library")
            continue
        for prop in block.findall("Property"):
            try:
                dataset = _dataset(block, prop, fluid, f"{stem} #{number}", provenance)
            except _SkipError as skip:
                result.warnings.append(f"data block {number}: {skip}")
                continue
            except ValueError as exc:  # inconsistent values: report and continue with the rest of the file
                result.warnings.append(f"data block {number}: {exc}")
                continue
            result.datasets.append(dataset)
    return result


class _SkipError(Exception):
    """A property block that is valid ThermoML but not supported."""


def _dataset(block: ET.Element, prop: ET.Element, fluid: str, name: str, provenance: Provenance) -> Dataset:
    prop_number = _text(prop, "nPropNumber")
    prop_name = _first_text(prop, "Property-MethodID/PropertyGroup/*/ePropName")
    if prop_name is None:
        raise _SkipError(f"property {prop_number} has no ePropName")
    label, unit = _split_name(prop_name)
    quantity = _PROPERTIES.get(label.casefold())
    if quantity is None:
        raise _SkipError(f"property '{prop_name}' is not supported yet")
    method = _first_text(prop, "Property-MethodID/PropertyGroup/*/eMethodName") or _first_text(
        prop, "Property-MethodID/PropertyGroup/*/sMethodName"
    )
    phase_text = _first_text(prop, "PropPhaseID/ePropPhase")
    phase = _PHASES.get((phase_text or "").casefold(), Phase.UNKNOWN)

    variables = _state_columns(block)
    constraints = _constraints(block)
    temperature: list[tuple[float, str]] = []
    pressure: list[tuple[float, str] | None] = []
    values: list[float] = []
    uncertainty: list[float | None] = []
    for row in block.findall("NumValues"):
        value_el = next((pv for pv in row.findall("PropertyValue") if _text(pv, "nPropNumber") == prop_number), None)
        if value_el is None:
            continue
        state: dict[str, tuple[float, str]] = dict(constraints)
        for var in row.findall("VariableValue"):
            kind_unit = variables.get(_text(var, "nVarNumber") or "")
            if kind_unit is not None:
                kind, unit_of_var = kind_unit
                state[kind] = (_float(_text(var, "nVarValue"), f"variable {kind}"), unit_of_var)
        if "temperature" not in state:
            raise _SkipError(f"property '{prop_name}': a point has no temperature")
        temperature.append(state["temperature"])
        pressure.append(state.get("pressure"))
        values.append(_float(_text(value_el, "nPropValue"), prop_name))
        uncertainty.append(_uncertainty(value_el))
    if not values:
        raise _SkipError(f"property '{prop_name}' has no values")

    t_si = np.array([to_si(t, u, Quantity.TEMPERATURE) for t, u in temperature], dtype=float)
    v_si = to_si(values, _unit(unit), quantity)
    p_si = None
    known_pressures = [p for p in pressure if p is not None]
    if len(known_pressures) == len(pressure):
        p_si = np.array([to_si(p, u, Quantity.PRESSURE) for p, u in known_pressures], dtype=float)
    elif quantity is not Quantity.VAPOR_PRESSURE:
        raise _SkipError(f"property '{prop_name}': pressure is missing for some points (state undefined)")
    u_si = None
    if all(u is not None for u in uncertainty):
        u_si = difference_to_si(np.array(uncertainty, dtype=float), _unit(unit), quantity)
    method_provenance = Provenance(
        doi=provenance.doi, citation=provenance.citation, method=method, purity=provenance.purity
    )
    return Dataset(
        name=name if len(block.findall("Property")) == 1 else f"{name} {label}",
        fluid=fluid,
        quantity=quantity,
        temperature=t_si,
        values=v_si,
        pressure=p_si,
        expanded_uncertainty=u_si,
        coverage_factor=_COVERAGE_FACTOR,
        phase=(phase,) * len(values),
        provenance=method_provenance,
    )


def _state_columns(block: ET.Element) -> dict[str, tuple[str, str]]:
    """nVarNumber → ("temperature" | "pressure", unit) for the variables PropBench understands."""
    out: dict[str, tuple[str, str]] = {}
    for var in block.findall("Variable"):
        number = _text(var, "nVarNumber")
        kind = _state_kind(var.find("VariableID/VariableType"))
        if number and kind:
            out[number] = kind
    return out


def _constraints(block: ET.Element) -> dict[str, tuple[float, str]]:
    """Constant state variables of a block: "temperature" | "pressure" → (value, unit)."""
    out: dict[str, tuple[float, str]] = {}
    for con in block.findall("Constraint"):
        kind = _state_kind(con.find("ConstraintID/ConstraintType"))
        if kind:
            out[kind[0]] = (_float(_text(con, "nConstraintValue"), f"constraint {kind[0]}"), kind[1])
    return out


def _state_kind(type_el: ET.Element | None) -> tuple[str, str] | None:
    if type_el is None:
        return None
    for tag, kind in (("eTemperature", "temperature"), ("ePressure", "pressure")):
        text = _text(type_el, tag)
        if text:
            return kind, _unit(_split_name(text)[1])
    return None


def _uncertainty(value_el: ET.Element) -> float | None:
    """Absolute expanded uncertainty (k = 2) of one value, or None if not stated."""
    for path, factor in (
        ("CombinedUncertainty/nCombExpandUncertValue", 1.0),
        ("PropUncertainty/nExpandUncertValue", 1.0),
        ("CombinedUncertainty/nCombStdUncertValue", _COVERAGE_FACTOR),
        ("PropUncertainty/nStdUncertValue", _COVERAGE_FACTOR),
    ):
        text = _first_text(value_el, path)
        if text is not None:
            return _float(text, "uncertainty") * factor
    return None


def _provenance(root: ET.Element) -> Provenance:
    citation = root.find("Citation")
    if citation is None:
        return Provenance()
    authors = [a.text.strip() for a in citation.findall("sAuthor") if a.text]
    parts = [
        ", ".join(authors),
        _text(citation, "sTitle"),
        _text(citation, "sPubName"),
        _text(citation, "yrPubYr"),
    ]
    return Provenance(doi=_text(citation, "sDOI"), citation=". ".join(p.rstrip(".") for p in parts if p) or None)


def _compounds(root: ET.Element) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for compound in root.findall("Compound"):
        number = _text(compound, "RegNum/nOrgNum")
        if not number:
            continue
        names = [el.text.strip() for el in compound if el.text and el.text.strip() and _is_name_tag(el.tag)]
        out[number] = names
    return out


def _is_name_tag(tag: str) -> bool:
    return tag in {"sCommonName", "sIUPACName", "sFormulaMolec"} or "CAS" in tag


def _identify(names: list[str]) -> str | None:
    for name in names:
        try:
            return identify_fluid(name)
        except UnknownFluidError:
            continue
    return None


def _split_name(text: str) -> tuple[str, str]:
    label, _, unit = text.rpartition(",")
    return (label.strip(), unit.strip()) if label else (text.strip(), "")


def _unit(unit: str) -> str:
    """ThermoML writes kg/m3, W/m/K: add the exponent marker pint expects."""
    return re.sub(r"(?<=[A-Za-z])(\d)", r"^\1", unit)


def _strip_namespaces(root: ET.Element) -> None:
    for el in root.iter():
        if isinstance(el.tag, str) and "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _text(el: ET.Element, path: str) -> str | None:
    found = el.find(path)
    return found.text.strip() if found is not None and found.text and found.text.strip() else None


def _first_text(el: ET.Element, path: str) -> str | None:
    for found in el.findall(path):
        if found.text and found.text.strip():
            return found.text.strip()
    return None


def _float(text: str | None, what: str) -> float:
    try:
        return float(text)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ValueError(f"{what}: '{text}' is not a number") from None
