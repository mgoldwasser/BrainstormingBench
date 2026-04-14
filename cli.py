"""BrainstormingBench researcher CLI — absolute metrics only.

The plugin path (`plugin/scripts/bench.py`) owns `run`, `battle`, `judge`,
and `report` — those are stdlib-only and ship with the Claude Code plugin.
This CLI is the researcher-only path: it depends on numpy and
sentence-transformers (via `metrics/`) and computes the four
creativity-psychology metrics over a run directory produced by the plugin.

Usage:
    python -m cli metrics runs/<dir>/ [--baseline runs/<baseline_dir>/]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Iterable

from metrics._types import Response, load_response


def _load_run(run_dir: Path) -> list[Response]:
    out: list[Response] = []
    for p in sorted(run_dir.glob("*.json")):
        if p.name in {"run_meta.json", "metrics.json"}:
            continue
        try:
            out.append(load_response(p))
        except (KeyError, json.JSONDecodeError):
            continue
    return out


def _fmt(v) -> str:
    if isinstance(v, float):
        if math.isnan(v):
            return "—"
        return f"{v:.3f}"
    return str(v)


def _nanmean(vals: Iterable[float]) -> float:
    xs = [v for v in vals if not (isinstance(v, float) and math.isnan(v))]
    if not xs:
        return float("nan")
    return sum(xs) / len(xs)


def _print_table(title: str, headers: list[str], rows: list[list[str]]) -> None:
    widths = [len(h) for h in headers]
    for r in rows:
        for i, cell in enumerate(r):
            if len(cell) > widths[i]:
                widths[i] = len(cell)
    sep = "  "
    print(f"\n{title}")
    print(sep.join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    print(sep.join("-" * w for w in widths))
    for r in rows:
        print(sep.join(r[i].ljust(widths[i]) for i in range(len(headers))))


def cmd_metrics(run_dir: str, baseline: str | None) -> int:
    from metrics import elaboration, flexibility, fluency, originality
    from metrics.originality import build_obvious_corpus

    rd = Path(run_dir)
    responses = _load_run(rd)
    if not responses:
        print(f"error: no responses in {rd}", file=sys.stderr)
        return 1

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

    headers = list(rows[0].keys())
    table_rows = [[_fmt(row[h]) for h in headers] for row in rows]
    _print_table(f"metrics: {rd.name}", headers, table_rows)

    means = {h: _nanmean([row[h] for row in rows]) for h in headers[1:]}
    _print_table(
        "aggregate (mean across problems)",
        headers[1:],
        [[_fmt(means[h]) for h in headers[1:]]],
    )

    out = rd / "metrics.json"
    out.write_text(json.dumps({"rows": rows, "aggregate": means}, indent=2))
    print(f"\nwrote {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bench",
        description="BrainstormingBench researcher CLI (absolute metrics).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_metrics = sub.add_parser(
        "metrics",
        help="compute fluency, flexibility, originality, elaboration over a run dir",
    )
    p_metrics.add_argument("run_dir")
    p_metrics.add_argument(
        "--baseline",
        default=None,
        help="baseline run dir (typically plain_claude) for corpus-relative originality",
    )

    args = parser.parse_args(argv)
    if args.cmd == "metrics":
        return cmd_metrics(args.run_dir, args.baseline)
    parser.error(f"unknown command: {args.cmd}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
