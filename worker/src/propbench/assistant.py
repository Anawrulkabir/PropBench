"""AI assistant (README §4d): bring your own key; one OpenAI-compatible connector (OpenAI, Groq, OpenRouter,
Together, Ollama, LM Studio) plus Anthropic and Gemini.

The assistant only talks: ``ask`` returns the reply text and the changes it proposes (scripts, plot settings,
column mappings) as data. Nothing here executes code or changes the project; the app shows each proposal and
applies it only after the user confirms (CLAUDE.md AI rules). Every reply carries its provenance (prompt,
provider, model, time) to be stored with whatever the user accepts. The API key is passed in by the shell from the
OS keychain for this one request and is never returned, stored or logged.
"""

from __future__ import annotations

import json
import re
import time
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

PROVIDERS = {
    "openai": {"label": "OpenAI-compatible", "base_url": "https://api.openai.com/v1"},
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1"},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1"},
    "together": {"label": "Together", "base_url": "https://api.together.xyz/v1"},
    "ollama": {"label": "Ollama (local)", "base_url": "http://localhost:11434/v1", "local": True},
    "lmstudio": {"label": "LM Studio (local)", "base_url": "http://localhost:1234/v1", "local": True},
    "anthropic": {"label": "Anthropic", "base_url": "https://api.anthropic.com/v1"},
    "gemini": {"label": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta"},
}

SYSTEM = (
    "You help a researcher who develops thermophysical property models in PropBench. Answer briefly. "
    'When you propose a change, put it in a fenced block: ```python propbench-script title="..."``` for a '
    "script that uses `import propbench as pb`, or ```json propbench-plot``` for graph settings, or "
    "```json propbench-mapping``` for an import column mapping. Never claim to have run or applied anything: "
    "the user reviews and applies proposals."
)

Transport = Callable[[str, Mapping[str, str], bytes], bytes]


class AssistantError(ValueError):
    """The provider is unknown, the request failed or the reply could not be read."""


def _post(url: str, headers: Mapping[str, str], body: bytes) -> bytes:
    req = urllib.request.Request(url, data=body, headers=dict(headers), method="POST")
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.read()


def build_request(
    provider: str, model: str, messages: Sequence[Mapping[str, str]], api_key: str | None, base_url: str | None = None
) -> tuple[str, dict[str, str], dict[str, Any]]:
    """URL, headers and JSON body of a chat request (the system prompt first)."""
    info = PROVIDERS.get(provider)
    if info is None:
        raise AssistantError(f"unknown provider {provider!r} (known: {', '.join(PROVIDERS)})")
    base = (base_url or info["base_url"]).rstrip("/")
    if not base.startswith(("https://", "http://localhost", "http://127.0.0.1")):
        raise AssistantError("the provider URL must use https (plain http only for a local server)")
    if not api_key and not info.get("local"):
        raise AssistantError(f"no API key for {info['label']}: add one in Settings › AI assistant")
    msgs = [{"role": m["role"], "content": m["content"]} for m in messages if m.get("role") in ("user", "assistant")]
    if provider == "anthropic":
        headers = {"content-type": "application/json", "x-api-key": api_key or "", "anthropic-version": "2023-06-01"}
        return f"{base}/messages", headers, {"model": model, "max_tokens": 2048, "system": SYSTEM, "messages": msgs}
    if provider == "gemini":
        contents = [
            {"role": "model" if m["role"] == "assistant" else "user", "parts": [{"text": m["content"]}]} for m in msgs
        ]
        headers = {"content-type": "application/json", "x-goog-api-key": api_key or ""}
        body = {"systemInstruction": {"parts": [{"text": SYSTEM}]}, "contents": contents}
        return f"{base}/models/{model}:generateContent", headers, body
    headers = {"content-type": "application/json"}
    if api_key:
        headers["authorization"] = f"Bearer {api_key}"
    return (
        f"{base}/chat/completions",
        headers,
        {"model": model, "messages": [{"role": "system", "content": SYSTEM}, *msgs]},
    )


def _reply_text(provider: str, data: Mapping[str, Any]) -> str:
    try:
        if provider == "anthropic":
            return "".join(part.get("text", "") for part in data["content"] if part.get("type") == "text")
        if provider == "gemini":
            return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"])
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as exc:
        raise AssistantError(f"unexpected reply from {provider}: {str(data)[:200]}") from exc


_BLOCK = re.compile(r"```(\w+)[ \t]+propbench-(script|plot|mapping)([^\n]*)\n(.*?)```", re.S)


def proposals(text: str) -> list[dict[str, Any]]:
    """Changes proposed in a reply (data only; the app previews them and applies them on confirmation)."""
    out = []
    for i, m in enumerate(_BLOCK.finditer(text)):
        lang, kind, attrs, body = m.groups()
        title = re.search(r'title="([^"]*)"', attrs)
        item: dict[str, Any] = {
            "id": i,
            "kind": kind,
            "title": title.group(1) if title else kind,
            "content": body.rstrip(),
        }
        if lang == "json":
            try:
                item["value"] = json.loads(body)
            except json.JSONDecodeError:
                item["invalid"] = "the proposed JSON could not be read"
        out.append(item)
    return out


def ask(
    provider: str,
    model: str,
    messages: Sequence[Mapping[str, str]],
    api_key: str | None = None,
    base_url: str | None = None,
    context: str = "",
    transport: Transport = _post,
) -> dict[str, Any]:
    """Send the conversation (with ``context``, exactly as shown to the user, prepended to the last message)."""
    msgs = [dict(m) for m in messages]
    if context and msgs and msgs[-1].get("role") == "user":
        msgs[-1]["content"] = f"Project context:\n{context}\n\nQuestion:\n{msgs[-1]['content']}"
    url, headers, body = build_request(provider, model, msgs, api_key, base_url)
    try:
        raw = transport(url, headers, json.dumps(body).encode("utf-8"))
        data = json.loads(raw)
    except (OSError, ValueError) as exc:
        message = str(exc).replace(api_key, "***") if api_key else str(exc)
        raise AssistantError(f"{PROVIDERS[provider]['label']} did not answer: {message}") from None
    text = _reply_text(provider, data)
    return {
        "text": text,
        "proposals": proposals(text),
        "provenance": {
            "provider": provider,
            "model": model,
            "base_url": url.split("?")[0],
            "prompt": msgs[-1]["content"] if msgs else "",
            "time": int(time.time()),
        },
    }
