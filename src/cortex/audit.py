"""Read-only data-integrity audit over the CORTEX DuckDB.

Quantifies known ingestion defects before and after remediation:
amendment duplicates in congress_trades, malformed tickers, dedupe-collapse
baselines for insider/activist tables, fund action distribution, executive
LLM-analysis coverage, and fabricated candidate ranks. Never mutates data.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Plausible US equity ticker: 1-5 capitals, optional class suffix (BRK.B, BF/B).
_TICKER_RE = re.compile(r"^[A-Z]{1,5}([./][A-Z]{1,2})?$")


@dataclass
class AuditReport:
    sections: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps(self.sections, indent=2, default=str)


def _congress_amendment_duplicates(conn: Any) -> dict[str, Any]:
    """Groups identical on the natural trade key but with >1 report_url.

    These are almost certainly amended Senate/House reports stored twice —
    the dedupe id includes report_url, and an amendment gets a fresh URL.
    """
    rows = conn.execute(
        """
        SELECT chamber,
               count(*)                        AS dup_groups,
               sum(n_rows - 1)                 AS excess_rows
        FROM (
            SELECT chamber, count(*) AS n_rows
            FROM congress_trades
            GROUP BY senator, ticker, transaction_type, amount,
                     transaction_date, chamber
            HAVING count(DISTINCT report_url) > 1
        )
        GROUP BY chamber
        """
    ).fetchall()
    total = conn.execute("SELECT count(*) FROM congress_trades").fetchone()[0]
    by_chamber = {r[0]: {"dup_groups": r[1], "excess_rows": r[2]} for r in rows}
    return {
        "total_rows": total,
        "by_chamber": by_chamber,
        "dup_groups": sum(v["dup_groups"] for v in by_chamber.values()),
        "excess_rows": sum(v["excess_rows"] for v in by_chamber.values()),
    }


def _suspicious_tickers(conn: Any) -> dict[str, Any]:
    """Congress tickers failing the ticker pattern, plus universe coverage.

    Pattern failure = probable parse corruption. Absence from the S&P
    500/400 lists is informational only — members legally trade anything.
    """
    tickers = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT ticker FROM congress_trades"
        ).fetchall()
    ]
    bad = sorted(t for t in tickers if not _TICKER_RE.match(t or ""))
    bad_rows = 0
    if bad:
        placeholders = ",".join("?" for _ in bad)
        bad_rows = conn.execute(
            f"SELECT count(*) FROM congress_trades WHERE ticker IN ({placeholders})",
            bad,
        ).fetchone()[0]

    known: set[str] = set()
    universe_note = "unavailable (fetch failed or offline)"
    try:
        from cortex.sources.universe import sp400_tickers, sp500_tickers

        known = set(sp500_tickers()) | set(sp400_tickers())
        if known:
            universe_note = f"S&P 500 ∪ 400 ({len(known)} tickers)"
    except Exception as exc:  # noqa: BLE001 - audit must not die on network
        log.warning("Audit: universe fetch failed — %s", exc)

    outside = sorted(
        t for t in tickers if _TICKER_RE.match(t or "") and known and t not in known
    )
    return {
        "distinct_tickers": len(tickers),
        "pattern_fail_tickers": len(bad),
        "pattern_fail_rows": bad_rows,
        "pattern_fail_top20": bad[:20],
        "universe": universe_note,
        "outside_universe_tickers": len(outside) if known else None,
        "outside_universe_note": "informational — members trade non-index names",
    }


def _collapse_baselines(conn: Any) -> dict[str, Any]:
    """Row counts for tables whose dedupe keys collapsed records at ingest.

    Same-day multi-lot insider buys and same-day multi-filer 13D stakes were
    silently merged BEFORE storage, so the lost rows cannot be counted from
    the DB. These counts are the before-numbers; the Phase 1 rebuild re-sync
    delta is the actual damage measurement.
    """
    insider = conn.execute("SELECT count(*) FROM insider_buys").fetchone()[0]
    activist = conn.execute("SELECT count(*) FROM activist_stakes").fetchone()[0]
    return {
        "insider_buys_rows": insider,
        "activist_stakes_rows": activist,
        "note": (
            "collisions were collapsed at ingest and are unrecoverable here; "
            "measure damage as the Phase 1 --rebuild re-sync delta"
        ),
    }


def _fund_actions(conn: Any) -> dict[str, Any]:
    """fund_holdings distribution by action — EXIT rows are clobber-at-risk."""
    rows = conn.execute(
        "SELECT action, count(*) FROM fund_holdings GROUP BY action ORDER BY 2 DESC"
    ).fetchall()
    return {
        "by_action": {r[0]: r[1] for r in rows},
        "exit_rows": next((r[1] for r in rows if r[0] == "EXIT"), 0),
    }


def _executive_analysis(conn: Any) -> dict[str, Any]:
    """executive_mentions: NULL `meaningful` conflates never-analyzed with off."""
    total, null_meaningful = conn.execute(
        "SELECT count(*), count(*) FILTER (meaningful IS NULL) "
        "FROM executive_mentions"
    ).fetchone()
    return {
        "total_rows": total,
        "meaningful_null": null_meaningful,
        "analyzed": total - null_meaningful,
    }


def _candidate_rank_fakes(conn: Any) -> dict[str, Any]:
    """candidates rows with rank > 30 — force-included fabricated positions."""
    rows = conn.execute(
        "SELECT ticker, composite_rank FROM candidates "
        "WHERE composite_rank > 30 ORDER BY composite_rank"
    ).fetchall()
    return {
        "rows_over_rank_30": len(rows),
        "tickers": [f"{r[0]}#{r[1]}" for r in rows],
    }


def run_audit(db_path: Path) -> AuditReport:
    """Run all integrity checks against a read-only connection."""
    from cortex.storage.db import connect

    report = AuditReport()
    with connect(db_path, read_only=True) as conn:
        report.sections["congress_amendment_duplicates"] = (
            _congress_amendment_duplicates(conn)
        )
        report.sections["suspicious_tickers"] = _suspicious_tickers(conn)
        report.sections["collapse_baselines"] = _collapse_baselines(conn)
        report.sections["fund_actions"] = _fund_actions(conn)
        report.sections["executive_analysis"] = _executive_analysis(conn)
        report.sections["candidate_rank_fakes"] = _candidate_rank_fakes(conn)
    return report


def format_report(report: AuditReport) -> str:
    """Render the audit as a plain-text section-per-check report."""
    out: list[str] = ["CORTEX DATA-INTEGRITY AUDIT (read-only)", "=" * 60]
    for name, section in report.sections.items():
        out.append("")
        out.append(f"[{name}]")
        for key, value in section.items():
            if isinstance(value, dict):
                out.append(f"  {key}:")
                for k, v in value.items():
                    out.append(f"    {k}: {v}")
            elif isinstance(value, list):
                out.append(f"  {key}: {', '.join(map(str, value)) or '(none)'}")
            else:
                out.append(f"  {key}: {value}")
    out.append("")
    out.append("=" * 60)
    return "\n".join(out)
