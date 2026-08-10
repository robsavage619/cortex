from __future__ import annotations

import hashlib
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, cast

import yaml

from cortex.storage.db import connect
from cortex.storage.schemas import _load_vss

logger = logging.getLogger(__name__)

# The vault is a general-purpose knowledge base — most of it (exercise science,
# sabermetrics, frontend) is noise for a factor-research retriever and actively
# crowds out the finance corpus at query time. Index only notes whose frontmatter
# `tags`/`domains` intersect this allowlist.
RESEARCH_TAGS = frozenset(
    {
        "quantitative-finance",
        "factor-investing",
        "investing",
        "asset-pricing",
        "portfolio-theory",
        "cortex",
        "decision-support",
    }
)

# Vault `retrieval_priority` → the existing integer `tier` column, so a note's
# own curation ranking survives into retrieval.
_PRIORITY_TIERS = {
    "critical": 1,
    "high": 2,
    "medium": 3,
    "normal": 3,
    "low": 4,
    "archive": 5,
}

_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?", re.DOTALL)


class Embedder(Protocol):
    """Minimal embedding interface (matches fastembed's TextEmbedding)."""

    def embed(self, texts: list[str]) -> Iterable[Iterable[float]]: ...


_MODEL = "BAAI/bge-small-en-v1.5"
_CHUNK_SIZE = 400
_CHUNK_OVERLAP = 50

# Module-level singleton — loading fastembed the first time downloads ~33 MB
# and compiles ONNX; subsequent calls reuse the cached instance.
_EMBEDDER: Embedder | None = None


@dataclass
class Chunk:
    id: str
    note_path: str
    wikilink: str
    tier: int | None
    text: str


def _get_embedder() -> Embedder:
    global _EMBEDDER
    if _EMBEDDER is None:
        from fastembed import TextEmbedding

        _EMBEDDER = cast(Embedder, TextEmbedding(model_name=_MODEL))
    return _EMBEDDER


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


@dataclass(frozen=True)
class NoteMeta:
    """Frontmatter facts that decide whether and how a note is indexed."""

    tags: frozenset[str]
    tier: int | None
    title: str


def _parse_note(text: str, note_path: Path) -> tuple[NoteMeta, str]:
    """Split a vault note into its frontmatter facts and its embeddable body.

    The YAML block itself is never embedded — it is punctuation, and leaving it
    in poisons the first chunk of every note. The human-readable `title` and
    `summary` are lifted back into the body so that signal is not lost.

    Args:
        text: Raw note contents.
        note_path: Only used for log context and the tier fallback.

    Returns:
        A ``(NoteMeta, body)`` pair. Notes without parseable frontmatter yield
        empty tags, so a tag filter excludes them rather than guessing.
    """
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        return NoteMeta(frozenset(), _tier_from_path(note_path), ""), text

    body = text[match.end() :]
    try:
        loaded = yaml.safe_load(match.group(1))
    except yaml.YAMLError as exc:
        logger.warning("Unparseable frontmatter in %s: %s", note_path, exc)
        return NoteMeta(frozenset(), _tier_from_path(note_path), ""), body
    if not isinstance(loaded, dict):
        return NoteMeta(frozenset(), _tier_from_path(note_path), ""), body

    tags: set[str] = set()
    for key in ("tags", "domains"):
        value = loaded.get(key)
        if isinstance(value, list):
            tags.update(str(v).strip().lower() for v in value if v is not None)
        elif isinstance(value, str):
            tags.update(t.strip().lower() for t in value.split(",") if t.strip())

    priority = loaded.get("retrieval_priority")
    tier = _PRIORITY_TIERS.get(str(priority).strip().lower()) if priority else None
    if tier is None:
        tier = _tier_from_path(note_path)

    title = str(loaded.get("title") or "").strip()
    summary = str(loaded.get("summary") or "").strip()
    # Aliases exist to capture the other names a note goes by, which is exactly
    # the phrasing a query is likely to use ("the t>3 paper", "HLZ 2016").
    raw_aliases = loaded.get("aliases")
    aliases = (
        ", ".join(str(a).strip() for a in raw_aliases if a)
        if isinstance(raw_aliases, list)
        else ""
    )
    preamble = "\n\n".join(p for p in (title, aliases, summary) if p)
    if preamble:
        body = f"{preamble}\n\n{body.lstrip()}"

    return NoteMeta(frozenset(tags), tier, title), body


def index_vault(
    vault_dir: Path,
    *,
    db_path: Path | None = None,
    embedder: Embedder | None = None,
    include_tags: Iterable[str] | None = None,
) -> int:
    """Embed markdown notes under vault_dir into research_chunks.

    Re-indexing is idempotent per source: every chunk row for a re-encountered
    note_path is cleared before reinsertion, so shrinking or editing a note can
    never leave orphan chunks behind.

    Args:
        vault_dir: Directory tree to scan recursively for ``*.md`` notes.
        db_path: DuckDB path; defaults to the configured store.
        embedder: Embedding backend; defaults to the local fastembed model.
        include_tags: Keep only notes whose frontmatter ``tags``/``domains``
            intersect this set. ``None`` indexes every note found.

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

    wanted = frozenset(t.lower() for t in include_tags) if include_tags else None
    embedder = embedder or _get_embedder()
    chunks: list[tuple[str, str, str, int | None, str]] = []
    kept = 0

    for note in notes:
        try:
            text = note.read_text(encoding="utf-8")
        except OSError as exc:
            logger.error("Skipping unreadable note %s: %s", note, exc)
            continue
        meta, body = _parse_note(text, note)
        if wanted is not None and not (meta.tags & wanted):
            continue
        kept += 1
        wikilink = _note_to_wikilink(note, vault_dir)
        # Every chunk carries its note title, so a mid-note chunk still says
        # which paper it came from once it is retrieved out of context.
        prefix = f"{meta.title}. " if meta.title else ""
        for idx, chunk_text in enumerate(_chunk_text(body)):
            chunk_id = hashlib.sha256(f"{note}#{idx}".encode()).hexdigest()[:16]
            chunks.append(
                (chunk_id, str(note), wikilink, meta.tier, f"{prefix}{chunk_text}")
            )

    if wanted is not None:
        logger.info("Kept %d of %d notes matching %s", kept, len(notes), sorted(wanted))

    if not chunks:
        return 0

    texts = [c[4] for c in chunks]
    embeddings = [[float(x) for x in emb] for emb in embedder.embed(texts)]
    if len(embeddings) != len(chunks):
        raise RuntimeError(
            f"Embedder returned {len(embeddings)} vectors for {len(chunks)} chunks"
        )

    now = datetime.now(UTC)
    with connect(db_path) as conn:
        _load_vss(conn)
        # Clear the whole tree, not just the notes we kept: a note that was
        # renamed, deleted, or newly excluded by include_tags must not survive
        # as an orphan chunk that retrieval can still return.
        conn.execute(
            "DELETE FROM research_chunks WHERE note_path LIKE ?",
            [f"{vault_dir}/%"],
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

    logger.info("Indexed %d chunks from %d notes", len(chunks), kept)
    return len(chunks)


def retrieve(
    query: str,
    *,
    k: int = 5,
    db_path: Path | None = None,
    embedder: Embedder | None = None,
) -> list[Chunk]:
    """Return the k most relevant research chunks for query, one per note.

    Chunks are deduplicated by source note: three passages from the same paper
    are one citation, and returning them as three fills a k=2 research panel
    with a single source. Fewer than k results means fewer than k distinct notes
    were relevant, which is the honest answer.

    Falls back to an empty list if the VSS index is not built or no chunks exist.
    """
    # Cheap check: if the vault has no chunks, skip model load entirely.
    with connect(db_path, read_only=True) as conn:
        try:
            n = conn.execute("SELECT COUNT(*) FROM research_chunks").fetchone()
            if n is None or n[0] == 0:
                return []
        except Exception:
            return []

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
                # Over-fetch so the per-note dedupe below still has k distinct
                # notes to draw on when one note dominates the top of the list.
                [query_vec, max(k * 5, 25)],
            ).fetchall()
        except Exception as exc:
            logger.warning("VSS retrieve failed: %s", exc)
            return []

    best: list[Chunk] = []
    seen: set[str] = set()
    for r in rows:
        if r[1] in seen:
            continue
        seen.add(r[1])
        best.append(Chunk(id=r[0], note_path=r[1], wikilink=r[2], tier=r[3], text=r[4]))
        if len(best) == k:
            break
    return best
