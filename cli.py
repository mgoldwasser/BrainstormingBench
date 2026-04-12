"""BrainstormingBench CLI.

Subcommands:
    bench run      — run one adapter over a problem set, write response JSONs
    bench metrics  — compute absolute metrics over a run directory
    bench judge    — pairwise battles between two run directories, update Elo
    bench report   — regenerate leaderboard.md from all saved battles

Run directories are self-describing: each problem's response is written as
`<problem_id>.json`, plus a `run_meta.json` that captures adapter name,
problem-set version, and timestamp.
"""

from __future__ import annotations

import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import click
import yaml
from rich.console import Console
from rich.table import Table

from adapters.base import Adapter, Response
from judge.elo import EloLeaderboard
from judge.pairwise import BattleRecord, PairwiseJudge, SingleBattle


console = Console()


# ---------------------------------------------------------------------------
# adapter registry
# ---------------------------------------------------------------------------

def _build_adapter(spec: str) -> Adapter:
    """Parse `--adapter` strings into an Adapter instance.

    Recognized forms:
        plain_claude
        single_technique[stoner_circle]   (or first_principles / worst_idea)
        brainstorm_kit
        brainstorm_kit[cli]               (force transport)
        brainstorm_kit[sdk]
        human:/path/to/responses_dir      (author inferred from dir name)

        # Any Claude Code slash command. The `{problem}` placeholder is
        # inserted automatically if absent.
        /my-plugin:brainstorm
        /my-plugin:brainstorm {problem}

        # Explicit form with a custom tag:
        claude_skill:/my-plugin:brainstorm {problem}:my-tag
    """
    if spec == "plain_claude":
        from adapters.plain_claude import PlainClaudeAdapter
        return PlainClaudeAdapter()
    if spec.startswith("single_technique"):
        from adapters.single_technique import SingleTechniqueAdapter
        technique = "stoner_circle"
        if "[" in spec and spec.endswith("]"):
            technique = spec[spec.index("[") + 1 : -1]
        return SingleTechniqueAdapter(technique=technique)
    if spec.startswith("brainstorm_kit"):
        from adapters.brainstorm_kit import BrainstormKitAdapter
        transport = "auto"
        if "[" in spec and spec.endswith("]"):
            transport = spec[spec.index("[") + 1 : -1]
        return BrainstormKitAdapter(transport=transport)
    if spec.startswith("human:"):
        from adapters.human import HumanAdapter
        path = spec.split(":", 1)[1]
        return HumanAdapter(
            responses_dir=path,
            author_tag=Path(path).name or "anonymous",
        )
    if spec.startswith("claude_skill:"):
        from adapters.claude_skill import ClaudeSkillAdapter
        # claude_skill:<template>:<tag>. Template may itself contain ':',
        # so rsplit once from the right to separate the tag.
        rest = spec[len("claude_skill:"):]
        if ":" in rest:
            template, tag = rest.rsplit(":", 1)
        else:
            template, tag = rest, _auto_tag(rest)
        if "{problem}" not in template:
            template = f"{template} {{problem}}"
        return ClaudeSkillAdapter(command_template=template, tag=tag)
    if spec.startswith("/"):
        # Raw slash-command form — auto-wrap into ClaudeSkillAdapter.
        from adapters.claude_skill import ClaudeSkillAdapter
        template = spec if "{problem}" in spec else f"{spec} {{problem}}"
        return ClaudeSkillAdapter(
            command_template=template, tag=_auto_tag(spec)
        )
    raise click.BadParameter(f"unknown adapter: {spec!r}")


def _auto_tag(spec: str) -> str:
    """Derive a leaderboard tag from a raw slash-command spec."""
    head = spec.split(" ", 1)[0]
    return head.lstrip("/").replace(":", "_").replace("/", "_") or "skill"


# ---------------------------------------------------------------------------
# problems loader
# ---------------------------------------------------------------------------

def _load_problems(version: str) -> tuple[dict, list[dict]]:
    path = Path(__file__).parent / "problems" / f"{version}.yaml"
    if not path.exists():
        raise click.BadParameter(f"no problem set at {path}")
    data = yaml.safe_load(path.read_text())
    return data, data["problems"]


# ---------------------------------------------------------------------------
# bench run
# ---------------------------------------------------------------------------

@click.group()
def cli() -> None:
    """Evaluate brainstorming systems on a frozen problem set."""


@cli.command("run")
@click.option("--adapter", "adapter_spec", required=True, help="adapter spec; see `_build_adapter`")
@click.option("--problems", "problems_version", default="v1", show_default=True)
@click.option("--out", "out_dir", type=click.Path(), required=True)
@click.option("--limit", type=int, default=None, help="cap number of problems (debug only)")
def cmd_run(adapter_spec: str, problems_version: str, out_dir: str, limit: int | None) -> None:
    """Run one adapter over a problem set."""
    adapter = _build_adapter(adapter_spec)
    meta, problems = _load_problems(problems_version)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    if limit is not None:
        problems = problems[:limit]

    run_meta = {
        "adapter": adapter.name,
        "problem_set_version": meta["version"],
        "problem_set_frozen_at": str(meta["frozen_at"]),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "problem_count": len(problems),
        "run_type": "adapter_run",
    }
    (out / "run_meta.json").write_text(json.dumps(run_meta, indent=2))

    for i, p in enumerate(problems, start=1):
        pid = p["id"]
        console.log(f"[{i}/{len(problems)}] running {adapter.name} on {pid}")
        # Human adapter needs the id out-of-band; see adapters/human.py.
        if hasattr(adapter, "_current_problem_id"):
            setattr(adapter, "_current_problem_id", pid)
        else:
            setattr(adapter, "_current_problem_id", pid)

        t0 = time.time()
        response: Response = adapter.generate(p["prompt"])
        response.problem_id = pid
        response.save(out)
        console.log(
            f"    {len(response.ideas)} ideas in {time.time() - t0:.1f}s"
        )

    console.log(f"[green]done[/green]: {out}")


# ---------------------------------------------------------------------------
# bench metrics
# ---------------------------------------------------------------------------

@cli.command("metrics")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False))
@click.option(
    "--baseline",
    type=click.Path(exists=True, file_okay=False),
    default=None,
    help="baseline run dir (typically plain_claude) used for corpus-relative originality",
)
def cmd_metrics(run_dir: str, baseline: str | None) -> None:
    """Compute fluency, flexibility, originality, elaboration over a run dir."""
    from metrics import elaboration, flexibility, fluency, originality
    from metrics.originality import build_obvious_corpus

    rd = Path(run_dir)
    responses = _load_run(rd)
    if not responses:
        raise click.ClickException(f"no responses in {rd}")

    corpus = None
    if baseline:
        baseline_responses = _load_run(Path(baseline))
        corpus = build_obvious_corpus(baseline_responses)

    rows: list[dict] = []
    for r in responses:
        flu = fluency(r)
        flex = flexibility(r)
        orig = originality(r, corpus_embeddings=corpus)
        elab = elaboration(r)
        rows.append(
            {
                "problem_id": r.problem_id,
                "fluency": flu,
                "flexibility": flex,
                "originality_within": orig["within_response"],
                "originality_corpus": orig["corpus_relative"],
                "elab_mean_tokens": elab["mean_tokens_per_idea"],
                "elab_justified": elab["any_justification_coverage"],
            }
        )

    # table
    t = Table(title=f"metrics: {rd.name}")
    headers = list(rows[0].keys())
    for h in headers:
        t.add_column(h)
    for row in rows:
        t.add_row(*[_fmt(row[h]) for h in headers])
    console.print(t)

    # aggregate
    agg_t = Table(title="aggregate (mean across problems)")
    for h in headers[1:]:
        agg_t.add_column(h)
    means = {h: _nanmean([row[h] for row in rows]) for h in headers[1:]}
    agg_t.add_row(*[_fmt(means[h]) for h in headers[1:]])
    console.print(agg_t)

    # write
    out = rd / "metrics.json"
    out.write_text(json.dumps({"rows": rows, "aggregate": means}, indent=2))
    console.log(f"wrote {out}")


# ---------------------------------------------------------------------------
# bench judge
# ---------------------------------------------------------------------------

@cli.command("judge")
@click.option("--a", "a_dir", type=click.Path(exists=True, file_okay=False), required=True)
@click.option("--b", "b_dir", type=click.Path(exists=True, file_okay=False), required=True)
@click.option("--battles", type=int, default=3, show_default=True)
@click.option("--problems", "problems_version", default="v1", show_default=True)
@click.option("--seed", type=int, default=0, show_default=True)
@click.option("--out", "out_path", type=click.Path(), default=None, help="path for battle JSON; defaults under runs/")
def cmd_judge(
    a_dir: str,
    b_dir: str,
    battles: int,
    problems_version: str,
    seed: int,
    out_path: str | None,
) -> None:
    """Run pairwise battles between two run directories and record results."""
    a_responses = {r.problem_id: r for r in _load_run(Path(a_dir))}
    b_responses = {r.problem_id: r for r in _load_run(Path(b_dir))}
    _, problems = _load_problems(problems_version)

    judge = PairwiseJudge(rng=random.Random(seed))

    # Sanity-check judge vs generator families on the first overlapping problem.
    common = [p for p in problems if p["id"] in a_responses and p["id"] in b_responses]
    if not common:
        raise click.ClickException("no overlapping problem ids between A and B")
    for w in judge.check_family_disjoint(a_responses[common[0]["id"]], b_responses[common[0]["id"]]):
        console.log(f"[yellow]WARN[/yellow] {w}")

    records: list[BattleRecord] = []
    for p in common:
        pid = p["id"]
        console.log(f"judging {pid}  ({a_responses[pid].system}  vs  {b_responses[pid].system})")
        rec = judge.run(
            problem_text=p["prompt"],
            a=a_responses[pid],
            b=b_responses[pid],
            problem_id=pid,
            battles=battles,
        )
        records.append(rec)

    if out_path is None:
        tag = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
        out_path = str(Path("runs") / f"battles-{tag}.json")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    Path(out_path).write_text(
        json.dumps(
            {
                "problem_set_version": problems_version,
                "seed": seed,
                "battles_per_pair": battles,
                "records": [r.to_json() for r in records],
            },
            indent=2,
        )
    )
    console.log(f"wrote {out_path}")

    # show running leaderboard
    board = EloLeaderboard.from_records(records)
    console.print(board.to_markdown())


# ---------------------------------------------------------------------------
# bench report
# ---------------------------------------------------------------------------

@cli.command("report")
@click.option("--runs", "runs_dir", type=click.Path(exists=True, file_okay=False), default="runs", show_default=True)
@click.option("--out", "out_path", type=click.Path(), default="leaderboard.md", show_default=True)
def cmd_report(runs_dir: str, out_path: str) -> None:
    """Regenerate leaderboard.md from all saved battle files in `runs/`."""
    all_records: list[BattleRecord] = []
    for bf in sorted(Path(runs_dir).glob("battles-*.json")):
        data = json.loads(bf.read_text())
        for rec_json in data.get("records", []):
            all_records.append(_record_from_json(rec_json))

    if not all_records:
        raise click.ClickException(f"no battle files in {runs_dir}/ (battles-*.json)")

    board = EloLeaderboard.from_records(all_records)
    header = (
        "# BrainstormingBench leaderboard\n\n"
        f"_Generated {datetime.now(timezone.utc).isoformat()} from "
        f"{len(all_records)} pairwise battle records._\n\n"
    )
    Path(out_path).write_text(header + board.to_markdown() + "\n")
    console.print(board.to_markdown())
    console.log(f"wrote {out_path}")


# ---------------------------------------------------------------------------
# bench battle — one-shot head-to-head on a single problem
# ---------------------------------------------------------------------------

@cli.command("battle")
@click.option("--a", "a_spec", required=True, help="adapter spec for system A (e.g. a /slash-command)")
@click.option("--b", "b_spec", required=True, help="adapter spec for system B")
@click.option(
    "--problem",
    required=True,
    help="a problem id from the problem set (e.g. product-01) OR a literal prompt in quotes",
)
@click.option("--battles", type=int, default=3, show_default=True)
@click.option("--problems", "problems_version", default="v1", show_default=True)
@click.option("--seed", type=int, default=0, show_default=True)
@click.option(
    "--out",
    "out_dir",
    type=click.Path(),
    default=None,
    help="directory to write A/B responses and battle record (default: runs/battle-<ts>/)",
)
def cmd_battle(
    a_spec: str,
    b_spec: str,
    problem: str,
    battles: int,
    problems_version: str,
    seed: int,
    out_dir: str | None,
) -> None:
    """Run a blinded pairwise battle between two systems on a single problem.

    Designed for interactive use inside a Claude Code session via the
    `/brainstormingbench:battle` slash command. For full v1 evaluation,
    use `bench run` then `bench judge` then `bench report`.
    """
    # Resolve the problem: id lookup first, fall back to literal text.
    _, problems = _load_problems(problems_version)
    matched = next((p for p in problems if p["id"] == problem), None)
    if matched is not None:
        problem_id = matched["id"]
        problem_text = matched["prompt"]
    else:
        problem_id = "custom"
        problem_text = problem

    if out_dir is None:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = str(Path("runs") / f"battle-{ts}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    console.log(f"battle on [bold]{problem_id}[/bold]: {problem_text[:80]}")

    a = _build_adapter(a_spec)
    b = _build_adapter(b_spec)
    console.log(f"A = {a.name}")
    console.log(f"B = {b.name}")

    # Run both generators. Human adapter needs the problem id side-channel.
    for ad in (a, b):
        setattr(ad, "_current_problem_id", problem_id)

    a_resp = a.generate(problem_text)
    a_resp.problem_id = problem_id
    a_resp.save(out / "A")

    b_resp = b.generate(problem_text)
    b_resp.problem_id = problem_id
    b_resp.save(out / "B")
    console.log(
        f"A produced {len(a_resp.ideas)} ideas, B produced {len(b_resp.ideas)} ideas"
    )

    # Judge. Warn if judge family overlaps either generator.
    judge = PairwiseJudge(rng=random.Random(seed))
    for w in judge.check_family_disjoint(a_resp, b_resp):
        console.log(f"[yellow]WARN[/yellow] {w}")

    record = judge.run(
        problem_text=problem_text,
        a=a_resp,
        b=b_resp,
        problem_id=problem_id,
        battles=battles,
    )
    (out / "battle.json").write_text(
        json.dumps(
            {
                "problem_id": problem_id,
                "problem_text": problem_text,
                "problem_set_version": problems_version,
                "seed": seed,
                "battles_per_pair": battles,
                "records": [record.to_json()],
            },
            indent=2,
        )
    )

    # Show verdict.
    winner_map = {"A": a.name, "B": b.name, "tie": "tie"}
    majority = record.majority_winner()
    console.rule("[bold]Verdict[/bold]")
    console.print(f"overall winner: [bold]{winner_map[majority]}[/bold]")
    # sub-criteria tallies
    sub = {"novelty_winner": {}, "diversity_winner": {}, "usefulness_winner": {}}
    for b_ in record.battles:
        for k in sub:
            v = b_.output.get(k)
            if v in ("A", "B", "tie"):
                # position-normalize
                if b_.order == "B_first":
                    v = {"A": "B", "B": "A", "tie": "tie"}[v]
                sub[k][v] = sub[k].get(v, 0) + 1
    for k, tallies in sub.items():
        nice = k.replace("_winner", "")
        ordered = ", ".join(f"{winner_map[w]}={n}" for w, n in sorted(tallies.items(), key=lambda x: -x[1]))
        console.print(f"  {nice}: {ordered}")
    console.log(f"wrote {out}/battle.json (and A/, B/)")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_run(run_dir: Path) -> list[Response]:
    out: list[Response] = []
    for p in sorted(run_dir.glob("*.json")):
        if p.name in {"run_meta.json", "metrics.json"}:
            continue
        try:
            out.append(Response.load(p))
        except (KeyError, json.JSONDecodeError):
            continue
    return out


def _record_from_json(d: dict) -> BattleRecord:
    return BattleRecord(
        a_system=d["a_system"],
        b_system=d["b_system"],
        problem_id=d["problem_id"],
        battles=[SingleBattle(**b) for b in d["battles"]],
    )


def _fmt(v) -> str:
    if isinstance(v, float):
        if v != v:  # NaN
            return "—"
        return f"{v:.3f}"
    return str(v)


def _nanmean(vals: Iterable[float]) -> float:
    xs = [v for v in vals if v == v]  # filter NaN
    if not xs:
        return float("nan")
    return sum(xs) / len(xs)


if __name__ == "__main__":
    cli()
