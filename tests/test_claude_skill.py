"""Tests for the generic ClaudeSkillAdapter and `/slash-command` spec parsing.

Subprocesses are faked — tests never actually invoke `claude`.
"""

from __future__ import annotations

import subprocess

import pytest


def test_requires_problem_placeholder() -> None:
    from adapters.claude_skill import ClaudeSkillAdapter

    with pytest.raises(ValueError, match=r"\{problem\}"):
        ClaudeSkillAdapter(
            command_template="/some-plugin:ideas",
            tag="x",
            require_binary=False,
        )


def test_sanitize_tag() -> None:
    from adapters.claude_skill import ClaudeSkillAdapter

    ad = ClaudeSkillAdapter(
        command_template="/my-plugin:brainstorm {problem}",
        tag="my plugin :v1.0",
        require_binary=False,
    )
    # spaces, colon, etc. should collapse to dashes, leaderboard-safe
    assert ad.name.startswith("claude_skill[")
    assert ":" not in ad.name.split("[", 1)[1].split("]", 1)[0]
    assert " " not in ad.name


def test_generate_captures_subprocess_output(monkeypatch) -> None:
    from adapters.claude_skill import ClaudeSkillAdapter

    captured: dict = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        # Return a CompletedProcess mimic
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=0,
            stdout="1. alpha\n2. beta\n3. gamma\n",
            stderr="",
        )

    monkeypatch.setattr("adapters.claude_skill.subprocess.run", fake_run)

    ad = ClaudeSkillAdapter(
        command_template="/my:plugin {problem}",
        tag="my-plugin",
        require_binary=False,
    )
    resp = ad.generate("How to compete with Amazon?")

    assert captured["cmd"][0] == "claude"
    assert captured["cmd"][1] == "-p"
    # problem text was substituted into the template
    assert captured["cmd"][2] == "/my:plugin How to compete with Amazon?"
    assert len(resp.ideas) == 3
    assert resp.ideas[0].text == "alpha"
    assert resp.meta["transport"] == "claude_cli"
    assert resp.meta["command_template"] == "/my:plugin {problem}"
    assert resp.meta["returncode"] == 0


def test_generate_records_stderr_tail(monkeypatch) -> None:
    from adapters.claude_skill import ClaudeSkillAdapter

    def fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(
            args=cmd,
            returncode=1,
            stdout="",
            stderr="x" * 1000,
        )

    monkeypatch.setattr("adapters.claude_skill.subprocess.run", fake_run)

    ad = ClaudeSkillAdapter(
        command_template="/bad {problem}",
        tag="bad",
        require_binary=False,
    )
    resp = ad.generate("p")
    # stderr is truncated to a 500-char tail
    assert len(resp.meta["stderr_tail"]) == 500
    assert resp.meta["returncode"] == 1


# ---------------------------------------------------------------------------
# CLI adapter-spec parsing (_build_adapter)
# ---------------------------------------------------------------------------

def test_build_adapter_slash_command_spec(monkeypatch) -> None:
    # bypass the binary check and capture construction
    import adapters.claude_skill as cs

    monkeypatch.setattr(cs.shutil, "which", lambda _: "/fake/claude")

    from cli import _build_adapter

    ad = _build_adapter("/brainstorm-kit:brainstorm")
    assert ad.name.startswith("claude_skill[")
    # {problem} is added automatically when absent
    assert "{problem}" in ad._template


def test_build_adapter_slash_command_with_placeholder(monkeypatch) -> None:
    import adapters.claude_skill as cs

    monkeypatch.setattr(cs.shutil, "which", lambda _: "/fake/claude")

    from cli import _build_adapter

    ad = _build_adapter("/my-plugin:ideas {problem}")
    # placeholder preserved, not doubled
    assert ad._template.count("{problem}") == 1


def test_build_adapter_claude_skill_explicit(monkeypatch) -> None:
    import adapters.claude_skill as cs

    monkeypatch.setattr(cs.shutil, "which", lambda _: "/fake/claude")

    from cli import _build_adapter

    ad = _build_adapter("claude_skill:/x:y {problem}:my-tag")
    # tag is the bit after the final ':'
    assert ad.name == "claude_skill[my-tag]@0.1"
    assert ad._template == "/x:y {problem}"
