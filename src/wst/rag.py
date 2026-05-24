from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

from wst.storage.db import connect
from wst.storage.schemas import _load_vss

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    """Minimal embedding interface (matches fastembed's TextEmbedding)."""

    def embed(self, texts: list[str]) -> Iterable[Iterable[float]]: ...

_MODEL = "BAAI/bge-small-en-v1.5"
_CHUNK_SIZE = 400
_CHUNK_OVERLAP = 50


@dataclass
class Chunk:
    id: str
    note_path: str
    wikilink: str
    tier: int | None
    text: str


def _get_embedder() -> Embedder:
    from fastembed import TextEmbedding

    return cast(Embedder, TextEmbedding(model_name=_MODEL))


def _chunk_text(
    text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP
) -> list[str]:
    words = text.split()
    chunks: list[str] = []
    i = 0
    while i < len(words):
        chunks.append(" ".join(words[i : i + size]))
        i += size - overlap
    return [c for c in chunks if c.strip()]


def _note_to_wikilink(note_path: Path, vault_root: Path) -> str:
    try:
        rel = note_path.relative_to(vault_root)
        stem = rel.with_suffix("").as_posix()
        return f"[[{stem}]]"
    except ValueError:
        return f"[[{note_path.stem}]]"


def _tier_from_path(note_path: Path) -> int | None:
    match = re.search(r"tier[_-]?(\d)", str(note_path), re.IGNORECASE)
    return int(match.group(1)) if match else None


def index_vault(
    vault_dir: Path,
    *,
    db_path: Path | None = None,
    embedder: Embedder | None = None,
) -> int:
    """Embed all markdown notes under vault_dir into research_chunks.

    Re-indexing is idempotent per source: every chunk row for a re-encountered
    note_path is cleared before reinsertion, so shrinking or editing a note can
    never leave orphan chunks behind.

    Args:
        vault_dir: Directory tree to scan recursively for ``*.md`` notes.
        db_path: DuckDB path; defaults to the configured store.
        embedder: Embedding backend; defaults to the local fastembed model.

    Returns:
        The number of chunks indexed.
    """
    if not vault_dir.is_dir():
        logger.warning("Research dir does not exist: %s", vault_dir)
        return 0

    notes = sorted(vault_dir.rglob("*.md"))
    if not notes:
        logger.warning("No markdown notes found in %s", vault_dir)
        return 0

    embedder = embedder or _get_embedder()
    chunks: list[tuple[str, str, str, int | None, str]] = []

    for note in notes:
        try:
            text = note.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Skipping unreadable note %s: %s", note, exc)
            continue
        wikilink = _note_to_wikilink(note, vault_dir)
        tier = _tier_from_path(note)
        for idx, chunk_text in enumerate(_chunk_text(text)):
            chunk_id = hashlib.sha256(f"{note}#{idx}".encode()).hexdigest()[:16]
            chunks.append((chunk_id, str(note), wikilink, tier, chunk_text))

    if not chunks:
        return 0

    texts = [c[4] for c in chunks]
    embeddings = [[float(x) for x in emb] for emb in embedder.embed(texts)]
    if len(embeddings) != len(chunks):
        raise RuntimeError(
            f"Embedder returned {len(embeddings)} vectors for {len(chunks)} chunks"
        )

    source_paths = sorted({c[1] for c in chunks})
    now = datetime.now(UTC)
    with connect(db_path) as conn:
        _load_vss(conn)
        conn.executemany(
            "DELETE FROM research_chunks WHERE note_path = ?",
            [(p,) for p in source_paths],
        )
        conn.executemany(
            """
            INSERT INTO research_chunks
                (id, note_path, wikilink, tier, text, embedding, indexed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (c[0], c[1], c[2], c[3], c[4], emb, now)
                for c, emb in zip(chunks, embeddings, strict=True)
            ],
        )

    logger.info("Indexed %d chunks from %d notes", len(chunks), len(notes))
    return len(chunks)


def retrieve(
    query: str,
    *,
    k: int = 5,
    db_path: Path | None = None,
    embedder: Embedder | None = None,
) -> list[Chunk]:
    """Return the k most relevant research chunks for query.

    Falls back to an empty list if the VSS index is not built or no chunks exist.
    """
    embedder = embedder or _get_embedder()
    query_vec = [float(x) for x in next(iter(embedder.embed([query])))]

    with connect(db_path, read_only=True) as conn:
        try:
            conn.execute("LOAD vss")
            rows = conn.execute(
                """
                SELECT id, note_path, wikilink, tier, text
                FROM research_chunks
                ORDER BY array_cosine_similarity(embedding, ?::FLOAT[384]) DESC
                LIMIT ?
                """,
                [query_vec, k],
            ).fetchall()
        except Exception as exc:
            logger.warning("VSS retrieve failed: %s", exc)
            return []

    return [
        Chunk(id=r[0], note_path=r[1], wikilink=r[2], tier=r[3], text=r[4])
        for r in rows
    ]
