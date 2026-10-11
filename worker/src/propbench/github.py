"""GitHub (README §4d): device-flow sign-in and pushing a project mirror to a repository.

Sign-in uses GitHub's OAuth device flow (the user enters a code on github.com; PropBench never sees a password).
It needs the client id of a GitHub OAuth app registered for PropBench, given in the settings. The token is handed
to the shell, which stores it in the OS keychain; it is passed back here only for the request that needs it and
is never returned, stored or logged.

``push`` writes the mirror's files as one commit on a branch with the Git Data API (blobs → tree → commit →
ref), so the repository holds exactly the mirror's files after each push.
"""

from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

API = "https://api.github.com"
Transport = Callable[[str, str, Mapping[str, str], bytes | None], tuple[int, bytes]]


class GitHubError(ValueError):
    """Sign-in or a push failed, or the request is invalid."""


def _http(method: str, url: str, headers: Mapping[str, str], body: bytes | None) -> tuple[int, bytes]:
    req = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def _json(transport: Transport, method: str, url: str, token: str | None, payload: Any = None) -> tuple[int, Any]:
    headers = {"accept": "application/json", "user-agent": "PropBench"}
    if token:
        headers["authorization"] = f"Bearer {token}"
    body = None
    if payload is not None:
        headers["content-type"] = "application/json"
        body = json.dumps(payload).encode("utf-8")
    try:
        status, raw = transport(method, url, headers, body)
    except OSError as exc:
        raise GitHubError(f"GitHub did not answer: {exc}") from None
    try:
        return status, json.loads(raw or b"null")
    except json.JSONDecodeError:
        return status, None


def device_start(client_id: str, transport: Transport = _http) -> dict[str, Any]:
    """Start the device flow: the user opens ``verification_uri`` and enters ``user_code``."""
    if not re.fullmatch(r"[A-Za-z0-9._-]{8,64}", client_id or ""):
        raise GitHubError("set the client id of PropBench's GitHub OAuth app in Settings › GitHub")
    status, data = _json(
        transport, "POST", "https://github.com/login/device/code", None, {"client_id": client_id, "scope": "repo"}
    )
    if status != 200 or not isinstance(data, dict) or "device_code" not in data:
        raise GitHubError(f"GitHub refused the sign-in request ({status})")
    return {k: data[k] for k in ("device_code", "user_code", "verification_uri", "expires_in", "interval") if k in data}


def device_poll(client_id: str, device_code: str, transport: Transport = _http) -> dict[str, Any]:
    """One poll: {"status": "pending" | "slow_down" | "ok", "token"?} (the token goes to the keychain only)."""
    payload = {
        "client_id": client_id,
        "device_code": device_code,
        "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    }
    _, data = _json(transport, "POST", "https://github.com/login/oauth/access_token", None, payload)
    if isinstance(data, dict) and data.get("access_token"):
        return {"status": "ok", "token": data["access_token"]}
    error = (data or {}).get("error", "unknown") if isinstance(data, dict) else "unknown"
    if error in ("authorization_pending", "slow_down"):
        return {"status": "pending" if error == "authorization_pending" else "slow_down"}
    raise GitHubError(f"sign-in failed: {error}")


def push(
    token: str,
    owner: str,
    repo: str,
    branch: str,
    files: Mapping[str, str],
    message: str,
    transport: Transport = _http,
) -> dict[str, Any]:
    """Commit ``files`` (path → base64 content) as the full content of ``branch`` and move the branch to it."""
    for name, value in (("owner", owner), ("repository", repo), ("branch", branch)):
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", value or "") or ".." in value:
            raise GitHubError(f"invalid {name} {value!r}")
    if not token:
        raise GitHubError("sign in to GitHub first (Settings › GitHub)")
    base = f"{API}/repos/{owner}/{repo}"
    status, ref = _json(transport, "GET", f"{base}/git/ref/heads/{urllib.parse.quote(branch)}", token)
    parents = [ref["object"]["sha"]] if status == 200 else []
    if status not in (200, 404, 409):
        raise GitHubError(f"cannot read {owner}/{repo} ({status}): check the name and your access")
    tree = []
    for path in sorted(files):
        status, blob = _json(
            transport, "POST", f"{base}/git/blobs", token, {"content": files[path], "encoding": "base64"}
        )
        if status != 201:
            raise GitHubError(f"upload of {path} failed ({status})")
        tree.append({"path": path, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    status, t = _json(transport, "POST", f"{base}/git/trees", token, {"tree": tree})
    if status != 201:
        raise GitHubError(f"creating the tree failed ({status})")
    status, commit = _json(
        transport, "POST", f"{base}/git/commits", token, {"message": message, "tree": t["sha"], "parents": parents}
    )
    if status != 201:
        raise GitHubError(f"creating the commit failed ({status})")
    if parents:
        status, _ = _json(transport, "PATCH", f"{base}/git/refs/heads/{branch}", token, {"sha": commit["sha"]})
    else:
        status, _ = _json(
            transport, "POST", f"{base}/git/refs", token, {"ref": f"refs/heads/{branch}", "sha": commit["sha"]}
        )
    if status not in (200, 201):
        raise GitHubError(f"moving {branch} failed ({status})")
    return {
        "commit": commit["sha"],
        "url": f"https://github.com/{owner}/{repo}/commit/{commit['sha']}",
        "files": len(tree),
    }


def encode_files(files: Mapping[str, bytes]) -> dict[str, str]:
    return {k: base64.b64encode(v).decode("ascii") for k, v in files.items()}
