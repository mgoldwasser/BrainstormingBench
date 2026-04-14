#!/usr/bin/env python3
"""BrainstormingBench — stdlib-only plugin runner.

Subcommands:
    bench.py run     --skill /slash:cmd --out runs/<dir>/   [--problems v1] [--limit N]
    bench.py battle  --a /slash:a --b /slash:b --problem <id|"text"> [--battles 3]
    bench.py judge   --a runs/<a>/ --b runs/<b>/ [--battles 3] [--seed 0]
    bench.py report  [--runs runs/] [--out leaderboard.md]

Design constraints:
- Stdlib only. The plugin must run with system python3, no pip install.
- All model calls go through `claude -p` (subscription auth, no API key).
- All outputs and intermediate artifacts are JSON / Markdown so they
  remain inspectable without the script.

Frozen invariants (mirrored from the original Python package):
- Generators use claude-opus-4-6, judge uses claude-sonnet-4-6 — different
  family so the judge isn't grading its own kin.
- Battles are blinded and position-randomized; SingleBattle.order records
  which physical slot the canonical A system occupied so verdicts can be
  flipped back when aggregating.
- Elo: K=32, initial=1500, ties=0.5, bootstrap CI via percentile of
  resampled-with-replacement battle lists (1000 iterations).
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# locations
# ---------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent
PROBLEMS_DIR = SCRIPT_DIR / "problems"
RUBRICS_DIR = SCRIPT_DIR / "rubrics"

GENERATOR_MODEL = "claude-opus-4-6"
JUDGE_MODEL = "claude-sonnet-4-6"
DEFAULT_TIMEOUT_S = 600


# ---------------------------------------------------------------------------
# claude -p transport
# ---------------------------------------------------------------------------

def _require_claude_cli(binary: str = "claude") -> None:
    if shutil.which(binary) is None:
        die(
            f"cannot find `{binary}` on PATH. Install Claude Code "
            "(https://claude.com/claude-code) — this plugin requires it."
        )


def claude_p(
    invocation: str,
    *,
    system_prompt: str | None = None,
    model: str | None = None,
    json_schema: dict | None = None,
    effort: str | None = None,
    timeout_s: int = DEFAULT_TIMEOUT_S,
    bare: bool = False,
    allow_everything: bool = False,
) -> tuple[str, dict[str, Any]]:
    """Invoke `claude -p` and return (stdout, meta).

    `invocation` is the prompt or slash-command string passed as the
    positional argument to `claude -p`. When `bare=True`, hooks / plugin
    discovery / CLAUDE.md / auto-memory are disabled and the model is
    pinned — used for the generator/judge text calls. When `bare=False`
    the user's environment is preserved — used when running a slash
    command that itself depends on hooks / skills.

    `allow_everything=True` adds `--dangerously-skip-permissions`. Required
    for non-interactive invocation of plugins that read files or use tools
    at runtime; there is no human in the loop to approve permission prompts.

    Why not `--bare` for the judge: `--bare` disables keychain/OAuth reads,
    forcing `ANTHROPIC_API_KEY` for auth. That breaks subscription users.
    Instead we approximate isolation with `--tools ""` and
    `--disable-slash-commands` plus an explicit `--system-prompt`, which by
    itself overrides default CLAUDE.md / dynamic-section discovery.
    """
    _require_claude_cli()
    args: list[str] = ["claude", "-p"]
    if bare:
        args += ["--tools", "", "--disable-slash-commands"]
    if allow_everything:
        args.append("--dangerously-skip-permissions")
    if model:
        args += ["--model", model]
    if system_prompt is not None:
        args += ["--system-prompt", system_prompt]
    if effort:
        args += ["--effort", effort]
    if json_schema is not None:
        # --json-schema requires --output-format json; the validated object
        # lands in the result envelope's .structured_output, not .result.
        args += ["--json-schema", json.dumps(json_schema)]
        args += ["--output-format", "json"]
    args.append(invocation)

    started = time.time()
    completed = subprocess.run(
        args, capture_output=True, text=True, timeout=timeout_s, check=False
    )
    latency = round(time.time() - started, 2)
    if completed.returncode != 0:
        raise RuntimeError(
            f"`claude -p` exited rc={completed.returncode}; "
            f"stderr tail: {(completed.stderr or '')[-500:]}"
        )
    return completed.stdout, {
        "transport": "claude_cli",
        "model": model,
        "latency_s": latency,
        "stderr_tail": (completed.stderr or "")[-500:],
    }


# ---------------------------------------------------------------------------
# problems / rubric
# ---------------------------------------------------------------------------

def load_problems(version: str) -> tuple[dict, list[dict]]:
    path = PROBLEMS_DIR / f"{version}.json"
    if not path.exists():
        die(f"no problem set at {path}")
    data = json.loads(path.read_text())
    return data, data["problems"]


def load_rubric(version: str) -> str:
    path = RUBRICS_DIR / f"rubric_{version}.md"
    if not path.exists():
        die(f"no rubric at {path}")
    return path.read_text()


# ---------------------------------------------------------------------------
# idea parsing — heuristic split of raw output into a list of ideas
# ---------------------------------------------------------------------------

_BULLET_RE = re.compile(
    r"""^\s*(?:
          \d+\s*[.)]
        | [-*•]
        | \(?[a-zA-Z]\s*[.)]
    )\s+""",
    re.VERBOSE,
)
_SKIP_RE = re.compile(
    r"""^\s*(?:
          \#{1,6}\s
        | (?:here(?:'s|\sare)|below)\b
    )""",
    re.VERBOSE | re.IGNORECASE,
)


def parse_ideas(raw: str) -> list[str]:
    """Split a verbatim brainstorming output into idea texts."""
    if not raw or not raw.strip():
        return []

    bulleted: list[str] = []
    current: list[str] = []
    for line in raw.splitlines():
        if _SKIP_RE.match(line):
            continue
        stripped = line.rstrip()
        if _BULLET_RE.match(stripped):
            if current:
                bulleted.append(" ".join(current).strip())
                current = []
            current.append(_BULLET_RE.sub("", stripped, count=1).strip())
        elif stripped.strip() == "":
            if current:
                bulleted.append(" ".join(current).strip())
                current = []
        else:
            if current:
                current.append(stripped.strip())
    if current:
        bulleted.append(" ".join(current).strip())

    if len(bulleted) >= 2:
        return [t for t in bulleted if t]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", raw) if p.strip()]
    paragraphs = [p for p in paragraphs if not _SKIP_RE.match(p)]
    if len(paragraphs) >= 2:
        return paragraphs

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", raw) if s.strip()]
    if len(sentences) > 1:
        return sentences

    return [raw.strip()]


# ---------------------------------------------------------------------------
# response helpers (filesystem layout)
# ---------------------------------------------------------------------------

def write_response(out_dir: Path, problem_id: str, payload: dict) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{problem_id}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False))
    return path


def load_responses(run_dir: Path) -> dict[str, dict]:
    """problem_id -> response dict, skipping bookkeeping files."""
    out: dict[str, dict] = {}
    for p in sorted(run_dir.glob("*.json")):
        if p.name in {"run_meta.json", "metrics.json", "battle.json"}:
            continue
        try:
            data = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        pid = data.get("problem_id") or p.stem
        out[pid] = data
    return out


def auto_tag(spec: str) -> str:
    """Derive a leaderboard tag from a slash-command spec."""
    head = spec.split(" ", 1)[0]
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", head.lstrip("/"))
    return cleaned.strip("-") or "skill"


def system_name(spec: str) -> str:
    return f"claude_skill[{auto_tag(spec)}]@0.1"


# ---------------------------------------------------------------------------
# brainstorming-side: invoke a slash command per problem
# ---------------------------------------------------------------------------

def run_skill(skill_spec: str, problem_text: str, *, allow_everything: bool = False) -> dict:
    """Invoke a slash command for one problem and return a response dict."""
    invocation = (
        skill_spec.format(problem=problem_text)
        if "{problem}" in skill_spec
        else f"{skill_spec} {problem_text}"
    )
    raw, meta = claude_p(invocation, bare=False, allow_everything=allow_everything)
    return {
        "system": system_name(skill_spec),
        "skill_spec": skill_spec,
        "ideas": [{"text": t} for t in parse_ideas(raw)],
        "raw": raw,
        "meta": meta,
    }


# ---------------------------------------------------------------------------
# judge
# ---------------------------------------------------------------------------

JUDGE_SCHEMA = {
    "type": "object",
    "required": ["reasoning", "novelty_winner", "diversity_winner",
                 "usefulness_winner", "winner"],
    "additionalProperties": False,
    "properties": {
        "reasoning": {"type": "string"},
        "novelty_winner": {"enum": ["A", "B", "tie"]},
        "diversity_winner": {"enum": ["A", "B", "tie"]},
        "usefulness_winner": {"enum": ["A", "B", "tie"]},
        "winner": {"enum": ["A", "B", "tie"]},
    },
}


def render_response(resp: dict) -> str:
    ideas = resp.get("ideas") or []
    if not ideas:
        return "(no ideas)"
    return "\n".join(f"{i}. {idea['text'].strip()}" for i, idea in enumerate(ideas, 1))


def model_family(model: str | None) -> str:
    if not model:
        return ""
    for fam in ("opus", "sonnet", "haiku"):
        if fam in model:
            return fam
    return model


def family_warnings(a: dict, b: dict) -> list[str]:
    judge_fam = model_family(JUDGE_MODEL)
    out: list[str] = []
    for resp in (a, b):
        m = (resp.get("meta") or {}).get("model")
        if m and model_family(m) == judge_fam:
            out.append(
                f"judge family ({judge_fam}) matches generator "
                f"{resp.get('system')!r}'s model {m}; results may be biased"
            )
    return out


def run_one_battle(
    problem_text: str,
    a: dict,
    b: dict,
    problem_id: str,
    rubric: str,
    rng: random.Random,
) -> dict:
    """One blinded, position-randomized judge call. Returns a SingleBattle dict."""
    a_first = rng.random() < 0.5
    order = "A_first" if a_first else "B_first"
    first, second = (a, b) if a_first else (b, a)
    user = (
        f"Problem:\n{problem_text}\n\n"
        f"--- Response A ---\n{render_response(first)}\n\n"
        f"--- Response B ---\n{render_response(second)}\n\n"
        "Follow the rubric. Return JSON matching the required schema."
    )
    try:
        raw, _meta = claude_p(
            user,
            system_prompt=rubric,
            model=JUDGE_MODEL,
            json_schema=JUDGE_SCHEMA,
            effort="medium",
            bare=True,
        )
        output = parse_judge_envelope(raw)
    except Exception as e:  # noqa: BLE001 — record and continue
        output = {"error": f"{type(e).__name__}: {e}"}
    return {
        "a_system": a["system"],
        "b_system": b["system"],
        "problem_id": problem_id,
        "order": order,
        "output": output,
        "judge_model": JUDGE_MODEL,
    }


def parse_judge_envelope(raw: str) -> dict:
    """Parse `claude -p --output-format json --json-schema` envelope.

    The envelope is JSON with keys including `result`, `is_error`, and
    `structured_output`. The schema-validated object is in
    `.structured_output`. We surface that. If the envelope reports an error
    or has no structured output, raise so the battle is recorded as failed.
    """
    envelope = json.loads(raw.strip())
    if envelope.get("is_error"):
        raise RuntimeError(f"judge envelope reported error: {envelope.get('result', '')[:500]}")
    structured = envelope.get("structured_output")
    if not isinstance(structured, dict):
        raise RuntimeError(
            f"judge envelope missing structured_output; "
            f"result={(envelope.get('result') or '')[:200]!r}"
        )
    return structured


def run_battles(
    problem_text: str,
    a: dict,
    b: dict,
    problem_id: str,
    rubric: str,
    n: int,
    rng: random.Random,
) -> dict:
    """Aggregate N SingleBattles into a BattleRecord dict."""
    return {
        "a_system": a["system"],
        "b_system": b["system"],
        "problem_id": problem_id,
        "battles": [
            run_one_battle(problem_text, a, b, problem_id, rubric, rng)
            for _ in range(n)
        ],
    }


def majority_winner(record: dict) -> str:
    """Position-normalized majority verdict across record['battles']."""
    votes = {"A": 0, "B": 0, "tie": 0}
    for b in record["battles"]:
        w = (b.get("output") or {}).get("winner")
        if w not in votes:
            continue
        if b["order"] == "A_first":
            votes[w] += 1
        else:
            votes["A" if w == "B" else "B" if w == "A" else "tie"] += 1
    top = max(votes.values())
    winners = [k for k, v in votes.items() if v == top]
    return winners[0] if len(winners) == 1 else "tie"


# ---------------------------------------------------------------------------
# Elo
# ---------------------------------------------------------------------------

INITIAL_ELO = 1500.0
K_FACTOR = 32.0


def canonicalize(records: list[dict]) -> list[tuple[str, str, float]]:
    """Flatten BattleRecords into (a_system, b_system, score_a) tuples."""
    out: list[tuple[str, str, float]] = []
    for r in records:
        for b in r["battles"]:
            w = (b.get("output") or {}).get("winner")
            if w not in ("A", "B", "tie"):
                continue
            effective = w if b["order"] == "A_first" else (
                "A" if w == "B" else "B" if w == "A" else "tie"
            )
            score = {"A": 1.0, "B": 0.0, "tie": 0.5}[effective]
            out.append((r["a_system"], r["b_system"], score))
    return out


def update_ratings(
    battles: list[tuple[str, str, float]],
    *,
    seed: int | None = None,
) -> dict[str, float]:
    rng = random.Random(seed)
    order = list(battles)
    rng.shuffle(order)
    ratings: dict[str, float] = {}
    for a, b, sa in order:
        ra = ratings.setdefault(a, INITIAL_ELO)
        rb = ratings.setdefault(b, INITIAL_ELO)
        ea = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
        eb = 1.0 - ea
        ratings[a] = ra + K_FACTOR * (sa - ea)
        ratings[b] = rb + K_FACTOR * ((1.0 - sa) - eb)
    return ratings


def percentile(sorted_vals: list[float], p: float) -> float:
    """Linear-interpolated percentile (mirrors numpy default)."""
    if not sorted_vals:
        return float("nan")
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    rank = (p / 100.0) * (len(sorted_vals) - 1)
    lo = math.floor(rank)
    hi = math.ceil(rank)
    if lo == hi:
        return sorted_vals[lo]
    frac = rank - lo
    return sorted_vals[lo] * (1 - frac) + sorted_vals[hi] * frac


def bootstrap_cis(
    battles: list[tuple[str, str, float]],
    *,
    iterations: int = 1000,
    seed: int = 42,
) -> dict[str, tuple[float, float]]:
    rng = random.Random(seed)
    systems = {s for ab in battles for s in ab[:2]}
    if not battles:
        return {s: (INITIAL_ELO, INITIAL_ELO) for s in systems}
    samples: dict[str, list[float]] = {s: [] for s in systems}
    n = len(battles)
    for _ in range(iterations):
        resampled = [battles[rng.randrange(n)] for _ in range(n)]
        rated = update_ratings(resampled, seed=rng.randrange(2**32))
        for s in systems:
            samples[s].append(rated.get(s, INITIAL_ELO))
    out: dict[str, tuple[float, float]] = {}
    for s, vals in samples.items():
        vals_sorted = sorted(vals)
        out[s] = (percentile(vals_sorted, 2.5), percentile(vals_sorted, 97.5))
    return out


def leaderboard_markdown(records: list[dict], *, seed: int = 42) -> str:
    battles = canonicalize(records)
    ratings = update_ratings(battles, seed=seed)
    cis = bootstrap_cis(battles, seed=seed)
    wlt: dict[str, list[int]] = {s: [0, 0, 0] for s in ratings}
    for a, b, sa in battles:
        if sa == 1.0:
            wlt[a][0] += 1; wlt[b][1] += 1
        elif sa == 0.0:
            wlt[a][1] += 1; wlt[b][0] += 1
        else:
            wlt[a][2] += 1; wlt[b][2] += 1

    rows = sorted(ratings.items(), key=lambda kv: kv[1], reverse=True)
    lines = [
        "| Rank | System | Elo | 95% CI | W | L | T |",
        "|-----:|:-------|----:|:------:|--:|--:|--:|",
    ]
    for rank, (s, r) in enumerate(rows, 1):
        lo, hi = cis.get(s, (r, r))
        w, l, t = wlt.get(s, [0, 0, 0])
        lines.append(
            f"| {rank} | `{s}` | {r:.0f} | [{lo:.0f}, {hi:.0f}] | "
            f"{w} | {l} | {t} |"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# subcommands
# ---------------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> None:
    meta, problems = load_problems(args.problems)
    if args.limit is not None:
        problems = problems[: args.limit]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    run_meta = {
        "skill_spec": args.skill,
        "system": system_name(args.skill),
        "problem_set_version": meta["version"],
        "problem_set_frozen_at": meta["frozen_at"],
        "started_at": datetime.now(timezone.utc).isoformat(),
        "problem_count": len(problems),
        "workers": args.workers,
        "run_type": "skill_run",
    }
    (out / "run_meta.json").write_text(json.dumps(run_meta, indent=2))

    total = len(problems)

    def run_one(p: dict) -> None:
        pid = p["id"]
        log(f"  start {pid}")
        t0 = time.time()
        resp = run_skill(args.skill, p["prompt"], allow_everything=args.allow_everything)
        resp["problem_id"] = pid
        write_response(out, pid, resp)
        log(f"  done  {pid}: {len(resp['ideas'])} ideas in {time.time() - t0:.1f}s")

    log(f"running {total} problems, workers={args.workers}")
    parallel_map(run_one, problems, args.workers)
    log(f"done: {out}")


def cmd_battle(args: argparse.Namespace) -> None:
    _, problems = load_problems(args.problems)
    matched = next((p for p in problems if p["id"] == args.problem), None)
    if matched is not None:
        problem_id, problem_text = matched["id"], matched["prompt"]
    else:
        problem_id, problem_text = "custom", args.problem

    out = Path(args.out) if args.out else Path("runs") / (
        f"battle-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    out.mkdir(parents=True, exist_ok=True)

    log(f"battle on {problem_id}: {problem_text[:80]}")
    log(f"A = {args.a}")
    log(f"B = {args.b}")

    a_resp = run_skill(args.a, problem_text, allow_everything=args.allow_everything)
    a_resp["problem_id"] = problem_id
    write_response(out / "A", problem_id, a_resp)
    b_resp = run_skill(args.b, problem_text, allow_everything=args.allow_everything)
    b_resp["problem_id"] = problem_id
    write_response(out / "B", problem_id, b_resp)
    log(f"A produced {len(a_resp['ideas'])} ideas, B produced {len(b_resp['ideas'])} ideas")

    rubric = load_rubric(args.problems)
    for w in family_warnings(a_resp, b_resp):
        log(f"WARN {w}")
    rng = random.Random(args.seed)
    record = run_battles(
        problem_text, a_resp, b_resp, problem_id, rubric, args.battles, rng
    )

    (out / "battle.json").write_text(json.dumps({
        "problem_id": problem_id,
        "problem_text": problem_text,
        "problem_set_version": args.problems,
        "seed": args.seed,
        "battles_per_pair": args.battles,
        "records": [record],
    }, indent=2))

    winner_map = {"A": args.a, "B": args.b, "tie": "tie"}
    print("---", file=sys.stderr)
    print(f"Verdict: {winner_map[majority_winner(record)]}", file=sys.stderr)
    sub = {"novelty_winner": {}, "diversity_winner": {}, "usefulness_winner": {}}
    for b in record["battles"]:
        for k in sub:
            v = (b.get("output") or {}).get(k)
            if v not in ("A", "B", "tie"):
                continue
            if b["order"] == "B_first":
                v = {"A": "B", "B": "A", "tie": "tie"}[v]
            sub[k][v] = sub[k].get(v, 0) + 1
    for k, tallies in sub.items():
        nice = k.replace("_winner", "")
        ordered = ", ".join(
            f"{winner_map[w]}={n}"
            for w, n in sorted(tallies.items(), key=lambda x: -x[1])
        )
        print(f"  {nice}: {ordered}", file=sys.stderr)
    log(f"wrote {out}/battle.json (and A/, B/)")


def cmd_judge(args: argparse.Namespace) -> None:
    a_responses = load_responses(Path(args.a))
    b_responses = load_responses(Path(args.b))
    _, problems = load_problems(args.problems)
    common = [p for p in problems if p["id"] in a_responses and p["id"] in b_responses]
    if not common:
        die("no overlapping problem ids between A and B")

    rubric = load_rubric(args.problems)
    for w in family_warnings(a_responses[common[0]["id"]], b_responses[common[0]["id"]]):
        log(f"WARN {w}")

    def judge_one(p: dict) -> dict:
        pid = p["id"]
        log(f"  start {pid}")
        # Per-problem rng derived from master seed so parallel scheduling
        # doesn't change the position-randomization sequence per problem.
        prng = random.Random(f"{args.seed}:{pid}")
        rec = run_battles(
            p["prompt"], a_responses[pid], b_responses[pid],
            pid, rubric, args.battles, prng,
        )
        log(f"  done  {pid}: majority={majority_winner(rec)}")
        return rec

    log(f"judging {len(common)} problems × {args.battles} battles, workers={args.workers}")
    records = parallel_map(judge_one, common, args.workers)

    out_path = Path(args.out) if args.out else Path("runs") / (
        f"battles-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "problem_set_version": args.problems,
        "seed": args.seed,
        "battles_per_pair": args.battles,
        "records": records,
    }, indent=2))
    log(f"wrote {out_path}")
    print(leaderboard_markdown(records))


def cmd_report(args: argparse.Namespace) -> None:
    runs_dir = Path(args.runs)
    all_records: list[dict] = []
    for bf in sorted(runs_dir.glob("battles-*.json")):
        data = json.loads(bf.read_text())
        all_records.extend(data.get("records", []))
    if not all_records:
        die(f"no battle files in {runs_dir}/ (battles-*.json)")
    md = leaderboard_markdown(all_records)
    header = (
        "# BrainstormingBench leaderboard\n\n"
        f"_Generated {datetime.now(timezone.utc).isoformat()} from "
        f"{len(all_records)} pairwise battle records._\n\n"
    )
    Path(args.out).write_text(header + md + "\n")
    print(md)
    log(f"wrote {args.out}")


# ---------------------------------------------------------------------------
# logging / CLI scaffolding
# ---------------------------------------------------------------------------

_LOG_LOCK = threading.Lock()


def log(msg: str) -> None:
    with _LOG_LOCK:
        print(msg, file=sys.stderr, flush=True)


def parallel_map(fn, items, workers: int):
    """Apply fn to each item, optionally with a thread pool.

    workers=1 runs serially in input order. workers>1 uses a ThreadPoolExecutor
    and returns results in INPUT order (not completion order) so downstream
    aggregation is deterministic.
    """
    if workers <= 1 or len(items) <= 1:
        return [fn(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as ex:
        return list(ex.map(fn, items))


def die(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)
    sys.exit(2)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="bench", description="BrainstormingBench plugin runner."
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="Run a slash command over a problem set.")
    p_run.add_argument("--skill", required=True, help="slash command, e.g. /my-plugin:brainstorm")
    p_run.add_argument("--out", required=True, help="run directory to write into")
    p_run.add_argument("--problems", default="v1")
    p_run.add_argument("--limit", type=int, default=None)
    p_run.add_argument(
        "--allow-everything",
        action="store_true",
        help="pass --dangerously-skip-permissions to the slash-command subprocess "
             "(needed for plugins that read files or use tools at runtime)",
    )
    p_run.add_argument(
        "--workers", type=int, default=1,
        help="parallel claude -p subprocesses (default 1; raise to overlap I/O, "
             "watch for subscription rate limits)",
    )
    p_run.set_defaults(func=cmd_run)

    p_b = sub.add_parser("battle", help="One-shot pairwise battle on a single problem.")
    p_b.add_argument("--a", required=True, help="slash command for system A")
    p_b.add_argument("--b", required=True, help="slash command for system B")
    p_b.add_argument("--problem", required=True, help="problem id, or quoted custom prompt")
    p_b.add_argument("--battles", type=int, default=3)
    p_b.add_argument("--problems", default="v1")
    p_b.add_argument("--seed", type=int, default=0)
    p_b.add_argument("--out", default=None)
    p_b.add_argument(
        "--allow-everything",
        action="store_true",
        help="pass --dangerously-skip-permissions to the slash-command subprocesses",
    )
    p_b.set_defaults(func=cmd_battle)

    p_j = sub.add_parser("judge", help="Pairwise battles between two saved run dirs.")
    p_j.add_argument("--a", required=True, help="run dir for system A")
    p_j.add_argument("--b", required=True, help="run dir for system B")
    p_j.add_argument("--battles", type=int, default=3)
    p_j.add_argument("--problems", default="v1")
    p_j.add_argument("--seed", type=int, default=0)
    p_j.add_argument("--out", default=None)
    p_j.add_argument(
        "--workers", type=int, default=1,
        help="parallel judge calls across problems (default 1)",
    )
    p_j.set_defaults(func=cmd_judge)

    p_r = sub.add_parser("report", help="Regenerate leaderboard.md from runs/battles-*.json.")
    p_r.add_argument("--runs", default="runs")
    p_r.add_argument("--out", default="leaderboard.md")
    p_r.set_defaults(func=cmd_report)

    return ap


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
