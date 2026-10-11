"""The template plug-in passes the check-value harness (README M4c acceptance)."""

from pathlib import Path

from propbench import plugins

HERE = Path(__file__).resolve().parent.parent


def test_template_reproduces_its_published_check_values():
    report = plugins.check(HERE)
    assert report["verified"], report["results"]
    assert len(report["results"]) == 3


def test_parameters_can_be_changed():
    model = plugins.model_of(plugins.load_module(HERE, "plugin.py"))
    assert abs(model.predict(273.15, 0.0)[0] - 1.716e-5) < 1e-18
    assert (
        model.with_params({"S": 120.0}).predict(300.0, 0.0)[0]
        != model.predict(300.0, 0.0)[0]
    )
