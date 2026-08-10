from __future__ import annotations

import hashlib
from pathlib import Path

from cortex.rag import (
    _chunk_text,
    _note_to_wikilink,
    _parse_note,
    _tier_from_path,
    index_vault,
    retrieve,
)
from cortex.storage.db import connect
from cortex.storage.schemas import apply_schema

_DIM = 384


class FakeEmbedder:
    """Deterministic 384-dim embedder — keyword-biased, no model download."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        vecs: list[list[float]] = []
        for text in texts:
            vec = [0.0] * _DIM
            for token in text.lower().split():
                h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
                vec[h % _DIM] += 1.0
            vecs.append(vec)
        return vecs


def _fresh_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "rag.db"
    with connect(db_path) as conn:
        apply_schema(conn)
    return db_path


def _count_chunks(db_path: Path) -> int:
    with connect(db_path, read_only=True) as conn:
        return conn.execute("SELECT COUNT(*) FROM research_chunks").fetchone()[0]


def test_chunk_text_basic():
    words = ["word"] * 500
    text = " ".join(words)
    chunks = _chunk_text(text, size=400, overlap=50)
    assert len(chunks) >= 2
    for c in chunks:
        assert c.strip()


def test_chunk_text_short():
    chunks = _chunk_text("hello world", size=400, overlap=50)
    assert len(chunks) == 1
    assert chunks[0] == "hello world"


def test_chunk_text_empty():
    assert _chunk_text("") == []


def test_note_to_wikilink_relative(tmp_path):
    vault = tmp_path / "vault"
    vault.mkdir()
    note = vault / "investing" / "research" / "thinking-in-bets.md"
    note.parent.mkdir(parents=True)
    link = _note_to_wikilink(note, vault)
    assert link == "[[investing/research/thinking-in-bets]]"


def test_note_to_wikilink_outside_vault(tmp_path):
    vault = tmp_path / "vault"
    note = tmp_path / "outside" / "note.md"
    link = _note_to_wikilink(note, vault)
    assert link == "[[note]]"


def test_tier_from_path_detects_tier():
    assert _tier_from_path(Path("tier1/thinking-in-bets.md")) == 1
    assert _tier_from_path(Path("tier-3/paper.md")) == 3
    assert _tier_from_path(Path("Tier_2_notes.md")) == 2


def test_tier_from_path_none_when_absent():
    assert _tier_from_path(Path("research/some-paper.md")) is None


def test_index_vault_empty_dir_returns_zero(tmp_path):
    db_path = _fresh_db(tmp_path)
    research = tmp_path / "research"
    research.mkdir()
    assert index_vault(research, db_path=db_path, embedder=FakeEmbedder()) == 0


def test_index_vault_missing_dir_returns_zero(tmp_path):
    db_path = _fresh_db(tmp_path)
    missing = tmp_path / "nope"
    assert index_vault(missing, db_path=db_path, embedder=FakeEmbedder()) == 0


def test_index_and_retrieve(tmp_path):
    db_path = _fresh_db(tmp_path)
    research = tmp_path / "research"
    research.mkdir()
    (research / "bets.md").write_text(
        "thesis as bet resulting decision journal calibration", encoding="utf-8"
    )
    (research / "moat.md").write_text(
        "competitive advantage moat pricing power switching costs", encoding="utf-8"
    )

    n = index_vault(research, db_path=db_path, embedder=FakeEmbedder())
    assert n == 2

    hits = retrieve(
        "decision journal calibration", k=1, db_path=db_path, embedder=FakeEmbedder()
    )
    assert len(hits) == 1
    assert hits[0].wikilink == "[[bets]]"


def test_retrieve_returns_one_chunk_per_note(tmp_path):
    db_path = _fresh_db(tmp_path)
    research = tmp_path / "research"
    research.mkdir()
    # one long note that would otherwise occupy every slot
    (research / "long.md").write_text(
        " ".join(["calibration"] * 2000), encoding="utf-8"
    )
    (research / "other.md").write_text(
        "calibration appears here once too", encoding="utf-8"
    )

    index_vault(research, db_path=db_path, embedder=FakeEmbedder())
    hits = retrieve("calibration", k=3, db_path=db_path, embedder=FakeEmbedder())

    assert len(hits) == 2
    assert {h.wikilink for h in hits} == {"[[long]]", "[[other]]"}


def test_index_is_idempotent(tmp_path):
    db_path = _fresh_db(tmp_path)
    research = tmp_path / "research"
    research.mkdir()
    (research / "note.md").write_text("alpha beta gamma delta", encoding="utf-8")

    index_vault(research, db_path=db_path, embedder=FakeEmbedder())
    first = _count_chunks(db_path)
    index_vault(research, db_path=db_path, embedder=FakeEmbedder())
    assert _count_chunks(db_path) == first


_NOTE_WITH_FRONTMATTER = """---
type: source-summary
title: "The Gross Profitability Premium"
summary: "Novy-Marx (2013). Gross profitability predicts the cross-section."
tags: [quantitative-finance, factor-investing, quality]
retrieval_priority: critical
---

Body text about profitable firms earning higher returns.
"""

_NOTE_OFF_TOPIC = """---
title: "Annual Plan Periodization"
tags: [exercise-science, training]
retrieval_priority: high
---

Body text about macrocycles and tapering.
"""


def test_parse_note_extracts_tags_and_tier(tmp_path):
    meta, body = _parse_note(_NOTE_WITH_FRONTMATTER, tmp_path / "novy-marx.md")
    assert "quantitative-finance" in meta.tags
    assert "factor-investing" in meta.tags
    assert meta.tier == 1
    assert meta.title == "The Gross Profitability Premium"
    assert "---" not in body
    assert "type: source-summary" not in body
    # title and summary survive the frontmatter strip
    assert "Gross Profitability Premium" in body
    assert "Novy-Marx (2013)" in body
    assert "profitable firms" in body


def test_parse_note_domains_count_as_tags(tmp_path):
    note = "---\ndomains: [quantitative-finance]\n---\n\nbody\n"
    meta, _ = _parse_note(note, tmp_path / "n.md")
    assert meta.tags == frozenset({"quantitative-finance"})


def test_parse_note_without_frontmatter_is_untagged(tmp_path):
    meta, body = _parse_note("just prose, no yaml", tmp_path / "n.md")
    assert meta.tags == frozenset()
    assert meta.tier is None
    assert body == "just prose, no yaml"


def test_parse_note_malformed_frontmatter_degrades(tmp_path):
    note = "---\ntags: [unclosed\n---\n\nbody text\n"
    meta, body = _parse_note(note, tmp_path / "n.md")
    assert meta.tags == frozenset()
    assert "body text" in body


def test_parse_note_falls_back_to_path_tier(tmp_path):
    meta, _ = _parse_note("---\ntitle: x\n---\n\nbody\n", tmp_path / "tier2" / "n.md")
    assert meta.tier == 2


def test_index_vault_filters_by_tag(tmp_path):
    db_path = _fresh_db(tmp_path)
    research = tmp_path / "wiki"
    research.mkdir()
    (research / "novy-marx.md").write_text(_NOTE_WITH_FRONTMATTER, encoding="utf-8")
    (research / "periodization.md").write_text(_NOTE_OFF_TOPIC, encoding="utf-8")

    n = index_vault(
        research,
        db_path=db_path,
        embedder=FakeEmbedder(),
        include_tags={"quantitative-finance"},
    )
    assert n == 1

    with connect(db_path, read_only=True) as conn:
        rows = conn.execute("SELECT wikilink, tier FROM research_chunks").fetchall()
    assert rows == [("[[novy-marx]]", 1)]


def test_index_vault_without_filter_keeps_everything(tmp_path):
    db_path = _fresh_db(tmp_path)
    research = tmp_path / "wiki"
    research.mkdir()
    (research / "novy-marx.md").write_text(_NOTE_WITH_FRONTMATTER, encoding="utf-8")
    (research / "periodization.md").write_text(_NOTE_OFF_TOPIC, encoding="utf-8")

    assert index_vault(research, db_path=db_path, embedder=FakeEmbedder()) == 2


def test_indexed_chunks_carry_note_title(tmp_path):
    db_path = _fresh_db(tmp_path)
    research = tmp_path / "wiki"
    research.mkdir()
    long_body = " ".join(["profitability"] * 900)
    (research / "novy-marx.md").write_text(
        _NOTE_WITH_FRONTMATTER + long_body, encoding="utf-8"
    )

    index_vault(research, db_path=db_path, embedder=FakeEmbedder())
    with connect(db_path, read_only=True) as conn:
        texts = [
            r[0] for r in conn.execute("SELECT text FROM research_chunks").fetchall()
        ]
    assert len(texts) >= 2
    # even the tail chunk says which note it came from
    assert all(t.startswith("The Gross Profitability Premium.") for t in texts)


def test_reindex_drops_notes_that_stop_matching(tmp_path):
    db_path = _fresh_db(tmp_path)
    research = tmp_path / "wiki"
    research.mkdir()
    note = research / "note.md"
    note.write_text(_NOTE_WITH_FRONTMATTER, encoding="utf-8")

    index_vault(
        research,
        db_path=db_path,
        embedder=FakeEmbedder(),
        include_tags={"quantitative-finance"},
    )
    assert _count_chunks(db_path) == 1

    # retagged out of the research corpus — its chunks must not linger
    note.write_text(_NOTE_OFF_TOPIC, encoding="utf-8")
    (research / "keeper.md").write_text(_NOTE_WITH_FRONTMATTER, encoding="utf-8")
    index_vault(
        research,
        db_path=db_path,
        embedder=FakeEmbedder(),
        include_tags={"quantitative-finance"},
    )

    with connect(db_path, read_only=True) as conn:
        links = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT wikilink FROM research_chunks"
            ).fetchall()
        ]
    assert links == ["[[keeper]]"]


def test_reindex_drops_deleted_notes(tmp_path):
    db_path = _fresh_db(tmp_path)
    research = tmp_path / "wiki"
    research.mkdir()
    (research / "a.md").write_text(_NOTE_WITH_FRONTMATTER, encoding="utf-8")
    (research / "b.md").write_text(_NOTE_WITH_FRONTMATTER, encoding="utf-8")
    index_vault(research, db_path=db_path, embedder=FakeEmbedder())
    assert _count_chunks(db_path) == 2

    (research / "b.md").unlink()
    index_vault(research, db_path=db_path, embedder=FakeEmbedder())
    assert _count_chunks(db_path) == 1


def test_reindex_shrunk_note_leaves_no_orphans(tmp_path):
    db_path = _fresh_db(tmp_path)
    research = tmp_path / "research"
    research.mkdir()
    note = research / "note.md"
    note.write_text(" ".join(["word"] * 1000), encoding="utf-8")

    index_vault(research, db_path=db_path, embedder=FakeEmbedder())
    big = _count_chunks(db_path)
    assert big >= 2

    note.write_text("just one short chunk now", encoding="utf-8")
    index_vault(research, db_path=db_path, embedder=FakeEmbedder())
    assert _count_chunks(db_path) == 1
