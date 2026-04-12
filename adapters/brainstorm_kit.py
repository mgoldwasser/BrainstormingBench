"""Adapter for the brainstorm-kit plugin at github.com/mgoldwasser/ClaudeBrainstorming.

This adapter talks to brainstorm-kit **externally**, either by invoking the
`claude` CLI as a subprocess or by replicating the public brainstorm-kit
prompt via the Anthropic SDK. The benchmark must never import brainstorm-kit
code — comparability depends on this being a black-box call.

Transport selection at construction time:
    - "cli":  shell out to `claude -p "/brainstorm-kit:brainstorm <problem>"`.
              Requires a working `claude` install on PATH and the plugin
              enabled in the user's configuration. Captures stdout verbatim.
    - "sdk":  replicate the plugin's top-level prompt via the Anthropic SDK.
              Cheaper to reproduce on CI but necessarily a simplification;
              the real plugin may do multi-step orchestration this adapter
              does not reproduce.
    - "auto": use "cli" if a `claude` binary is found on PATH, else "sdk".

The "sdk" path is clearly labelled in the adapter name so that a fallback
run is never silently mistaken for a real run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from typing import Any

from adapters.base import Adapter, Response, parse_ideas

_MODEL = "claude-opus-4-6"

# Public, simplified replica of the brainstorm-kit top-level prompt. Kept
# short to avoid drifting from the real plugin; the point of "sdk" mode is
# to be a plausible stand-in on CI, not an exact replica.
_SDK_SYSTEM = (
    "You are a brainstorming facilitator running a multi-technique session. "
    "For the given problem, silently consider at least three distinct "
    "brainstorming techniques (e.g. first-principles decomposition, "
    "analogies from another domain, deliberate worst-ideas-then-invert, "
    "constraint removal). Produce a single merged numbered list of at least "
    "15 distinct ideas, drawing from multiple techniques. For each idea, "
    "optionally annotate the originating technique in square brackets at the "
    "end of the line. No preamble, no conclusion."
)


class BrainstormKitAdapter(Adapter):
    """External adapter for the brainstorm-kit plugin."""

    def __init__(
        self,
        transport: str = "auto",
        plugin_command: str = "/brainstorm-kit:brainstorm",
        claude_binary: str = "claude",
        version_tag: str = "unknown",
        model: str = _MODEL,
        max_tokens: int = 8192,
        timeout_s: int = 600,
    ) -> None:
        if transport not in {"auto", "cli", "sdk"}:
            raise ValueError(f"unknown transport {transport!r}")
        resolved = transport
        if transport == "auto":
            resolved = "cli" if shutil.which(claude_binary) else "sdk"

        self._transport = resolved
        self._plugin_command = plugin_command
        self._claude_binary = claude_binary
        self._model = model
        self._max_tokens = max_tokens
        self._timeout_s = timeout_s
        # Tag the name so runs from different transports never collide on the
        # leaderboard.
        self.name = f"brainstorm_kit[{resolved}]@{version_tag}"

    # ------------------------------------------------------------------
    # transport dispatch
    # ------------------------------------------------------------------

    def generate(self, problem: str) -> Response:
        if self._transport == "cli":
            return self._generate_cli(problem)
        return self._generate_sdk(problem)

    # --- cli transport ------------------------------------------------

    def _generate_cli(self, problem: str) -> Response:
        """Invoke the brainstorm-kit plugin via the local `claude` CLI.

        We pass the plugin command and the problem as a single `-p` argument
        so the CLI treats it as a non-interactive prompt. stdout is captured
        verbatim.
        """
        invocation = f'{self._plugin_command} {problem}'
        started = time.time()
        completed = subprocess.run(
            [self._claude_binary, "-p", invocation],
            capture_output=True,
            text=True,
            timeout=self._timeout_s,
            check=False,
        )
        latency = time.time() - started
        raw = completed.stdout or ""
        ideas = parse_ideas(raw, origin="brainstorm_kit")
        return Response(
            problem_id="",
            system=self.name,
            ideas=ideas,
            raw=raw,
            meta={
                "transport": "cli",
                "returncode": completed.returncode,
                "stderr": completed.stderr,
                "latency_s": round(latency, 2),
            },
        )

    # --- sdk transport ------------------------------------------------

    def _generate_sdk(self, problem: str) -> Response:
        from anthropic import Anthropic

        client = Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
        started = time.time()
        raw_chunks: list[str] = []
        usage: dict[str, Any] = {}
        with client.messages.stream(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SDK_SYSTEM,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": f"Problem:\n{problem}"}],
        ) as stream:
            for text in stream.text_stream:
                raw_chunks.append(text)
            final = stream.get_final_message()
            if final.usage is not None:
                usage = {
                    "input_tokens": final.usage.input_tokens,
                    "output_tokens": final.usage.output_tokens,
                }

        raw = "".join(raw_chunks)
        latency = time.time() - started
        ideas = parse_ideas(raw, origin="brainstorm_kit")
        return Response(
            problem_id="",
            system=self.name,
            ideas=ideas,
            raw=raw,
            meta={
                "transport": "sdk",
                "model": self._model,
                "latency_s": round(latency, 2),
                **usage,
            },
        )
