"""Newline-delimited JSON-RPC 2.0 server.

Protocol (version 2):

* On start the worker sends one notification ``{"jsonrpc": "2.0", "method": "ready", "params": {...}}`` with the
  protocol, Python, propbench and backend versions.
* Requests are single JSON objects, one per line, UTF-8. Batches are not supported. Params are always an object.
* Methods: ``property(fluid, pair, values, output)`` → ``{value, output, backend, backend_version}`` (since v1), and
  the operations of ``propbench.api`` listed in ``METHODS`` (since v2). SI units; NaN is sent as null.
* Errors: -32602 invalid params, -32001 backend error, -32002 PropBench error (bad data, model, file, fit, ...).
* The worker exits when stdin closes.
"""

import inspect
import json
import platform
import sys
from collections.abc import Callable
from typing import IO, Any

import propbench
from propbench import api
from propbench.backends import Backend, BackendError
from propbench.backends.coolprop import CoolPropBackend
from propbench.fit import FitError

PROTOCOL_VERSION = 2

# RPC method → function of propbench.api (keyword arguments = params)
METHODS: dict[str, Callable[..., dict[str, Any]]] = {
    "fluids": api.fluids,
    "properties": api.properties,
    "dataset.preview": api.dataset_preview,
    "dataset.import": api.dataset_import,
    "dataset.check": api.dataset_check,
    "model.kinds": api.model_kinds,
    "model.default": api.model_default,
    "model.predict": api.model_predict,
    "model.fit": api.model_fit,
    "study.validate": api.study_validate,
    "selection.lock": api.selection_lock,
    "selection.select": api.selection_select,
    "consistency.analyze": api.consistency_analyze,
    "model.references": api.model_references,
    "model.compare": api.model_compare,
    "components.list": api.components_list,
    "components.install": api.components_install,
    "components.install_file": api.components_install_file,
    "components.remove": api.components_remove,
    "components.datasets": api.components_datasets,
    "env.status": api.env_status,
    "env.create": api.env_create,
    "env.install": api.env_install,
    "env.sync": api.env_sync,
    "env.run": api.env_run,
    "worksheet.compute": api.worksheet_compute,
    "curvefit.fit": api.curvefit_fit,
    "curvefit.ftest": api.curvefit_ftest,
    "gum.linear": api.gum_linear,
    "gum.montecarlo": api.gum_montecarlo,
    "refs.parse": api.refs_parse,
    "refs.format": api.refs_format,
    "refs.doi": api.refs_doi,
    "figure.render": api.figure_render,
    "figure.presets": api.figure_presets,
    "report.render": api.report_render,
    "model.export_coolprop": api.model_export_coolprop,
}

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
BACKEND_ERROR = -32001
PROPBENCH_ERROR = -32002


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Server:
    def __init__(self, backend: Backend | None = None) -> None:
        self.backend: Backend = backend if backend is not None else CoolPropBackend()
        self.methods: dict[str, Callable[[Any], dict[str, Any]]] = {"property": self._property}
        for name, function in METHODS.items():
            self.methods[name] = _api_method(function)

    def ready_params(self) -> dict[str, Any]:
        import CoolProp

        return {
            "protocol": PROTOCOL_VERSION,
            "propbench": propbench.__version__,
            "python": platform.python_version(),
            "coolprop": CoolProp.__version__,
        }

    def serve(self, instream: IO[str], outstream: IO[str]) -> None:
        """Answer requests from ``instream`` until it closes."""
        _write(outstream, {"jsonrpc": "2.0", "method": "ready", "params": self.ready_params()})
        for line in instream:
            if not line.strip():
                continue
            response = self.handle_line(line)
            if response is not None:
                _write(outstream, response)

    def handle_line(self, line: str) -> dict[str, Any] | None:
        """Return the response for one request line, or ``None`` for a notification."""
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            return _error(None, PARSE_ERROR, f"parse error: {exc}")
        if not isinstance(message, dict):
            return _error(None, INVALID_REQUEST, "request must be a JSON object")
        request_id = message.get("id")
        is_notification = "id" not in message
        if not _valid_id(request_id):
            return _error(None, INVALID_REQUEST, "id must be a string, an integer or null")
        try:
            if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
                raise RpcError(INVALID_REQUEST, "invalid JSON-RPC 2.0 request")
            method = self.methods.get(message["method"])
            if method is None:
                raise RpcError(METHOD_NOT_FOUND, f"method not found: {message['method']}")
            result = method(message.get("params"))
        except RpcError as exc:
            return None if is_notification else _error(request_id, exc.code, exc.message)
        except Exception as exc:  # keep the worker alive; report instead of crashing
            if is_notification:
                return None
            return _error(request_id, INTERNAL_ERROR, f"{type(exc).__name__}: {exc}")
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "result": result}

    def _property(self, params: Any) -> dict[str, Any]:
        if not isinstance(params, dict):
            raise RpcError(INVALID_PARAMS, "params must be an object")
        expected = {"fluid", "pair", "values", "output"}
        missing = expected - params.keys()
        unknown = params.keys() - expected
        if missing or unknown:
            raise RpcError(
                INVALID_PARAMS,
                f"missing params: {sorted(missing)}; unknown params: {sorted(unknown)}",
            )
        fluid, pair, values, output = (params[k] for k in ("fluid", "pair", "values", "output"))
        for name, value in (("fluid", fluid), ("pair", pair), ("output", output)):
            if not isinstance(value, str) or not value:
                raise RpcError(INVALID_PARAMS, f"'{name}' must be a non-empty string")
        if (
            not isinstance(values, list)
            or len(values) != 2
            or not all(isinstance(v, int | float) and not isinstance(v, bool) for v in values)
        ):
            raise RpcError(INVALID_PARAMS, "'values' must be a list of two numbers")
        try:
            result = self.backend.property(fluid, pair, (values[0], values[1]), output)
        except BackendError as exc:
            raise RpcError(BACKEND_ERROR, str(exc)) from exc
        return {
            "value": result.value,
            "output": result.output,
            "backend": result.backend,
            "backend_version": result.backend_version,
        }


def _api_method(function: Callable[..., dict[str, Any]]) -> Callable[[Any], dict[str, Any]]:
    signature = inspect.signature(function)

    def call(params: Any) -> dict[str, Any]:
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise RpcError(INVALID_PARAMS, "params must be an object")
        try:
            signature.bind(**params)
        except TypeError as exc:
            raise RpcError(INVALID_PARAMS, str(exc)) from exc
        try:
            return function(**params)
        except BackendError as exc:
            raise RpcError(BACKEND_ERROR, str(exc)) from exc
        except (ValueError, FitError, OSError, KeyError, RuntimeError) as exc:
            # every PropBench domain error is a ValueError (DatasetError, ModelError, MappingError, ...)
            raise RpcError(PROPBENCH_ERROR, str(exc)) from exc

    return call


def _valid_id(request_id: Any) -> bool:
    return (
        request_id is None
        or isinstance(request_id, str)
        or (isinstance(request_id, int) and not isinstance(request_id, bool))
    )


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def _write(outstream: IO[str], message: dict[str, Any]) -> None:
    outstream.write(json.dumps(message, allow_nan=False, separators=(",", ":")) + "\n")
    outstream.flush()


def main() -> int:
    """Run the worker on the process's stdin/stdout.

    The protocol gets a private duplicate of stdout; file descriptor 1 is then pointed at stderr, so that anything a
    library prints (from Python or C/C++) goes to the log and cannot corrupt the protocol stream.
    """
    import os

    sys.stdout.flush()
    protocol_out = os.fdopen(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    instream = open(sys.stdin.fileno(), encoding="utf-8", newline="\n", closefd=False)  # noqa: SIM115
    from propbench import components

    components.activate_python()  # pure-Python components installed in the app data folder
    Server().serve(instream, protocol_out)
    return 0
