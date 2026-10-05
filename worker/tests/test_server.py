import io
import json

import pytest

from propbench.backends import BackendError, PropertyResult
from propbench.worker.server import (
    BACKEND_ERROR,
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    PROTOCOL_VERSION,
    Server,
)

GOOD_PARAMS = {"fluid": "R134a", "pair": "PT_INPUTS", "values": [1.0e6, 300.0], "output": "Dmass"}


def request(params=GOOD_PARAMS, method="property", request_id=1):
    return json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})


def test_property_request():
    response = Server().handle_line(request())
    assert response["id"] == 1
    assert abs(response["result"]["value"] - 1201.53) < 0.005
    assert response["result"]["backend"] == "CoolProp::HEOS"


def test_serve_sends_ready_then_one_line_per_response():
    out = io.StringIO()
    Server().serve(io.StringIO(request(request_id=7) + "\n\n" + request(request_id="b") + "\n"), out)
    lines = out.getvalue().splitlines()
    assert len(lines) == 3
    ready = json.loads(lines[0])
    assert ready["method"] == "ready"
    assert "id" not in ready
    assert ready["params"]["protocol"] == PROTOCOL_VERSION
    assert {"propbench", "python", "coolprop"} <= ready["params"].keys()
    assert [json.loads(line)["id"] for line in lines[1:]] == [7, "b"]


def test_parse_error():
    response = Server().handle_line("{not json")
    assert response["error"]["code"] == PARSE_ERROR
    assert response["id"] is None


@pytest.mark.parametrize(
    "line",
    [
        "[]",
        "42",
        json.dumps({"jsonrpc": "1.0", "id": 1, "method": "property"}),
        json.dumps({"jsonrpc": "2.0", "id": 1}),
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": 5}),
        json.dumps({"jsonrpc": "2.0", "id": [1], "method": "property"}),
        json.dumps({"jsonrpc": "2.0", "id": True, "method": "property"}),
    ],
)
def test_invalid_request(line):
    assert Server().handle_line(line)["error"]["code"] == INVALID_REQUEST


def test_method_not_found():
    response = Server().handle_line(request(method="shutdown"))
    assert response["error"]["code"] == METHOD_NOT_FOUND


@pytest.mark.parametrize(
    "params",
    [
        None,
        [1, 2],
        {k: v for k, v in GOOD_PARAMS.items() if k != "fluid"},
        {**GOOD_PARAMS, "extra": 1},
        {**GOOD_PARAMS, "fluid": ""},
        {**GOOD_PARAMS, "pair": 3},
        {**GOOD_PARAMS, "values": [1.0e6]},
        {**GOOD_PARAMS, "values": [1.0e6, "300"]},
        {**GOOD_PARAMS, "values": [True, 300.0]},
        {**GOOD_PARAMS, "values": "1e6,300"},
    ],
)
def test_invalid_params(params):
    assert Server().handle_line(request(params=params))["error"]["code"] == INVALID_PARAMS


def test_backend_error():
    response = Server().handle_line(request(params={**GOOD_PARAMS, "fluid": "NotAFluid"}))
    assert response["error"]["code"] == BACKEND_ERROR
    assert "NotAFluid" in response["error"]["message"]


def test_notifications_get_no_response():
    line = json.dumps({"jsonrpc": "2.0", "method": "property", "params": GOOD_PARAMS})
    assert Server().handle_line(line) is None


class ExplodingBackend:
    name = "test"

    def property(self, fluid, pair, values, output):
        raise RuntimeError("boom")


class FixedBackend:
    name = "fixed"

    def property(self, fluid, pair, values, output):
        if fluid == "bad":
            raise BackendError("bad fluid")
        return PropertyResult(value=1.5, output=output, backend="fixed", backend_version="1")


def test_unexpected_exception_is_internal_error_and_server_survives():
    server = Server(ExplodingBackend())
    response = server.handle_line(request())
    assert response["error"]["code"] == INTERNAL_ERROR
    assert "boom" in response["error"]["message"]


def test_server_uses_injected_backend():
    server = Server(FixedBackend())
    assert server.handle_line(request())["result"]["value"] == 1.5
    assert server.handle_line(request(params={**GOOD_PARAMS, "fluid": "bad"}))["error"]["code"] == (BACKEND_ERROR)
