"""Publication figures (README §2e Graph studio, CLAUDE.md figure conventions) rendered with matplotlib.

A figure is a JSON spec: one plot per figure, the legend inside the axes, a journal preset for size and fonts,
vector output (SVG, PDF, EPS) or PNG/TIFF up to 2500 dpi. Layers are drawn in order:

* ``points``  x, y, optional ``err`` (symmetric y error bars), marker and colour
* ``line``    x, y (``null`` breaks the line), dashed or solid
* ``band``    a horizontal band ``[low, high]`` (e.g. ±U of a reference)
* ``hline``   a horizontal line at ``y`` (e.g. zero deviation)
* ``histogram`` ``values`` with ``bins``
* ``qq``      normal Q–Q plot of ``values`` (theoretical quantiles computed here)

Rendering is deterministic (fixed metadata, no timestamps) so the same spec gives the same file.
"""

from __future__ import annotations

import base64
import io
import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

# Journal presets: figure width (mm) and base font size (pt); height follows ``aspect`` (height/width).
PRESETS: dict[str, dict[str, Any]] = {
    "elsevier1": {"label": "Elsevier, 1 column (90 mm)", "width_mm": 90.0, "font": 8.0},
    "elsevier15": {"label": "Elsevier, 1.5 columns (140 mm)", "width_mm": 140.0, "font": 9.0},
    "elsevier2": {"label": "Elsevier, 2 columns (190 mm)", "width_mm": 190.0, "font": 9.0},
    "acs1": {"label": "ACS, 1 column (3.25 in)", "width_mm": 82.55, "font": 8.0},
    "acs2": {"label": "ACS, 2 columns (7 in)", "width_mm": 177.8, "font": 9.0},
    "springer1": {"label": "Springer, 1 column (84 mm)", "width_mm": 84.0, "font": 8.0},
    "springer2": {"label": "Springer, 2 columns (174 mm)", "width_mm": 174.0, "font": 9.0},
    "aip1": {"label": "AIP, 1 column (3.37 in)", "width_mm": 85.6, "font": 8.0},
}
FORMATS = {"svg": "image/svg+xml", "pdf": "application/pdf", "eps": "application/postscript", "png": "image/png"}
FORMATS["tiff"] = "image/tiff"
COLORS = ["#1f5fa8", "#b5540a", "#2e7d32", "#7b1fa2", "#c62828", "#00838f", "#5d4037", "#455a64"]
MARKERS = {"square": "s", "triangle": "^", "circle": "o", "diamond": "D", "down": "v", "plus": "P", "cross": "X"}


class FigureError(ValueError):
    """The figure spec is invalid."""


def _arr(values: Sequence[Any] | None) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in (values or [])], dtype=float)


def render(spec: Mapping[str, Any], fmt: str = "svg", dpi: int = 600) -> bytes:
    import matplotlib

    matplotlib.use("Agg")
    from matplotlib import pyplot as plt
    from scipy import stats

    if fmt not in FORMATS:
        raise FigureError(f"format must be one of {sorted(FORMATS)}")
    if not 72 <= int(dpi) <= 2500:
        raise FigureError("resolution must be between 72 and 2500 dpi")
    preset = PRESETS.get(str(spec.get("preset", "elsevier1")))
    if preset is None:
        raise FigureError(f"unknown preset {spec.get('preset')!r} (known: {', '.join(PRESETS)})")
    width_in = preset["width_mm"] / 25.4
    aspect = float(spec.get("aspect", 0.75))
    font = float(spec.get("font_size", preset["font"]))
    rc = {
        "font.size": font,
        "font.family": spec.get("font", "sans-serif"),
        "axes.linewidth": 0.6,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.top": True,
        "ytick.right": True,
        "lines.linewidth": float(spec.get("line_width", 1.0)),
        "legend.frameon": False,
        "svg.hashsalt": "propbench",
        "svg.fonttype": "path",
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
    with matplotlib.rc_context(rc):
        fig, ax = plt.subplots(figsize=(width_in, width_in * aspect), layout="constrained")
        try:
            for i, layer in enumerate(spec.get("layers", [])):
                _draw(ax, layer, i, float(spec.get("marker_size", 4.0)), stats)
            x, y = spec.get("x", {}), spec.get("y", {})
            ax.set_xlabel(str(x.get("label", "")))
            ax.set_ylabel(str(y.get("label", "")))
            if x.get("log"):
                ax.set_xscale("log")
            if y.get("log"):
                ax.set_yscale("log")
            if x.get("range"):
                ax.set_xlim(*map(float, x["range"]))
            if y.get("range"):
                ax.set_ylim(*map(float, y["range"]))
            if spec.get("title"):
                ax.set_title(str(spec["title"]), fontsize=font)
            if spec.get("legend", True) and any(layer.get("name") for layer in spec.get("layers", [])):
                handles, labels = ax.get_legend_handles_labels()
                order = [str(layer["name"]) for layer in spec.get("layers", []) if layer.get("name")]
                pairs = sorted(
                    zip(handles, labels, strict=True), key=lambda hl: order.index(hl[1]) if hl[1] in order else 0
                )
                ax.legend(
                    [h for h, _ in pairs],
                    [lbl for _, lbl in pairs],
                    loc=spec.get("legend_loc", "best"),
                    fontsize=font * 0.85,
                    handlelength=1.6,
                )
            buf = io.BytesIO()
            metadata = {
                "svg": {"Date": None},
                "pdf": {"CreationDate": None, "ModDate": None},
                "eps": {"CreationDate": None},
            }
            fig.savefig(buf, format=fmt, dpi=int(dpi), metadata=metadata.get(fmt), facecolor="white")
        finally:
            plt.close(fig)
    return buf.getvalue()


def _draw(ax: Any, layer: Mapping[str, Any], i: int, marker_size: float, stats: Any) -> None:
    kind = layer.get("type")
    color = layer.get("color") or COLORS[i % len(COLORS)]
    label = layer.get("name") or None
    if kind == "points":
        x, y = _arr(layer.get("x")), _arr(layer.get("y"))
        marker = MARKERS.get(str(layer.get("marker", "")), list(MARKERS.values())[i % len(MARKERS)])
        face = "none" if layer.get("open") else color
        err = layer.get("err")
        if err is not None:
            ax.errorbar(
                x,
                y,
                yerr=_arr(err),
                fmt=marker,
                ms=marker_size,
                mfc=face,
                mec=color,
                ecolor=color,
                elinewidth=0.6,
                capsize=1.5,
                label=label,
                linestyle="none",
            )
        else:
            ax.plot(x, y, marker, ms=marker_size, mfc=face, mec=color, label=label, linestyle="none")
    elif kind == "line":
        ax.plot(
            _arr(layer.get("x")),
            _arr(layer.get("y")),
            color=color,
            label=label,
            linestyle="--" if layer.get("dashed") else "-",
        )
    elif kind == "band":
        lo, hi = (float(v) for v in layer["range"])
        ax.axhspan(lo, hi, color=color, alpha=0.15, lw=0, label=label)
    elif kind == "hline":
        ax.axhline(float(layer.get("y", 0.0)), color=layer.get("color", "#333"), lw=0.6, label=label)
    elif kind == "histogram":
        v = _arr(layer.get("values"))
        ax.hist(
            v[np.isfinite(v)], bins=int(layer.get("bins", 20)), color=color, alpha=0.8, label=label, edgecolor="white"
        )
    elif kind == "qq":
        v = np.sort(_arr(layer.get("values")))
        v = v[np.isfinite(v)]
        q = stats.norm.ppf((np.arange(1, v.size + 1) - 0.5) / v.size)
        ax.plot(q, v, "o", ms=marker_size, mfc="none", mec=color, label=label)
        if v.size > 1:
            slope, intercept = np.polyfit(q, v, 1)
            ax.plot(q, intercept + slope * q, color="#333", lw=0.6)
    else:
        raise FigureError(f"unknown layer type {kind!r}")


def render_base64(spec: Mapping[str, Any], fmt: str = "svg", dpi: int = 600) -> dict[str, Any]:
    data = render(spec, fmt, dpi)
    preset = PRESETS[str(spec.get("preset", "elsevier1"))]
    width_px = math.ceil(preset["width_mm"] / 25.4 * int(dpi))
    return {
        "format": fmt,
        "mime": FORMATS[fmt],
        "content_base64": base64.b64encode(data).decode("ascii"),
        "bytes": len(data),
        "width_px": width_px if fmt in ("png", "tiff") else None,
    }
