"""Generic adapter: invoke any Claude Code skill or plugin via `claude -p`.

Use this to add brainstorming systems to the leaderboard without writing
Python. Anything you can run from a Claude Code prompt — a slash command
on a plugin, a skill, a user-defined command — can be benchmarked:

    ClaudeSkillAdapter(
        command_template="/my-plugin:brainstorm {problem}",
        tag="my-plugin-v2",
    )

The adapter shells out to a fresh, non-interactive `claude -p "<cmd>"`
subprocess per problem. Each invocation is a clean session, so outputs
are independent from whatever session invoked the benchmark.

The brainstorm_kit adapter predates this one and has similar behavior for
its CLI transport; ClaudeSkillAdapter is the right choice for anything
else.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time

from adapters.base import Adapter, Response, parse_ideas


def _sanitize_tag(raw: str) -> str:
    """Make a leaderboard-safe tag out of an arbitrary string."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", raw.strip())
    return cleaned.strip("-") or "skill"


class ClaudeSkillAdapter(Adapter):
    """Wrap an arbitrary `claude -p` invocation as an Adapter."""

    def __init__(
        self,
        command_template: str,
        tag: str,
        claude_binary: str = "claude",
        timeout_s: int = 600,
        require_binary: bool = True,
    ) -> None:
        if "{problem}" not in command_template:
            raise ValueError(
                "command_template must contain '{problem}'; e.g. "
                "'/my-plugin:brainstorm {problem}'"
            )
        if require_binary and shutil.which(claude_binary) is None:
            raise FileNotFoundError(
                f"cannot find `{claude_binary}` on PATH; install Claude Code"
                " (https://claude.com/claude-code) or pass require_binary=False"
            )
        self._template = command_template
        self._claude_binary = claude_binary
        self._timeout_s = timeout_s
        self.name = f"claude_skill[{_sanitize_tag(tag)}]@0.1"

    def generate(self, problem: str) -> Response:
        invocation = self._template.format(problem=problem)
        started = time.time()
        completed = subprocess.run(
            [self._claude_binary, "-p", invocation],
            capture_output=True,
            text=True,
            timeout=self._timeout_s,
            check=False,
        )
        raw = completed.stdout or ""
        ideas = parse_ideas(raw, origin=self.name)
        return Response(
            problem_id="",
            system=self.name,
            ideas=ideas,
            raw=raw,
            meta={
                "transport": "claude_cli",
                "command_template": self._template,
                "returncode": completed.returncode,
                "stderr_tail": (completed.stderr or "")[-500:],
                "latency_s": round(time.time() - started, 2),
            },
        )
