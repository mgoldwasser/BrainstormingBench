"""Adapter-layer tests. Exercise pure logic — no network calls."""

from __future__ import annotations

from pathlib import Path

import pytest

from adapters.base import Idea, Response, parse_ideas


# ---------------------------------------------------------------------------
# parse_ideas
# ---------------------------------------------------------------------------

def test_parse_numbered_list() -> None:
    raw = (
        "Here are some ideas:\n"
        "1. Sell coffee alongside the books.\n"
        "2. Host author events weekly.\n"
        "3) Partner with local schools.\n"
    )
    ideas = parse_ideas(raw)
    assert [i.text for i in ideas] == [
        "Sell coffee alongside the books.",
        "Host author events weekly.",
        "Partner with local schools.",
    ]


def test_parse_bulleted_list_with_continuation() -> None:
    raw = (
        "- First idea, which\n"
        "  wraps across lines.\n"
        "- Second idea.\n"
        "* Third idea.\n"
    )
    ideas = parse_ideas(raw)
    assert len(ideas) == 3
    assert "wraps across lines" in ideas[0].text
    assert ideas[2].text == "Third idea."


def test_parse_paragraph_fallback() -> None:
    raw = "Idea one, at length.\n\nIdea two, also at length.\n"
    ideas = parse_ideas(raw)
    assert len(ideas) == 2


def test_parse_empty() -> None:
    assert parse_ideas("") == []
    assert parse_ideas("   \n  ") == []


def test_parse_single_blob_sentence_split() -> None:
    raw = "Idea one. Idea two! Idea three?"
    ideas = parse_ideas(raw)
    assert len(ideas) == 3


def test_parse_preserves_origin() -> None:
    raw = "1. Alpha\n2. Beta"
    ideas = parse_ideas(raw, origin="stoner_circle")
    assert all(i.origin == "stoner_circle" for i in ideas)


# ---------------------------------------------------------------------------
# Response round-trip
# ---------------------------------------------------------------------------

def test_response_save_load_round_trip(tmp_path: Path) -> None:
    r = Response(
        problem_id="product-01",
        system="plain_claude@0.1",
        ideas=[Idea(text="Sell coffee."), Idea(text="Host events.", origin="x")],
        raw="raw output here",
        meta={"latency_s": 1.23, "model": "claude-opus-4-6"},
    )
    path = r.save(tmp_path)
    assert path.name == "product-01.json"

    loaded = Response.load(path)
    assert loaded.problem_id == r.problem_id
    assert loaded.system == r.system
    assert [i.text for i in loaded.ideas] == [i.text for i in r.ideas]
    assert loaded.raw == r.raw
    assert loaded.meta == r.meta


# ---------------------------------------------------------------------------
# HumanAdapter
# ---------------------------------------------------------------------------

def test_human_adapter_reads_file(tmp_path: Path) -> None:
    from adapters.human import HumanAdapter

    (tmp_path / "product-01.txt").write_text("1. Alpha\n2. Beta\n3. Gamma\n")
    ad = HumanAdapter(responses_dir=tmp_path, author_tag="alice")
    ad._current_problem_id = "product-01"
    r = ad.generate("How might a small indie bookstore compete with Amazon?")
    assert r.system == "human[alice]@0.1"
    assert len(r.ideas) == 3
    assert r.ideas[0].text == "Alpha"
    assert r.meta["author"] == "alice"


def test_human_adapter_missing_file(tmp_path: Path) -> None:
    from adapters.human import HumanAdapter

    ad = HumanAdapter(responses_dir=tmp_path)
    ad._current_problem_id = "does-not-exist"
    with pytest.raises(FileNotFoundError):
        ad.generate("whatever")


def test_human_adapter_nonexistent_dir(tmp_path: Path) -> None:
    from adapters.human import HumanAdapter

    with pytest.raises(FileNotFoundError):
        HumanAdapter(responses_dir=tmp_path / "nope")
