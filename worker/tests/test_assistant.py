"""AI assistant: requests per provider, the key never leaves the request, proposals are data only, offline."""

import json

import pytest

from propbench import assistant

KEY = "sk-test-secret-key"


def fake(reply):
    calls = []

    def transport(url, headers, body):
        calls.append((url, dict(headers), json.loads(body)))
        return json.dumps(reply).encode()

    return transport, calls


REPLY_TEXT = (
    "Fit both datasets with a shared ψ.\n"
    '```python propbench-script title="Global ECS fit"\nimport propbench as pb\ndata = pb.datasets()\n```\n'
    '```json propbench-plot\n{"xLabel": "T / K", "logY": true}\n```\n'
)


@pytest.mark.parametrize(
    ("provider", "reply", "url_end", "key_header"),
    [
        ("openai", {"choices": [{"message": {"content": REPLY_TEXT}}]}, "/chat/completions", "authorization"),
        ("groq", {"choices": [{"message": {"content": REPLY_TEXT}}]}, "/chat/completions", "authorization"),
        ("anthropic", {"content": [{"type": "text", "text": REPLY_TEXT}]}, "/messages", "x-api-key"),
        (
            "gemini",
            {"candidates": [{"content": {"parts": [{"text": REPLY_TEXT}]}}]},
            ":generateContent",
            "x-goog-api-key",
        ),
    ],
)
def test_providers_and_proposals(provider, reply, url_end, key_header):
    transport, calls = fake(reply)
    out = assistant.ask(
        provider,
        "model-x",
        [{"role": "user", "content": "How do I fit?"}],
        KEY,
        context="2 datasets of R13I1 viscosity",
        transport=transport,
    )
    url, headers, body = calls[0]
    assert url.endswith(url_end)
    assert url.startswith("https://")
    assert KEY in headers[key_header]
    assert "2 datasets of R13I1" in json.dumps(body), "the context shown to the user is what is sent"
    assert KEY not in json.dumps(out), "the key is never returned"
    kinds = [(p["kind"], p["title"]) for p in out["proposals"]]
    assert kinds == [("script", "Global ECS fit"), ("plot", "plot")]
    assert out["proposals"][1]["value"] == {"xLabel": "T / K", "logY": True}
    assert out["provenance"]["provider"] == provider
    assert out["provenance"]["model"] == "model-x"
    assert "How do I fit?" in out["provenance"]["prompt"]


def test_local_servers_need_no_key_and_remote_ones_need_https():
    transport, calls = fake({"choices": [{"message": {"content": "hi"}}]})
    out = assistant.ask("ollama", "llama3", [{"role": "user", "content": "hi"}], None, transport=transport)
    assert out["text"] == "hi"
    assert "authorization" not in calls[0][1]
    with pytest.raises(assistant.AssistantError, match="no API key"):
        assistant.ask("openai", "m", [{"role": "user", "content": "x"}], None, transport=transport)
    with pytest.raises(assistant.AssistantError, match="https"):
        assistant.ask(
            "openai",
            "m",
            [{"role": "user", "content": "x"}],
            KEY,
            base_url="http://evil.example/v1",
            transport=transport,
        )
    with pytest.raises(assistant.AssistantError, match="unknown provider"):
        assistant.ask("nope", "m", [], KEY, transport=transport)


def test_errors_never_show_the_key():
    def failing(url, headers, body):
        raise OSError(f"connection refused for {headers.get('authorization')}")

    with pytest.raises(assistant.AssistantError) as err:
        assistant.ask("openai", "m", [{"role": "user", "content": "x"}], KEY, transport=failing)
    assert KEY not in str(err.value)


def test_invalid_json_proposal_is_flagged_not_applied():
    out = assistant.proposals("```json propbench-mapping\n{not json\n```")
    assert out[0]["invalid"]
    assert "value" not in out[0]
