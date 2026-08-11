from __future__ import annotations

from cortex.evidence import (
    WILDCARD,
    build_evidence,
    caveats_for,
    evidence_for,
    sync_evidence,
)
from cortex.storage.db import connect
from cortex.storage.schemas import apply_schema

_PAPER = """---
type: source-summary
title: "Best Ideas"
summary: "Cohen, Polk & Silli. High-conviction positions outperform."
cortex_factors: [fund]
confidence: high
---

Body.
"""

_FINDING = """---
type: research-finding
title: "74% of the Fund Factor Is One Manager"
summary: "Renaissance supplies most of the rows."
cortex_factors: [fund]
confidence: high
current_verdict: "structural concern; no change made"
---

Body.
"""

_METHODOLOGY = """---
type: research-finding
title: "Deriving the Promotion Bar"
summary: "The bar should be derived per run."
cortex_factors: ["*"]
confidence: high
current_verdict: "bar is defensible but underived"
---

Body.
"""

_UNTAGGED = """---
type: source-summary
title: "Something Else"
tags: [quantitative-finance]
---

Body.
"""


def _vault(tmp_path, notes):
    d = tmp_path / "wiki"
    d.mkdir(exist_ok=True)
    for name, text in notes.items():
        (d / f"{name}.md").write_text(text, encoding="utf-8")
    return d


def test_build_evidence_reads_cortex_factors(tmp_path):
    d = _vault(tmp_path, {"best-ideas": _PAPER, "other": _UNTAGGED})
    ev = build_evidence(d)
    assert len(ev) == 1
    assert ev[0].factor == "fund"
    assert ev[0].wikilink == "[[best-ideas]]"
    assert ev[0].title == "Best Ideas"


def test_build_evidence_fans_out_multi_factor_notes(tmp_path):
    note = _PAPER.replace("cortex_factors: [fund]", "cortex_factors: [fund, congress]")
    d = _vault(tmp_path, {"n": note})
    assert {e.factor for e in build_evidence(d)} == {"fund", "congress"}


def test_wildcard_must_be_quoted_yaml(tmp_path):
    """A bare `*` in YAML flow sequence is an alias token and fails to parse.

    Writing `cortex_factors: [*]` silently drops the note from BOTH the
    evidence map and the RAG index, because frontmatter parsing raises.
    """
    import yaml

    with __import__("pytest").raises(yaml.YAMLError):
        yaml.safe_load("cortex_factors: [*]")
    assert yaml.safe_load('cortex_factors: ["*"]') == {"cortex_factors": ["*"]}

    d = _vault(tmp_path, {"m": _METHODOLOGY})
    assert build_evidence(d)[0].factor == WILDCARD


def test_build_evidence_skips_unparseable_frontmatter(tmp_path):
    d = _vault(tmp_path, {"bad": "---\ncortex_factors: [unclosed\n---\n\nbody\n"})
    assert build_evidence(d) == []


def test_build_evidence_missing_dir(tmp_path):
    assert build_evidence(tmp_path / "nope") == []


def test_is_caveat_only_for_findings_with_a_verdict(tmp_path):
    d = _vault(tmp_path, {"paper": _PAPER, "finding": _FINDING})
    by_title = {e.title: e for e in build_evidence(d)}
    assert not by_title["Best Ideas"].is_caveat
    assert by_title["74% of the Fund Factor Is One Manager"].is_caveat


def test_sync_and_read_back(tmp_path):
    db = tmp_path / "e.db"
    with connect(db) as conn:
        apply_schema(conn)
    d = _vault(tmp_path, {"p": _PAPER, "f": _FINDING, "m": _METHODOLOGY})

    assert sync_evidence(db, d) == 3
    items = evidence_for(db, "fund")
    # wildcard methodology is included but sorts last
    assert len(items) == 3
    assert items[-1].factor == WILDCARD
    # caveats sort ahead of plain citations
    assert items[0].is_caveat


def test_caveats_for_excludes_global_methodology(tmp_path):
    """A finding tagged for every factor is a real caveat but a global one.

    Surfacing it as a fund-specific caveat would bury "distrust this number"
    under "distrust all numbers".
    """
    db = tmp_path / "c.db"
    with connect(db) as conn:
        apply_schema(conn)
    d = _vault(tmp_path, {"f": _FINDING, "m": _METHODOLOGY})
    sync_evidence(db, d)

    cv = caveats_for(db, "fund")
    assert len(cv) == 1
    assert cv[0].title == "74% of the Fund Factor Is One Manager"


def test_sync_is_a_full_rebuild(tmp_path):
    """A note that loses its cortex_factors must stop claiming the factor."""
    db = tmp_path / "r.db"
    with connect(db) as conn:
        apply_schema(conn)
    d = _vault(tmp_path, {"p": _PAPER})
    assert sync_evidence(db, d) == 1

    (d / "p.md").write_text(_UNTAGGED, encoding="utf-8")
    assert sync_evidence(db, d) == 0
    assert evidence_for(db, "fund") == []


def test_evidence_for_unknown_factor_is_empty(tmp_path):
    db = tmp_path / "u.db"
    with connect(db) as conn:
        apply_schema(conn)
    sync_evidence(db, _vault(tmp_path, {"p": _PAPER}))
    assert evidence_for(db, "nonexistent", include_wildcard=False) == []


def test_evidence_for_missing_table_degrades(tmp_path):
    db = tmp_path / "old.db"
    with connect(db) as conn:
        conn.execute("CREATE TABLE placeholder (x INTEGER)")
    assert evidence_for(db, "fund") == []
