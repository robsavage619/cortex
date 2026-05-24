from __future__ import annotations

import hashlib
from pathlib import Path

from cortex.rag import (
    _chunk_text,
    _note_to_wikilink,
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


def test_index_is_idempotent(tmp_path):
    db_path = _fresh_db(tmp_path)
    research = tmp_path / "research"
    research.mkdir()
    (research / "note.md").write_text("alpha beta gamma delta", encoding="utf-8")

    index_vault(research, db_path=db_path, embedder=FakeEmbedder())
    first = _count_chunks(db_path)
    index_vault(research, db_path=db_path, embedder=FakeEmbedder())
    assert _count_chunks(db_path) == first


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
