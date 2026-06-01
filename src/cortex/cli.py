from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)


def _cmd_db_init(args: argparse.Namespace) -> None:  # noqa: ARG001
    from cortex.config import load_settings
    from cortex.storage.db import connect
    from cortex.storage.schemas import _load_vss, apply_schema

    settings = load_settings()
    print(f"Initialising DB at {settings.duckdb_path}")
    with connect(settings.duckdb_path) as conn:
        apply_schema(conn)
        _load_vss(conn)
    print("Done.")


def _cmd_new(args: argparse.Namespace) -> None:
    from cortex.config import load_settings
    from cortex.thesis import create

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
    from cortex.config import load_settings
    from cortex.review import due_for_review

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
    from cortex.calibration import compute
    from cortex.config import load_settings

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
    from cortex.config import load_settings
    from cortex.mirror import generate

    settings = load_settings()
    n = generate(settings.vault_dir, db_path=settings.duckdb_path)
    print(f"Mirror: wrote {n} files to {settings.vault_dir}")


def _cmd_rag_index(args: argparse.Namespace) -> None:  # noqa: ARG001
    from cortex.config import load_settings
    from cortex.rag import index_vault

    settings = load_settings()
    n = index_vault(settings.research_dir, db_path=settings.duckdb_path)
    print(f"Indexed {n} chunks from {settings.research_dir}")


def _cmd_discover(args: argparse.Namespace) -> None:
    from cortex.config import load_settings
    from cortex.discovery import run_discovery

    settings = load_settings()
    log.info("Starting CORTEX discovery pipeline…")
    from cortex.thesis import list_theses

    active = list_theses(status="open", db_path=settings.duckdb_path) + list_theses(
        status="pending", db_path=settings.duckdb_path
    )
    force = list({t for thesis in active for t in thesis.tickers})

    candidates = run_discovery(
        settings.duckdb_path,
        top_n=args.top_n,
        prefilter_n=args.prefilter_n,
        force_include=force,
    )
    print(f"Discovered {len(candidates)} candidates")
    for c in candidates:
        mom = f"{c.momentum_12_1:+.1%}" if c.momentum_12_1 is not None else "    —"
        ey = f"{c.earnings_yield:.3f}" if c.earnings_yield is not None else "  —"
        print(
            f"  #{c.composite_rank:2d} {c.ticker:<6} score={c.composite_score:+.3f}"
            f"  mom={mom}  ey={ey}"
        )


def _cmd_congress_sync(args: argparse.Namespace) -> None:
    from cortex.config import load_settings
    from cortex.sources.congress import (
        CongressSourceError,
        backfill_senate_trades,
        fetch_senate_trades,
        recent_window,
        store_trades,
    )

    settings = load_settings()
    try:
        if args.backfill_from_year:
            total = backfill_senate_trades(
                settings.duckdb_path,
                start_year=args.backfill_from_year,
                max_reports_per_window=args.max_reports,
                progress=lambda msg: print(f"  {msg}"),
            )
            yr = args.backfill_from_year
            print(f"Backfill complete — {total} new trades since {yr}")
        else:
            since = recent_window(args.since_days)
            log.info("Scraping Senate eFD since %s…", since)
            trades = fetch_senate_trades(since=since, max_reports=args.max_reports)
            new = store_trades(trades, settings.duckdb_path)
            print(f"Synced {len(trades)} trades ({new} new) since {since}")
    except CongressSourceError as exc:
        print(f"Sync failed: {exc}")
        raise SystemExit(1) from exc


def _cmd_house_sync(args: argparse.Namespace) -> None:
    from cortex.config import load_settings
    from cortex.sources.house import (
        HouseSourceError,
        backfill_house_trades,
        fetch_house_trades,
        store_house_trades,
    )

    settings = load_settings()
    try:
        if args.backfill_from_year:
            total = backfill_house_trades(
                settings.duckdb_path,
                start_year=args.backfill_from_year,
                progress=lambda msg: print(f"  {msg}"),
            )
            print(
                f"Backfill complete — {total} new trades since {args.backfill_from_year}"
            )
        else:
            since = date.today() - timedelta(days=args.since_days)
            log.info("Fetching House PTR filings since %s…", since)
            trades = fetch_house_trades(since=since, max_pdfs=args.max_pdfs)
            new = store_house_trades(trades, settings.duckdb_path)
            print(f"Synced {len(trades)} trades ({new} new) since {since}")
    except HouseSourceError as exc:
        print(f"Sync failed: {exc}")
        raise SystemExit(1) from exc


def _cmd_funds_sync(args: argparse.Namespace) -> None:  # noqa: ARG001
    from cortex.config import load_settings
    from cortex.sources.funds import MANAGERS, sync_all_managers

    settings = load_settings()
    print(f"Syncing 13F moves for {len(MANAGERS)} managers…")
    new = sync_all_managers(settings.duckdb_path)
    print(f"Funds sync complete — {new} new/updated moves")


def _cmd_insiders_sync(args: argparse.Namespace) -> None:
    from cortex.config import load_settings
    from cortex.sources.insiders import fetch_insider_buys_datasets
    from cortex.sources.universe import sp500_tickers

    settings = load_settings()
    universe = set(sp500_tickers())
    print(
        f"Fetching Form 4 purchases for {len(universe)} tickers "
        f"from {args.from_year} via SEC quarterly datasets…",
        flush=True,
    )
    total_new = fetch_insider_buys_datasets(
        universe, settings.duckdb_path, from_year=args.from_year
    )
    print(f"Insiders sync complete — {total_new} new rows", flush=True)


def _cmd_activism_sync(args: argparse.Namespace) -> None:
    from cortex.config import load_settings
    from cortex.sources.activism import fetch_activism_events, store_activism_events
    from cortex.sources.universe import sp500_tickers

    settings = load_settings()
    universe = set(sp500_tickers())
    print(
        f"Fetching SC 13D filings targeting {len(universe)} S&P500 tickers "
        f"from {args.from_year}… (this takes ~10–20 minutes)"
    )
    events = fetch_activism_events(universe, from_year=args.from_year)
    new = store_activism_events(events, settings.duckdb_path)
    print(f"Activism sync complete — {len(events)} events fetched, {new} new rows")


def _cmd_funds_backfill(args: argparse.Namespace) -> None:  # noqa: ARG001
    from cortex.config import load_settings
    from cortex.sources.funds import MANAGERS, sync_all_managers

    settings = load_settings()
    print(
        f"Historical 13F backfill for {len(MANAGERS)} managers "
        "(all quarters back to 2014) — this will take several minutes…"
    )
    new = sync_all_managers(settings.duckdb_path, historical=True)
    print(f"Funds backfill complete — {new} new/updated moves")


def _cmd_fundamentals_sync(args: argparse.Namespace) -> None:  # noqa: ARG001
    from cortex.config import load_settings
    from cortex.sources.fundamentals import sync_universe_fundamentals

    settings = load_settings()
    print("Syncing point-in-time fundamentals from EDGAR (this is slow)…")
    new = sync_universe_fundamentals(settings.duckdb_path)
    print(f"Fundamentals sync complete — {new} new annual data points")


def _cmd_event_study(args: argparse.Namespace) -> None:
    from cortex.backtest import run_event_study
    from cortex.config import load_settings

    settings = load_settings()
    rep = run_event_study(
        settings.duckdb_path,
        signal=args.signal,
        from_year=args.from_year,
    )
    signal_label = {
        "insider": "INSIDER  (Form 4 open-market buys)",
        "activism": "ACTIVISM  (SC 13D initial stakes)",
        "congress": "CONGRESS  (Senate/House disclosures)",
    }.get(args.signal, args.signal.upper())
    print()
    print("=" * 80)
    print(f"EVENT-STUDY: {signal_label}  from_year={rep.from_year}")
    print("Market-adjusted CAR (EW S&P 500 benchmark; no beta estimation).")
    print("Each filing treated as an independent event.")
    print("=" * 80)
    print()
    pl = rep.placebo
    print(
        f"  PRE-EVENT PLACEBO ({pl.w_start:+d},{pl.w_end:+d}): "
        f"CAR={pl.mean_car:+.2%}  NW t={pl.nw_tstat:+.2f}  "
        f"hit={pl.hit_rate:.0%}  n={pl.n}"
    )
    print("  (should be ~0 if filing-date gating is correct)")
    print()
    print("  HORIZONS:")
    for h in rep.horizons:
        print(
            f"  ({h.w_start:+d},+{h.w_end:d}): "
            f"CAR={h.mean_car:+.2%}  NW t={h.nw_tstat:+.2f}  "
            f"hit={h.hit_rate:.0%}  n={h.n}"
        )
    print()
    print(
        f"  {rep.n_skipped} events skipped (ticker absent from price data "
        "or event past data end)"
    )
    print()
    print("  CAVEATS:")
    print("  - Universe survivorship bias: current S&P 500 members only")
    print("  - Market-adjusted model only (no beta); CAPM-residual is a future upgrade")
    print(
        f"  - Sparse: {rep.n_events_total} events across ~503 names "
        f"({rep.from_year}→now)"
    )
    print("  - t ≥ 3.0 (NW, autocorrelation-robust) required to claim a real edge")
    print("=" * 80)


def _cmd_congress_oos(args: argparse.Namespace) -> None:
    from cortex.backtest import run_congress_oos
    from cortex.config import load_settings

    settings = load_settings()
    print()
    print("=" * 80)
    print("PRE-REGISTERED CONGRESS OOS TEST")
    print("Hypothesis: congress net-buy factor (180d hl / 365d window / disclosure-")
    print("gated) predicts 1-month fwd returns. Pass: OOS IC t-stat ≥ 3.0.")
    print("=" * 80)
    rep = run_congress_oos(
        settings.duckdb_path,
        insample_end_year=args.insample_end_year,
        start_year=args.start_year,
    )
    print()
    print(f"  IN-SAMPLE  {rep.insample_start} → {rep.insample_end}")
    print(
        f"    IC={rep.insample_mean_ic:+.4f}  t={rep.insample_ic_tstat:.2f}"
        f"  NW t={rep.insample_ic_tstat_nw:.2f}"
        f"  coverage={rep.insample_coverage:.0%}  n={rep.insample_n_months} months"
    )
    print()
    print(f"  OUT-OF-SAMPLE  {rep.oos_start} → {rep.oos_end}")
    print(
        f"    IC={rep.oos_mean_ic:+.4f}  t={rep.oos_ic_tstat:.2f}"
        f"  NW t={rep.oos_ic_tstat_nw:.2f}"
        f"  coverage={rep.oos_coverage:.0%}  n={rep.oos_n_months} months"
    )
    print()
    print("  PORTFOLIO (OOS, long-only top decile by congress score, EW, net 10bps):")
    print(
        f"    Congress top-decile CAGR={rep.oos_portfolio_cagr:+.1%}"
        f"  Sharpe={rep.oos_portfolio_sharpe:.2f}"
    )
    print(
        f"    EW Benchmark          CAGR={rep.oos_benchmark_cagr:+.1%}"
        f"  Sharpe={rep.oos_benchmark_sharpe:.2f}"
    )
    print()
    print("  CAVEATS: universe = current S&P500 (survivorship-biased, results")
    print(
        f"  upward-biased). Congress covers ~{rep.oos_coverage:.0%} of names (sparse)."
    )
    print()
    print(f"  VERDICT: {rep.verdict}")
    print("=" * 80)


def _cmd_backtest(args: argparse.Namespace) -> None:
    from cortex.backtest import run_backtest
    from cortex.config import load_settings

    settings = load_settings()
    rep = run_backtest(settings.duckdb_path, start_year=args.start_year)

    print()
    print("=" * 80)
    print(f"CORTEX BACKTEST  {rep.start} → {rep.end}  ({rep.n_names} names, monthly)")
    print("=" * 80)
    print(
        f"  {'BENCHMARK (EW S&P500)':30} "
        f"CAGR={rep.benchmark_cagr:+.1%}  Sharpe={rep.benchmark_sharpe:.2f}"
    )
    print("  " + "-" * 76)
    for s in rep.variants:
        print(
            f"  {s.label:30} IC={s.mean_ic:+.4f} "
            f"(t={s.ic_tstat:.2f}, NW={s.ic_tstat_nw:.2f})  "
            f"CAGR={s.cagr:+.1%}  Sharpe={s.sharpe:.2f}  "
            f"maxDD={s.max_drawdown:.1%}  hit={s.hit_rate:.0%}  n={s.n_months}"
        )
    print()
    print("  PER-FACTOR ABLATION (standalone information coefficient):")
    print(f"   {'factor':10} {'mean IC':>9}  {'t':>6}  {'NW t':>6}  {'coverage':>8}")
    for f in rep.factor_ics:
        flag = "  <-- real" if abs(f.ic_tstat_nw) >= 3.0 else ""
        print(
            f"   {f.factor:10} {f.mean_ic:>+9.4f}  {f.ic_tstat:>6.2f}  "
            f"{f.ic_tstat_nw:>6.2f}  {f.coverage:>7.0%}{flag}"
        )
    print()
    if rep.long_short is not None:
        ls = rep.long_short
        print("  LONG-SHORT SPREAD (CORTEX D10 − D1, beta-stripped factor return):")
        print(
            f"    mean monthly={ls.mean_monthly:+.4%}  NW t={ls.tstat_nw:.2f}  "
            f"CAGR={ls.cagr:+.1%}  Sharpe={ls.sharpe:.2f}  n={ls.n_months}"
        )
        print()
    if rep.factor_corr is not None:
        fc = rep.factor_corr
        print("  FACTOR IC CORRELATION (do flow factors add beyond price?):")
        header = "         " + "".join(f"{k[:5]:>7}" for k in fc.factors)
        print(header)
        for name, row in zip(fc.factors, fc.matrix, strict=True):
            cells = "".join(
                f"{v:>+7.2f}" if v is not None else f"{'—':>7}" for v in row
            )
            print(f"   {name:6}{cells}")
        print()
    cortex = rep.variants[0]
    print("  CORTEX decile CAGR (D1 worst → D10 best), monotonicity check:")
    deciles = "  ".join(f"D{d + 1}:{c:+.0%}" for d, c in enumerate(cortex.decile_cagr))
    print("   " + deciles)
    print()
    print(
        "  READ: a factor/composite is 'real' only at NW (Newey-West) IC t-stat ≥ 3.0"
    )
    print("  (autocorrelation-robust, multiple-testing haircut). The long-short spread")
    print(
        "  should be positive and deciles rise monotonically; a flow factor earns its"
    )
    print("  place only if its IC is weakly correlated with momentum/trend. CAVEATS:")
    print("  universe = CURRENT S&P500 (survivorship-biased → results upward-biased).")
    print("  Net 10bps/side, rf=0. Value/quality via point-in-time EDGAR filings.")
    print("=" * 80)


def _cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "cortex.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


def _cmd_sync_all(args: argparse.Namespace) -> None:
    """Run the full refresh (congress → funds → discover → volatility).

    Invoked as an isolated subprocess by the API so a sync OOM can't take down
    the web server. Streams progress to the status JSON on the volume. With
    ``--only`` it runs a subset, so per-source Railway cron jobs can refresh on
    independent cadences.
    """
    from cortex.config import load_settings
    from cortex.sync_job import run_full_sync

    settings = load_settings()
    only = (
        [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None
    )
    run_full_sync(settings.duckdb_path, only=only)


def _cmd_trigger_refresh(args: argparse.Namespace) -> None:
    """POST to the running web app's /refresh so a Railway cron job can kick off
    a sync. The cron service has no volume; the web service owns the DB and runs
    the actual sync as its own isolated subprocess (the path /refresh already
    drives). Reads target + credentials from env so nothing secret is in argv.
    """
    import os

    import httpx

    base = (args.url or os.environ.get("CORTEX_REFRESH_URL", "")).rstrip("/")
    if not base:
        print("error: pass --url or set CORTEX_REFRESH_URL", flush=True)
        raise SystemExit(2)

    params = {"only": args.only} if args.only else None
    user = os.environ.get("CORTEX_AUTH_USER", "")
    pw = os.environ.get("CORTEX_AUTH_PASS", "")
    auth = (user, pw) if user else None

    try:
        resp = httpx.post(
            f"{base}/refresh", params=params, auth=auth, timeout=30.0
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"trigger-refresh failed: {exc}", flush=True)
        raise SystemExit(1) from exc
    print(f"triggered refresh ({args.only or 'all'}) — {resp.json().get('status')}")


def _cmd_trigger_backup(args: argparse.Namespace) -> None:
    """POST /admin/backup on the running web app (for the weekly backup cron).

    The volume-owning web process runs the actual EXPORT; the cron box only
    fires the trigger. Mirrors trigger-refresh for credentials/target.
    """
    import os

    import httpx

    base = (args.url or os.environ.get("CORTEX_REFRESH_URL", "")).rstrip("/")
    if not base:
        print("error: pass --url or set CORTEX_REFRESH_URL", flush=True)
        raise SystemExit(2)

    user = os.environ.get("CORTEX_AUTH_USER", "")
    pw = os.environ.get("CORTEX_AUTH_PASS", "")
    auth = (user, pw) if user else None

    try:
        resp = httpx.post(
            f"{base}/admin/backup", params={"keep": args.keep}, auth=auth, timeout=120.0
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"trigger-backup failed: {exc}", flush=True)
        raise SystemExit(1) from exc
    body = resp.json()
    print(f"backup ok — {body.get('snapshot')} (pruned {body.get('pruned')})")


def _cmd_snapshot_factors(args: argparse.Namespace) -> None:
    """Run the backtest and persist each factor's t-stats with today's date.

    A nightly cron snapshot builds a time series so the drift of the congress /
    fund factors toward the t≥3.0 pre-registration bar is visible over time.
    """
    from datetime import date

    from cortex.backtest import run_backtest
    from cortex.config import load_settings
    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    settings = load_settings()
    try:
        rep = run_backtest(settings.duckdb_path, start_year=args.start_year)
    except Exception as exc:  # noqa: BLE001 - unattended job: alert, don't vanish
        from cortex.alerts import send_alert

        send_alert(f"⚠️ CORTEX snapshot-factors failed: {exc}")
        print(f"snapshot-factors failed: {exc}", flush=True)
        raise SystemExit(1) from exc
    today = date.today()
    n_months = rep.variants[0].n_months if rep.variants else None

    rows = [
        (today, f.factor, f.mean_ic, f.ic_tstat, f.ic_tstat_nw, f.coverage, n_months)
        for f in rep.factor_ics
    ]
    with connect(settings.duckdb_path) as conn:
        apply_schema(conn)
        for r in rows:
            conn.execute(
                """
                INSERT INTO factor_history
                  (snapshot_date, factor, ic_mean, ic_tstat, ic_tstat_nw,
                   coverage, n_months)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (snapshot_date, factor) DO UPDATE SET
                  ic_mean = excluded.ic_mean, ic_tstat = excluded.ic_tstat,
                  ic_tstat_nw = excluded.ic_tstat_nw, coverage = excluded.coverage,
                  n_months = excluded.n_months, recorded_at = CURRENT_TIMESTAMP
                """,
                list(r),
            )
    print(f"Snapshotted {len(rows)} factor t-stats for {today}")


def _cmd_trigger_snapshot(args: argparse.Namespace) -> None:
    """POST /admin/snapshot-factors on the running web app (nightly cron)."""
    import os

    import httpx

    base = (args.url or os.environ.get("CORTEX_REFRESH_URL", "")).rstrip("/")
    if not base:
        print("error: pass --url or set CORTEX_REFRESH_URL", flush=True)
        raise SystemExit(2)

    user = os.environ.get("CORTEX_AUTH_USER", "")
    pw = os.environ.get("CORTEX_AUTH_PASS", "")
    auth = (user, pw) if user else None
    try:
        resp = httpx.post(
            f"{base}/admin/snapshot-factors", auth=auth, timeout=30.0
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"trigger-snapshot failed: {exc}", flush=True)
        raise SystemExit(1) from exc
    print(f"triggered factor snapshot — {resp.json().get('status')}")


def _cmd_backup(args: argparse.Namespace) -> None:
    """Export the DuckDB to a timestamped snapshot dir on the volume.

    Uses DuckDB's EXPORT DATABASE (Parquet) so the snapshot is engine-portable
    and consistent. Prunes to the newest --keep snapshots.
    """
    from cortex.backup import prune_backups, run_backup
    from cortex.config import load_settings

    settings = load_settings()
    dest = run_backup(settings.duckdb_path, keep=args.keep)
    removed = prune_backups(settings.duckdb_path, keep=args.keep)
    print(f"Backup written to {dest}")
    if removed:
        print(f"Pruned {removed} old snapshot(s), keeping {args.keep}")


def _cmd_vol_screen(args: argparse.Namespace) -> None:
    from cortex.config import load_settings
    from cortex.volatility_screen import run_volatility_screen

    settings = load_settings()
    log.info("Starting swing screen…")
    stocks = run_volatility_screen(
        settings.duckdb_path,
        top_n=args.top_n,
        lookback_days=args.lookback_days,
    )
    print(f"Swing screen — top {len(stocks)} by consistent dollar swing")
    for s in stocks:
        adr = f"${s.avg_dollar_range:.2f}" if s.avg_dollar_range is not None else "—"
        cons = f"{s.range_consistency:.2f}" if s.range_consistency is not None else "—"
        pct = f"{s.avg_range_pct * 100:.1f}%" if s.avg_range_pct is not None else "—"
        osc = f"{s.oscillation_score:.2f}" if s.oscillation_score is not None else "—"
        print(
            f"  #{s.rank:2d} {s.ticker:<6} score={s.swing_score:7.3f}"
            f"  adr={adr:>9}  consistency={cons}  range={pct}  osc={osc}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="cortex", description="CORTEX — factor research CLI"
    )
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

    discover_p = sub.add_parser("discover", help="Run CORTEX 6-factor discovery")
    discover_p.add_argument(
        "--top-n",
        type=int,
        default=30,
        metavar="N",
        help="Number of candidates to keep (default: 30)",
    )
    discover_p.add_argument(
        "--prefilter-n",
        type=int,
        default=150,
        metavar="N",
        help="Shortlist size before fundamentals (default: 150)",
    )

    vol_p = sub.add_parser(
        "vol-screen",
        help="Run the swing screen — stocks with large, consistent daily $ swings",
    )
    vol_p.add_argument(
        "--top-n",
        type=int,
        default=75,
        metavar="N",
        help="Number of stocks to keep (default: 75)",
    )
    vol_p.add_argument(
        "--lookback-days",
        type=int,
        default=15,
        metavar="N",
        help="Trading-day window, floored at 10 / two weeks (default: 15)",
    )

    congress_p = sub.add_parser("congress-sync", help="Scrape Senate eFD into the DB")
    congress_p.add_argument(
        "--since-days",
        type=int,
        default=90,
        metavar="N",
        help="Look back N days of filings (default: 90)",
    )
    congress_p.add_argument(
        "--max-reports",
        type=int,
        default=250,
        metavar="N",
        help="Max PTR filings per window (default: 250)",
    )
    congress_p.add_argument(
        "--backfill-from-year",
        type=int,
        default=None,
        metavar="YYYY",
        help="Backfill the archive from this year, "
        "persisting per 180-day window (resumable)",
    )

    house_p = sub.add_parser(
        "house-sync", help="Scrape House Clerk PTR filings into the DB"
    )
    house_p.add_argument(
        "--since-days",
        type=int,
        default=90,
        metavar="N",
        help="Look back N days of filings (default: 90)",
    )
    house_p.add_argument(
        "--max-pdfs",
        type=int,
        default=500,
        metavar="N",
        help="Max PTR PDFs to download (default: 500)",
    )
    house_p.add_argument(
        "--backfill-from-year",
        type=int,
        default=None,
        metavar="YYYY",
        help="Backfill the archive from this year (resumable via dedup)",
    )

    sub.add_parser("funds-sync", help="Sync institutional 13F moves into the DB")
    sub.add_parser(
        "funds-backfill",
        help="Historical 13F backfill — all quarters back to 2014 for all managers",
    )

    ins_p = sub.add_parser(
        "insiders-sync",
        help="Sync Form 4 insider open-market purchases for S&P500 universe",
    )
    ins_p.add_argument(
        "--from-year",
        type=int,
        default=2017,
        metavar="YYYY",
        help="Earliest year to backfill (default: 2017)",
    )

    act_p = sub.add_parser(
        "activism-sync",
        help="Sync SC 13D activist filings for S&P500 universe into the DB",
    )
    act_p.add_argument(
        "--from-year",
        type=int,
        default=2014,
        metavar="YYYY",
        help="Earliest year to backfill (default: 2014)",
    )
    sub.add_parser("fundamentals-sync", help="Sync point-in-time EDGAR fundamentals")

    es_p = sub.add_parser(
        "event-study",
        help="CAR event study for a filing-gated signal (insider/activism/congress)",
    )
    es_p.add_argument(
        "--signal",
        required=True,
        choices=["insider", "activism", "congress"],
        metavar="{insider,activism,congress}",
        help="Signal to evaluate",
    )
    es_p.add_argument(
        "--from-year",
        type=int,
        default=2017,
        metavar="YYYY",
        help="First year of events to include (default: 2017)",
    )

    oos_p = sub.add_parser(
        "congress-oos",
        help="Pre-registered OOS test of the congressional-buy factor",
    )
    oos_p.add_argument(
        "--insample-end-year",
        type=int,
        default=2021,
        metavar="YYYY",
        help="Last year of the in-sample window (default: 2021)",
    )
    oos_p.add_argument(
        "--start-year",
        type=int,
        default=2017,
        metavar="YYYY",
        help="First year of the evaluation period (default: 2017)",
    )

    bt_p = sub.add_parser("backtest", help="Point-in-time CORTEX signal backtest")
    bt_p.add_argument(
        "--start-year",
        type=int,
        default=2017,
        metavar="YYYY",
        help="First year to evaluate (default: 2017)",
    )

    serve_p = sub.add_parser("serve", help="Start the FastAPI server")
    serve_p.add_argument("--host", default="127.0.0.1")
    serve_p.add_argument("--port", type=int, default=8000)
    serve_p.add_argument("--reload", action="store_true")

    sync_all_p = sub.add_parser(
        "sync-all",
        help="Run the full data refresh (congress, funds, discover, volatility)",
    )
    sync_all_p.add_argument(
        "--only",
        default=None,
        metavar="SOURCES",
        help="Comma-separated subset to run (congress,funds,discover,volatility)",
    )

    trig_p = sub.add_parser(
        "trigger-refresh",
        help="POST /refresh on the running web app (for Railway cron services)",
    )
    trig_p.add_argument(
        "--url",
        default=None,
        metavar="URL",
        help="Web app base URL (default: $CORTEX_REFRESH_URL)",
    )
    trig_p.add_argument(
        "--only",
        default=None,
        metavar="SOURCES",
        help="Comma-separated subset to refresh (congress,funds,discover,volatility)",
    )

    snap_p = sub.add_parser(
        "snapshot-factors",
        help="Persist today's factor t-stats to factor_history (nightly cron)",
    )
    snap_p.add_argument(
        "--start-year",
        type=int,
        default=2017,
        metavar="YYYY",
        help="First year to evaluate (default: 2017)",
    )

    trigsnap_p = sub.add_parser(
        "trigger-snapshot",
        help="POST /admin/snapshot-factors on the running web app (nightly cron)",
    )
    trigsnap_p.add_argument(
        "--url",
        default=None,
        metavar="URL",
        help="Web app base URL (default: $CORTEX_REFRESH_URL)",
    )

    backup_p = sub.add_parser(
        "backup", help="Export the DuckDB to a timestamped snapshot on the volume"
    )
    backup_p.add_argument(
        "--keep",
        type=int,
        default=7,
        metavar="N",
        help="Number of snapshots to retain (default: 7)",
    )

    trigbk_p = sub.add_parser(
        "trigger-backup",
        help="POST /admin/backup on the running web app (for the backup cron)",
    )
    trigbk_p.add_argument(
        "--url",
        default=None,
        metavar="URL",
        help="Web app base URL (default: $CORTEX_REFRESH_URL)",
    )
    trigbk_p.add_argument(
        "--keep",
        type=int,
        default=7,
        metavar="N",
        help="Number of snapshots to retain (default: 7)",
    )

    args = parser.parse_args()

    dispatch = {
        "db-init": _cmd_db_init,
        "new": _cmd_new,
        "review": _cmd_review,
        "calibration": _cmd_calibration,
        "mirror": _cmd_mirror,
        "rag-index": _cmd_rag_index,
        "discover": _cmd_discover,
        "vol-screen": _cmd_vol_screen,
        "congress-sync": _cmd_congress_sync,
        "house-sync": _cmd_house_sync,
        "funds-sync": _cmd_funds_sync,
        "funds-backfill": _cmd_funds_backfill,
        "insiders-sync": _cmd_insiders_sync,
        "activism-sync": _cmd_activism_sync,
        "fundamentals-sync": _cmd_fundamentals_sync,
        "event-study": _cmd_event_study,
        "congress-oos": _cmd_congress_oos,
        "backtest": _cmd_backtest,
        "serve": _cmd_serve,
        "sync-all": _cmd_sync_all,
        "trigger-refresh": _cmd_trigger_refresh,
        "trigger-backup": _cmd_trigger_backup,
        "trigger-snapshot": _cmd_trigger_snapshot,
        "snapshot-factors": _cmd_snapshot_factors,
        "backup": _cmd_backup,
    }
    dispatch[args.command](args)


if __name__ == "__main__":
    main()
