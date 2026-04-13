"""Tests for adapters._transport and CLI-transport adapter paths.

Subprocess is mocked — tests never invoke the real `claude` CLI.
"""

from __future__ import annotations

import subprocess

import pytest


# ---------------------------------------------------------------------------
# default_transport() selection
# ---------------------------------------------------------------------------

def test_default_transport_explicit_env_cli(monkeypatch) -> None:
    from adapters import _transport

    monkeypatch.setenv("BENCH_TRANSPORT", "cli")
    monkeypatch.setattr(_transport, "has_claude_cli", lambda b="claude": False)
    # env wins even when CLI isn't installed — caller's responsibility to ensure it
    assert _transport.default_transport() == "cli"


def test_default_transport_explicit_env_api(monkeypatch) -> None:
    from adapters import _transport

    monkeypatch.setenv("BENCH_TRANSPORT", "api")
    monkeypatch.setattr(_transport, "has_claude_cli", lambda b="claude": True)
    assert _transport.default_transport() == "api"


def test_default_transport_rejects_unknown_env(monkeypatch) -> None:
    from adapters import _transport

    monkeypatch.setenv("BENCH_TRANSPORT", "curl")
    with pytest.raises(ValueError, match="BENCH_TRANSPORT"):
        _transport.default_transport()


def test_default_transport_auto_cli_when_installed(monkeypatch) -> None:
    from adapters import _transport

    monkeypatch.delenv("BENCH_TRANSPORT", raising=False)
    monkeypatch.setattr(_transport, "has_claude_cli", lambda b="claude": True)
    assert _transport.default_transport() == "cli"


def test_default_transport_auto_api_when_no_cli(monkeypatch) -> None:
    from adapters import _transport

    monkeypatch.delenv("BENCH_TRANSPORT", raising=False)
    monkeypatch.setattr(_transport, "has_claude_cli", lambda b="claude": False)
    assert _transport.default_transport() == "api"


# ---------------------------------------------------------------------------
# generate_via_cli — subprocess is mocked
# ---------------------------------------------------------------------------

def test_generate_via_cli_builds_expected_args(monkeypatch) -> None:
    from adapters import _transport

    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(
            args=args, returncode=0,
            stdout="1. alpha\n2. beta\n",
            stderr="",
        )

    monkeypatch.setattr(_transport, "has_claude_cli", lambda b="claude": True)
    monkeypatch.setattr(_transport.subprocess, "run", fake_run)

    raw, meta = _transport.generate_via_cli(
        system_prompt="SYS",
        user_prompt="USR",
        model="claude-opus-4-6",
    )
    assert raw == "1. alpha\n2. beta\n"
    assert meta["transport"] == "claude_cli"
    assert meta["model"] == "claude-opus-4-6"

    # Verify the CLI invocation shape.
    args = captured["args"]
    assert args[:2] == ["claude", "-p"]
    assert "--model" in args and args[args.index("--model") + 1] == "claude-opus-4-6"
    assert "--system-prompt" in args and args[args.index("--system-prompt") + 1] == "SYS"
    assert "--tools" in args and args[args.index("--tools") + 1] == ""
    assert "--bare" in args
    # user prompt is the final positional
    assert args[-1] == "USR"


def test_generate_via_cli_with_json_schema(monkeypatch) -> None:
    from adapters import _transport

    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        return subprocess.CompletedProcess(
            args=args, returncode=0,
            stdout='{"winner": "A"}', stderr="",
        )

    monkeypatch.setattr(_transport, "has_claude_cli", lambda b="claude": True)
    monkeypatch.setattr(_transport.subprocess, "run", fake_run)

    raw, meta = _transport.generate_via_cli(
        system_prompt="rubric",
        user_prompt="judge me",
        model="claude-sonnet-4-6",
        json_schema='{"type":"object"}',
        effort="medium",
    )
    assert raw == '{"winner": "A"}'
    args = captured["args"]
    assert "--json-schema" in args
    assert args[args.index("--json-schema") + 1] == '{"type":"object"}'
    assert "--effort" in args
    assert args[args.index("--effort") + 1] == "medium"


def test_generate_via_cli_missing_binary_errors(monkeypatch) -> None:
    from adapters import _transport

    monkeypatch.setattr(_transport, "has_claude_cli", lambda b="claude": False)
    with pytest.raises(FileNotFoundError, match="claude"):
        _transport.generate_via_cli("s", "u")


def test_generate_via_cli_nonzero_return_raises(monkeypatch) -> None:
    from adapters import _transport

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=2, stdout="", stderr="auth failed",
        )

    monkeypatch.setattr(_transport, "has_claude_cli", lambda b="claude": True)
    monkeypatch.setattr(_transport.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="rc=2"):
        _transport.generate_via_cli("s", "u")


# ---------------------------------------------------------------------------
# parse_via_cli — strips markdown fences and validates with Pydantic
# ---------------------------------------------------------------------------

def test_parse_via_cli_strips_markdown_fences(monkeypatch) -> None:
    from pydantic import BaseModel

    from adapters import _transport

    class Verdict(BaseModel):
        winner: str

    def fake_run(args, **kwargs):
        # claude sometimes wraps JSON in ```json fences; parse_via_cli must strip them
        return subprocess.CompletedProcess(
            args=args, returncode=0,
            stdout='```json\n{"winner": "A"}\n```\n',
            stderr="",
        )

    monkeypatch.setattr(_transport, "has_claude_cli", lambda b="claude": True)
    monkeypatch.setattr(_transport.subprocess, "run", fake_run)

    parsed, _meta = _transport.parse_via_cli(
        system_prompt="rubric",
        user_prompt="judge me",
        output_format=Verdict,
        model="claude-sonnet-4-6",
    )
    assert parsed.winner == "A"


def test_parse_via_cli_rejects_non_json(monkeypatch) -> None:
    from pydantic import BaseModel

    from adapters import _transport

    class Verdict(BaseModel):
        winner: str

    def fake_run(args, **kwargs):
        return subprocess.CompletedProcess(
            args=args, returncode=0,
            stdout="I would rather not say.",
            stderr="",
        )

    monkeypatch.setattr(_transport, "has_claude_cli", lambda b="claude": True)
    monkeypatch.setattr(_transport.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="non-JSON"):
        _transport.parse_via_cli(
            system_prompt="rubric",
            user_prompt="judge me",
            output_format=Verdict,
            model="claude-sonnet-4-6",
        )


# ---------------------------------------------------------------------------
# PlainClaudeAdapter end-to-end through CLI transport
# ---------------------------------------------------------------------------

def test_plain_claude_adapter_via_cli(monkeypatch) -> None:
    from adapters import _transport
    from adapters.plain_claude import PlainClaudeAdapter

    def fake_run(args, **kwargs):
        # sanity: the adapter passes the built-in system prompt
        assert "--system-prompt" in args
        sys_idx = args.index("--system-prompt") + 1
        assert "brainstorming partner" in args[sys_idx].lower()
        # user prompt is the final arg and contains the problem
        assert "Amazon" in args[-1]
        return subprocess.CompletedProcess(
            args=args, returncode=0,
            stdout="1. Sell coffee\n2. Host events\n3. Book club subscriptions\n",
            stderr="",
        )

    monkeypatch.setattr(_transport, "has_claude_cli", lambda b="claude": True)
    monkeypatch.setattr(_transport.subprocess, "run", fake_run)

    ad = PlainClaudeAdapter(transport="cli")
    resp = ad.generate("How might a small indie bookstore compete with Amazon?")
    assert len(resp.ideas) == 3
    assert resp.ideas[0].text == "Sell coffee"
    assert resp.meta["transport"] == "claude_cli"
