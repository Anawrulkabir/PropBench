"""Runs the real worker process exactly as pb-engine starts it."""

import json
import subprocess
import sys

WORKER_ARGS = [sys.executable, "-I", "-B", "-X", "utf8", "-m", "propbench.worker"]


def run_worker(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(WORKER_ARGS, input=stdin, capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_worker_answers_acceptance_request_and_exits_on_eof():
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "property",
        "params": {"fluid": "R134a", "pair": "PT_INPUTS", "values": [1.0e6, 300.0], "output": "Dmass"},
    }
    proc = run_worker(json.dumps(req) + "\n")
    assert proc.returncode == 0, proc.stderr
    ready, response = (json.loads(line) for line in proc.stdout.splitlines())
    assert ready["method"] == "ready"
    assert response["id"] == 1
    assert abs(response["result"]["value"] - 1201.53) < 0.005


def test_library_prints_go_to_stderr_not_protocol():
    # Anything printed to fd 1 after start-up must not reach the protocol stream.
    code = (
        "import os, sys, io\n"
        "from propbench.worker import server\n"
        "class S(server.Server):\n"
        "    def ready_params(self):\n"
        "        print('stray python print')\n"
        "        os.write(1, b'stray fd print\\n')\n"
        "        return super().ready_params()\n"
        "server.Server = S\n"
        "sys.exit(server.main())\n"
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-B", "-c", code], input="", capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    assert [json.loads(line)["method"] for line in proc.stdout.splitlines()] == ["ready"]
    assert "stray python print" in proc.stderr
    assert "stray fd print" in proc.stderr
