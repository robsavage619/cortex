from __future__ import annotations

import argparse
from datetime import date


def _cmd_db_init(args: argparse.Namespace) -> None:  # noqa: ARG001
    from wst.config import load_settings
    from wst.storage.db import connect
    from wst.storage.schemas import _load_vss, apply_schema

    settings = load_settings()
    print(f"Initialising DB at {settings.duckdb_path}")
    with connect(settings.duckdb_path) as conn:
        apply_schema(conn)
        _load_vss(conn)
    print("Done.")


def _cmd_new(args: argparse.Namespace) -> None:
    from wst.config import load_settings
    from wst.thesis import create

    settings = load_settings()
    conviction = int(args.conviction)
    review = date.fromisoformat(args.review_date)
    t = create(
        tickers=args.ticker,
        author=args.author,
        conviction=conviction,
        claim=args.claim,
        falsifier=args.falsifier,
        review_date=review,
        reasoning=args.reasoning,
        db_path=settings.duckdb_path,
    )
    print(f"Created thesis {t.id}")
    print(f"  Claim: {t.claim}")
    print(f"  Tickers: {', '.join(t.tickers)}")
    print(f"  Review: {t.review_date}")


def _cmd_review(args: argparse.Namespace) -> None:  # noqa: ARG001
    from wst.config import load_settings
    from wst.review import due_for_review

    settings = load_settings()
    queue = due_for_review(db_path=settings.duckdb_path)
    if not queue:
        print("No theses due for review.")
        return
    print(f"{len(queue)} thesis(es) due for review:\n")
    for t in queue:
        tickers = ", ".join(t.tickers)
        print(f"  [{t.review_date}] {t.claim[:55]} ({tickers}) — {t.id[:8]}")


def _cmd_calibration(args: argparse.Namespace) -> None:  # noqa: ARG001
    from wst.calibration import compute
    from wst.config import load_settings

    settings = load_settings()
    report = compute(db_path=settings.duckdb_path)
    if not report.buckets:
        print("No reviewed theses yet — calibration unavailable.")
        return
    print(f"Brier score: {report.brier_score:.4f} (lower = better; 0 = perfect)")
    print(f"Overconfident: {report.overconfident}")
    print()
    print("Conviction buckets:")
    for b in report.buckets:
        bar = "█" * int(b.hit_rate * 20)
        print(
            f"  {b.conviction}/5  {bar:<20}  {b.hit_rate:.0%} ({b.correct}/{b.total})"
        )
    print()
    print("Per author:")
    for author, score in report.per_author.items():
        print(f"  {author}: {score:.4f}")


def _cmd_mirror(args: argparse.Namespace) -> None:  # noqa: ARG001
    from wst.config import load_settings
    from wst.mirror import generate

    settings = load_settings()
    n = generate(settings.vault_dir, db_path=settings.duckdb_path)
    print(f"Mirror: wrote {n} files to {settings.vault_dir}")


def _cmd_rag_index(args: argparse.Namespace) -> None:  # noqa: ARG001
    from wst.config import load_settings
    from wst.rag import index_vault

    settings = load_settings()
    n = index_vault(settings.research_dir, db_path=settings.duckdb_path)
    print(f"Indexed {n} chunks from {settings.research_dir}")


def _cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn
    uvicorn.run(
        "wst.api:app",
        host="127.0.0.1",
        port=args.port,
        reload=args.reload,
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="wst", description="Wall Street Tracker CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("db-init", help="Create / migrate the DuckDB schema")

    new_p = sub.add_parser("new", help="Create a new thesis")
    new_p.add_argument("--ticker", required=True, nargs="+", metavar="TICKER")
    new_p.add_argument("--author", required=True)
    new_p.add_argument("--conviction", required=True, type=int, choices=range(1, 6))
    new_p.add_argument("--claim", required=True)
    new_p.add_argument("--falsifier", required=True)
    new_p.add_argument("--review-date", required=True, metavar="YYYY-MM-DD")
    new_p.add_argument("--reasoning")

    sub.add_parser("review", help="Show theses due for review")
    sub.add_parser("calibration", help="Print calibration scorecard")
    sub.add_parser("mirror", help="Regenerate vault markdown mirror")
    sub.add_parser("rag-index", help="Embed vault notes into research_chunks")

    serve_p = sub.add_parser("serve", help="Start the FastAPI server")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--reload", action="store_true")

    args = parser.parse_args()

    dispatch = {
        "db-init": _cmd_db_init,
        "new": _cmd_new,
        "review": _cmd_review,
        "calibration": _cmd_calibration,
        "mirror": _cmd_mirror,
        "rag-index": _cmd_rag_index,
        "serve": _cmd_serve,
    }
    dispatch[args.command](args)
