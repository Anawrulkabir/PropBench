"""Publication figures: every format renders, PNG size follows preset and dpi, output is deterministic,
invalid specs are refused."""

import base64
import struct

import pytest

from propbench import figures

SPEC = {
    "preset": "elsevier1",
    "x": {"label": "T / K"},
    "y": {"label": "η / µPa·s"},
    "layers": [
        {
            "type": "points",
            "name": "Tuhin 2024",
            "x": [333, 353, 374],
            "y": [203.7, 167.5, 128.0],
            "err": [4.5, 3.7, 2.8],
        },
        {
            "type": "line",
            "name": "NISTIR 8209, 3 MPa",
            "x": [330, 350, 370, None, 380],
            "y": [210, 170, 132, None, 120],
        },
        {"type": "hline", "y": 150},
        {"type": "band", "range": [140, 160]},
    ],
}


@pytest.mark.parametrize("fmt", ["svg", "pdf", "eps", "png", "tiff"])
def test_formats_render(fmt):
    out = figures.render_base64(SPEC, fmt, 300)
    data = base64.b64decode(out["content_base64"])
    assert len(data) > 1000
    magic = {"svg": b"<?xml", "pdf": b"%PDF", "eps": b"%!PS", "png": b"\x89PNG", "tiff": b"II*\x00"}[fmt]
    assert data.startswith(magic) or (fmt == "tiff" and data[:4] in (b"II*\x00", b"MM\x00*"))


def test_png_size_follows_preset_and_dpi():
    data = figures.render({**SPEC, "preset": "elsevier2"}, "png", 600)
    width, height = struct.unpack(">II", data[16:24])
    assert abs(width - 190 / 25.4 * 600) <= 2  # 190 mm at 600 dpi
    assert abs(height / width - 0.75) < 0.01


def test_vector_output_is_deterministic():
    assert figures.render(SPEC, "svg") == figures.render(SPEC, "svg")
    assert figures.render(SPEC, "pdf") == figures.render(SPEC, "pdf")


def test_histogram_and_qq_layers():
    values = [0.1, -0.3, 0.5, 0.2, -0.1, 0.0, 0.4, -0.2]
    for layer in ({"type": "histogram", "values": values, "bins": 4}, {"type": "qq", "values": values}):
        assert figures.render({"preset": "acs1", "layers": [layer]}, "svg").startswith(b"<?xml")


@pytest.mark.parametrize(
    ("spec", "fmt", "dpi", "match"),
    [
        (SPEC, "bmp", 300, "format"),
        (SPEC, "png", 5000, "2500 dpi"),
        ({**SPEC, "preset": "nature9"}, "svg", 300, "unknown preset"),
        ({"layers": [{"type": "pie"}]}, "svg", 300, "unknown layer"),
    ],
)
def test_invalid_specs(spec, fmt, dpi, match):
    with pytest.raises(figures.FigureError, match=match):
        figures.render(spec, fmt, dpi)
