"""Newline-delimited JSON-RPC 2.0 server.

Protocol (version 1):

* On start the worker sends one notification ``{"jsonrpc": "2.0", "method": "ready", "params": {...}}`` with the
  protocol, Python, propbench and backend versions.
* Requests are single JSON objects, one per line, UTF-8. Batches are not supported.
* Methods: ``property(fluid, pair, values, output)`` → ``{value, output, backend, backend_version}``. SI units.
* The worker exits when stdin closes.
"""

import json
import platform
import sys
from collections.abc import Callable
from typing import IO, Any

import propbench
from propbench.backends import Backend, BackendError
from propbench.backends.coolprop import CoolPropBackend

PROTOCOL_VERSION = 1

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
BACKEND_ERROR = -32001


class RpcError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class Server:
    def __init__(self, backend: Backend | None = None) -> None:
        self.backend: Backend = backend if backend is not None else CoolPropBackend()
        self.methods: dict[str, Callable[[Any], dict[str, Any]]] = {"property": self._property}

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
    Server().serve(instream, protocol_out)
    return 0
