from __future__ import annotations

from wst.rag import _chunk_text, _note_to_wikilink, _tier_from_path
from pathlib import Path


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
