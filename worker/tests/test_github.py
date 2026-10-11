"""GitHub device flow and push through the Git Data API, against a fake GitHub (no network)."""

import base64
import json

import pytest

from propbench import github

TOKEN = "gho_secret_token"


class FakeGitHub:
    def __init__(self, branch_exists=True):
        self.calls = []
        self.branch_exists = branch_exists

    def __call__(self, method, url, headers, body):
        payload = json.loads(body) if body else None
        self.calls.append((method, url, dict(headers), payload))
        if url.endswith("/login/device/code"):
            return 200, json.dumps(
                {
                    "device_code": "dc",
                    "user_code": "ABCD-1234",
                    "verification_uri": "https://github.com/login/device",
                    "interval": 5,
                }
            ).encode()
        if url.endswith("/login/oauth/access_token"):
            return 200, json.dumps({"access_token": TOKEN}).encode()
        if "/git/ref/heads/" in url:
            return (200, json.dumps({"object": {"sha": "parent123"}}).encode()) if self.branch_exists else (404, b"{}")
        if url.endswith("/git/blobs"):
            return 201, json.dumps({"sha": f"blob{len(self.calls)}"}).encode()
        if url.endswith("/git/trees"):
            return 201, json.dumps({"sha": "tree1"}).encode()
        if url.endswith("/git/commits"):
            return 201, json.dumps({"sha": "commit1"}).encode()
        return 200, b"{}"


def test_device_flow():
    gh = FakeGitHub()
    start = github.device_start("Iv1.abcdef0123456789", transport=gh)
    assert start["user_code"] == "ABCD-1234"
    assert github.device_poll("Iv1.abcdef0123456789", "dc", transport=gh) == {"status": "ok", "token": TOKEN}
    with pytest.raises(github.GitHubError, match="client id"):
        github.device_start("", transport=gh)


def test_push_writes_blobs_tree_commit_and_moves_the_branch():
    gh = FakeGitHub()
    files = github.encode_files({"project.json": b"{}", "datasets/a.csv": b"T,p\n"})
    out = github.push(TOKEN, "lab", "cf3i-project", "main", files, "Update from PropBench", transport=gh)
    assert out["commit"] == "commit1"
    methods = [(m, u.split("/repos/lab/cf3i-project")[-1]) for m, u, _, _ in gh.calls]
    assert methods[0] == ("GET", "/git/ref/heads/main")
    assert [m for m in methods if m[1] == "/git/blobs"] == [("POST", "/git/blobs")] * 2
    commit = next(p for m, u, _, p in gh.calls if u.endswith("/git/commits"))
    assert commit == {"message": "Update from PropBench", "tree": "tree1", "parents": ["parent123"]}
    assert methods[-1] == ("PATCH", "/git/refs/heads/main")
    blob = next(p for m, u, _, p in gh.calls if u.endswith("/git/blobs"))
    assert base64.b64decode(blob["content"]) in (b"{}", b"T,p\n")
    assert all(h.get("authorization") == f"Bearer {TOKEN}" for _, u, h, _ in gh.calls if "/repos/" in u)


def test_push_to_a_new_branch_creates_it():
    gh = FakeGitHub(branch_exists=False)
    github.push(TOKEN, "lab", "repo", "propbench", github.encode_files({"a": b"x"}), "first", transport=gh)
    last = gh.calls[-1]
    assert last[0] == "POST"
    assert last[1].endswith("/git/refs")
    assert last[3]["ref"] == "refs/heads/propbench"


@pytest.mark.parametrize(("owner", "repo", "branch"), [("../x", "r", "main"), ("o", "r r", "main"), ("o", "r", "a..b")])
def test_invalid_names_are_refused(owner, repo, branch):
    with pytest.raises(github.GitHubError, match="invalid"):
        github.push(TOKEN, owner, repo, branch, {}, "m", transport=FakeGitHub())
