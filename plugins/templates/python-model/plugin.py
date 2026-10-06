"""Sutherland's law for the dilute-gas viscosity of air, as a PropBench model plug-in (template).

    eta = eta0 (T/T0)^(3/2) (T0 + S) / (T + S)

W. Sutherland, Phil. Mag. 36 (1893) 507. Constants for air: eta0 = 1.716e-5 Pa s at T0 = 273.15 K, S = 110.4 K
(F. M. White, Viscous Fluid Flow, 3rd ed. (2006), Table 1-2). ``eta0`` and ``S`` can be fitted; ``T0`` is fixed.

A model plug-in defines ``MODEL``: an object with the ``propbench.models.Model`` protocol (predict, params,
with_params, bounds, check_values, validity, reference). Replace the equation, parameters and check values with
your own; keep the check values published.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np
from propbench.core import Quantity
from propbench.models.base import (
    CheckValue,
    Parameter,
    Validity,
    as_states,
    free_bounds,
    updated,
)


def _defaults() -> dict[str, Parameter]:
    return {
        "eta0": Parameter(
            "eta0", 1.716e-5, 1e-6, 1e-4, unit="Pa s", description="viscosity at T0"
        ),
        "T0": Parameter(
            "T0",
            273.15,
            1.0,
            2000.0,
            fixed=True,
            unit="K",
            description="reference temperature",
        ),
        "S": Parameter(
            "S", 110.4, 0.0, 2000.0, unit="K", description="Sutherland temperature"
        ),
    }


@dataclass(frozen=True)
class Sutherland:
    name: str = "Sutherland"
    fluid: str = "air"
    quantity: Quantity = Quantity.VISCOSITY
    _params: dict[str, Parameter] = field(default_factory=_defaults)

    def predict(
        self, temperature: np.typing.ArrayLike, molar_density: np.typing.ArrayLike
    ) -> np.ndarray:
        t, _ = as_states(temperature, molar_density)
        p = {k: v.value for k, v in self._params.items()}
        return p["eta0"] * (t / p["T0"]) ** 1.5 * (p["T0"] + p["S"]) / (t + p["S"])

    def params(self) -> Mapping[str, Parameter]:
        return dict(self._params)

    def with_params(self, values: Mapping[str, float]) -> Sutherland:
        return Sutherland(
            self.name, self.fluid, self.quantity, updated(self._params, values)
        )

    def bounds(self) -> tuple[np.ndarray, np.ndarray]:
        return free_bounds(self)

    def check_values(self) -> Sequence[CheckValue]:
        # Incropera et al. (2007), Table A.4, air at 0.1 MPa (the manifest lists more)
        return [
            CheckValue(
                300.0,
                0.0,
                1.846e-5,
                0.01,
                "Incropera et al. (2007), Table A.4, air, 300 K",
            )
        ]

    def validity(self) -> Validity:
        return Validity(170.0, 1900.0, 50.0, "dilute gas; about 2 % (White 2006)")

    def reference(self) -> str:
        return "W. Sutherland, Phil. Mag. 36 (1893) 507; F. M. White, Viscous Fluid Flow, 3rd ed. (2006)"


MODEL = Sutherland()
