"""Transport helpers: route model calls through `claude -p` (subscription) or the Anthropic SDK (API key).

Why two transports:
- **CLI** (default): invokes `claude -p` as a subprocess. Auth is the user's
  Claude Code subscription — no `ANTHROPIC_API_KEY` required. This is the
  expected path when the benchmark runs inside a Claude Code session.
- **API**: uses the Anthropic SDK directly. Needs `ANTHROPIC_API_KEY`.
  Useful for CI / batch runs where the `claude` CLI isn't installed.

Selection precedence (see `default_transport()`):
1. `BENCH_TRANSPORT` env var (`cli` | `api`) wins if set.
2. If the `claude` CLI is on PATH, use `cli`.
3. Else, fall back to `api` (will fail loudly if no API key).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Any

DEFAULT_TIMEOUT_S = 600
DEFAULT_GENERATOR_MODEL = "claude-opus-4-6"


def has_claude_cli(binary: str = "claude") -> bool:
    return shutil.which(binary) is not None


def default_transport() -> str:
    """Pick 'cli' or 'api' per the precedence above."""
    env = os.environ.get("BENCH_TRANSPORT", "").strip().lower()
    if env in {"cli", "api"}:
        return env
    if env:
        raise ValueError(
            f"BENCH_TRANSPORT={env!r}; expected 'cli' or 'api' (or unset)"
        )
    return "cli" if has_claude_cli() else "api"


# ---------------------------------------------------------------------------
# CLI transport
# ---------------------------------------------------------------------------

def generate_via_cli(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_GENERATOR_MODEL,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    json_schema: str | None = None,
    effort: str | None = None,
    claude_binary: str = "claude",
) -> tuple[str, dict[str, Any]]:
    """Invoke `claude -p` and return (raw_output, meta).

    - `--bare` skips hooks / plugins / CLAUDE.md discovery / auto-memory so
      the subprocess is a clean slate regardless of where it was launched.
    - `--tools ""` disables all tools — generators and judges should not be
      using Bash, Edit, etc. They produce text.
    - `--json-schema`, if passed, constrains the model's stdout to a JSON
      object matching the schema. Used by the judge.
    """
    if not has_claude_cli(claude_binary):
        raise FileNotFoundError(
            f"cannot find `{claude_binary}` on PATH; install Claude Code "
            "(https://claude.com/claude-code) or set BENCH_TRANSPORT=api "
            "to use the Anthropic SDK instead (requires ANTHROPIC_API_KEY)"
        )

    args: list[str] = [
        claude_binary,
        "-p",
        "--model", model,
        "--system-prompt", system_prompt,
        "--tools", "",
        "--bare",
    ]
    if effort:
        args.extend(["--effort", effort])
    if json_schema is not None:
        args.extend(["--json-schema", json_schema])
    args.append(user_prompt)

    started = time.time()
    completed = subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        check=False,
    )
    latency = time.time() - started

    if completed.returncode != 0:
        raise RuntimeError(
            f"`claude -p` exited with rc={completed.returncode}; "
            f"stderr tail: {(completed.stderr or '')[-500:]}"
        )

    return completed.stdout, {
        "transport": "claude_cli",
        "model": model,
        "latency_s": round(latency, 2),
        "stderr_tail": (completed.stderr or "")[-500:],
    }


# ---------------------------------------------------------------------------
# API transport
# ---------------------------------------------------------------------------

def generate_via_api(
    system_prompt: str,
    user_prompt: str,
    model: str = DEFAULT_GENERATOR_MODEL,
    max_tokens: int = 8192,
) -> tuple[str, dict[str, Any]]:
    """Invoke the Anthropic SDK with streaming and return (raw_output, meta).

    Raises FileNotFoundError-equivalent if `ANTHROPIC_API_KEY` is unset
    (anthropic SDK will fail at construction time).
    """
    from anthropic import Anthropic  # lazy — keeps optional for CLI-only users

    if "ANTHROPIC_API_KEY" not in os.environ:
        raise RuntimeError(
            "BENCH_TRANSPORT=api requires ANTHROPIC_API_KEY. "
            "Unset BENCH_TRANSPORT to use the `claude -p` CLI transport instead."
        )

    client = Anthropic()
    started = time.time()
    chunks: list[str] = []
    usage: dict[str, Any] = {}
    with client.messages.stream(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        thinking={"type": "adaptive"},
        messages=[{"role": "user", "content": user_prompt}],
    ) as stream:
        for text in stream.text_stream:
            chunks.append(text)
        final = stream.get_final_message()
        if final.usage is not None:
            usage = {
                "input_tokens": final.usage.input_tokens,
                "output_tokens": final.usage.output_tokens,
            }

    return "".join(chunks), {
        "transport": "anthropic_sdk",
        "model": model,
        "latency_s": round(time.time() - started, 2),
        **usage,
    }


# ---------------------------------------------------------------------------
# JSON-mode helper for the judge
# ---------------------------------------------------------------------------

def parse_via_api(
    system_prompt: str,
    user_prompt: str,
    output_format,   # a Pydantic BaseModel subclass
    model: str,
    max_tokens: int = 4096,
    effort: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    """SDK-mode structured output using `messages.parse` + Pydantic."""
    from anthropic import Anthropic

    if "ANTHROPIC_API_KEY" not in os.environ:
        raise RuntimeError(
            "BENCH_TRANSPORT=api requires ANTHROPIC_API_KEY."
        )

    client = Anthropic()
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system_prompt,
        "thinking": {"type": "adaptive"},
        "output_format": output_format,
        "messages": [{"role": "user", "content": user_prompt}],
    }
    if effort:
        kwargs["output_config"] = {"effort": effort}

    started = time.time()
    result = client.messages.parse(**kwargs)
    latency = time.time() - started

    return result.parsed_output, {
        "transport": "anthropic_sdk",
        "model": model,
        "latency_s": round(latency, 2),
    }


def parse_via_cli(
    system_prompt: str,
    user_prompt: str,
    output_format,   # a Pydantic BaseModel subclass
    model: str,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    effort: str | None = None,
    claude_binary: str = "claude",
) -> tuple[Any, dict[str, Any]]:
    """CLI-mode structured output using `claude -p --json-schema`.

    The Pydantic model's JSON schema is passed to `--json-schema`, which
    constrains the model's stdout. We then parse stdout as JSON and
    validate with Pydantic (the SDK's belt-and-suspenders equivalent of
    `messages.parse`).
    """
    schema = json.dumps(output_format.model_json_schema())
    raw, meta = generate_via_cli(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        timeout_s=timeout_s,
        json_schema=schema,
        effort=effort,
        claude_binary=claude_binary,
    )

    # `claude -p --json-schema` returns the schema-conforming JSON on stdout.
    # Strip any leading/trailing whitespace and markdown fences just in case.
    stripped = raw.strip()
    if stripped.startswith("```"):
        # Remove opening fence (optionally with language tag) and closing fence.
        lines = stripped.splitlines()
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()

    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"`claude -p --json-schema` returned non-JSON output: "
            f"{stripped[:500]!r}"
        ) from e

    parsed = output_format.model_validate(data)
    return parsed, meta
