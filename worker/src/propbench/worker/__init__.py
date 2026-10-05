"""The PropBench worker process: JSON-RPC 2.0 over stdio, one JSON message per line (README §4b)."""

from propbench.worker.server import PROTOCOL_VERSION, Server

__all__ = ["PROTOCOL_VERSION", "Server"]
