"""PropBench science package: backends, models and the worker process.

Every property call goes through a :class:`propbench.backends.Backend`; see README §2i.
"""

from importlib.metadata import PackageNotFoundError, version

from propbench.backends import Backend, BackendError, PropertyResult
from propbench.backends.coolprop import CoolPropBackend

try:
    __version__ = version("propbench")
except PackageNotFoundError:  # pragma: no cover - only when run from a source tree without install
    __version__ = "0.0.0+unknown"

__all__ = [
    "Backend",
    "BackendError",
    "CoolPropBackend",
    "PropertyResult",
    "__version__",
    "datasets",
    "fit",
    "model",
    "model_kinds",
    "open",
    "property",
    "validate",
]

_SCRIPTING = {"datasets", "fit", "model", "model_kinds", "open", "validate"}


def __getattr__(name: str):
    """The scripting API (``propbench.script``) is imported on first use, so ``import propbench`` stays fast."""
    if name in _SCRIPTING:
        from propbench import script

        return getattr(script, name)
    raise AttributeError(f"module 'propbench' has no attribute {name!r}")


def property(fluid: str, pair: str, values: tuple[float, float], output: str) -> PropertyResult:
    """Compute one property at one state with the default backend (CoolProp HEOS), SI units.

    ``pair`` is a CoolProp input-pair name such as ``"PT_INPUTS"``; ``values`` follow that pair's order.
    """
    return CoolPropBackend().property(fluid, pair, values, output)
