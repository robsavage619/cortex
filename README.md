<p align="center">
  <img src="docs/banner.png" alt="CORTEX, a point-in-time multi-factor research engine" width="100%"/>
</p>

<p align="center">
  <a href="https://www.python.org/"><img src="https://img.shields.io/badge/python-3.12-blue.svg" alt="python 3.12"/></a>
  <a href="https://fastapi.tiangolo.com/"><img src="https://img.shields.io/badge/api-FastAPI-009688" alt="FastAPI"/></a>
  <a href="https://duckdb.org/"><img src="https://img.shields.io/badge/store-DuckDB%20%2B%20VSS-fff100" alt="DuckDB"/></a>
  <a href="web/"><img src="https://img.shields.io/badge/frontend-React%2019%20%2B%20Vite-61dafb" alt="React 19"/></a>
  <img src="https://img.shields.io/badge/tests-198%20passing-34D399" alt="tests"/>
  <img src="https://img.shields.io/badge/paid%20data%20vendors-zero-8B5CF6" alt="zero paid data vendors"/>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-source--available-lightgrey" alt="license"/></a>
</p>

CORTEX is a single-operator quantitative research platform. It ingests seven free
public disclosure feeds (SEC EDGAR Form 4, 13F and XBRL, Senate eFD, House Clerk
PTRs, FINRA Reg SHO, White House transcripts), builds ten point-in-time equity
factors over a historical S&P 500 universe, and scores each one against a
significance bar the harness derives from that run's own test count. It also logs
my own forecasts as theses with required falsifiers and scores how calibrated they
turn out to be. As of the 2026-09-19 run, no factor clears its bar, so nothing
trades. That result is the deliverable.

Published for portfolio review. The code is readable; it is not licensed for reuse.
See [LICENSE](LICENSE).

## The constraints that forced the design

**One operator, no team, no data budget.** Every source has to be a free public
filing feed. That rules out the survivorship-clean vendor panels most factor work
is built on (CRSP, Compustat), so point-in-time correctness has to be
reconstructed: vendored S&P 500 membership history, per-source coverage tables
that separate "never fetched" from "nothing there", and a delisting gap that is
measured and printed rather than assumed away.

**The question is "is this signal real", not "serve N users".** There is no
latency budget, no concurrency requirement, no multi-tenancy, no uptime target.
The throughput that matters is how fast one person gets from a hypothesis to a
measured t-statistic. So every layer that exists to serve many users at once is a
layer between the operator and that number, and none of them are here: no queue,
no scheduler daemon, no Postgres, no service boundary inside the app.

**The dataset fits on one disk.** 188 MB, 1.56M price rows, 433k 13F rows, 23
tables. That is why the database is embedded and columnar rather than a warehouse:
the backtest reads the whole panel in-process with no network hop and no
serialisation, and the entire store snapshots to Parquet in one command.

**A Railway volume attaches to exactly one service.** The web service owns the
volume, so a cron service physically cannot open the DuckDB file. Scheduled work
is therefore an HTTP trigger against the volume-owning process, which spawns the
real job as a detached subprocess so an OOM kill takes the sync rather than the
server.

**The failure mode is self-deception, not downtime.** A research tool that quietly
produces a flattering number is worse than one that is offline, because nobody
pages you. This is the constraint that shaped the most code. The significance bar
is computed per run instead of asserted. Hypotheses and falsifiers are written
before the run. Corrections that lower a t-statistic are kept and journaled the
same as ones that raise it. Each factor's known caveats print beside its own
number. The integrity audit measures event yield, rows stored against events
actually scored, because row-level checks kept passing while loaders silently
discarded data.

**Token spend must not leak into local runs.** The two LLM-assisted paths are
gated on `RAILWAY_ENVIRONMENT` or `CORTEX_PRODUCTION`, so development and the test
suite never bill the key.

## Architecture

```
                +----------------------------------------------+
                |  React 19 + Vite + TS portal   (web/)         |
                |  terminal UI, TanStack Query, charts          |
                +-----------------------+----------------------+
                                        |  one origin, port 8000
                +-----------------------+----------------------+
                |  FastAPI service   (src/cortex/api.py)        |
                |  36 routes: typed JSON API + the built SPA    |
                +-----------------------+----------------------+
                                        |
      +--------------+--------------+---+----------+--------------+
      |              |              |              |              |
+-----+-----+  +-----+-----+  +-----+-----+  +-----+-----+  +-----+------+
| composite |  | decision  |  | RAG /     |  | ingestion |  | backtest / |
| + scoring |  | quality   |  | evidence  |  | 14 source |  | pre-reg    |
| discovery |  | theses,   |  | fastembed |  | modules   |  | harness    |
|           |  | calibrat. |  | DuckDB VSS|  |           |  |            |
+-----+-----+  +-----+-----+  +-----+-----+  +-----+-----+  +-----+------+
      |              |              |              |              |
      +--------------+--------------+--------------+--------------+
                                        |
                       +----------------+----------------+
                       |  DuckDB, single file            |
                       |  23 tables, schema v22          |
                       |  + VSS HNSW index on embeddings |
                       +---------------------------------+
```

Details in [docs/architecture.md](docs/architecture.md).

## Five problems worth reading about

**Every 13F exit had been dropped for the life of the fund factor.**
`_load_fund_events` sized each event off the `value` column, but an EXIT closes a
position, so `value` is 0 by construction, `log1p(0)` is 0, and a `weight <= 0`
guard discarded the row. All 71,958 exit rows were gone; the negative leg had only
ever been TRIM. Sizing off `prev_shares` times the last close on or before the
filing date restored 7,309 of 8,100 in-universe exits, and the fund factor fell
from 2.48 to 2.42 with the composite from 1.78 to 1.65.
[docs/factor-journal.md](docs/factor-journal.md)

**The congress factor was Senate-only for eight years, and backfilling the House
changed nothing.** The House PTR backfill had never run, so 967 House rows all
carried 2026 dates. Adding 13,584 historical trades moved no number at all,
because `_congress_sign` understood only the Senate's English words while House
PTRs carry SEC letter codes, so about 14,300 of 14,551 House rows returned 0 and
were dropped. Fixing the parser took congress from 2.24 to 1.72, which is the
direction Ziobrowski (2011) predicts since the House effect is weaker and pooling
dilutes. The old 2.24 was a Senate-only number.
[docs/ingestion.md](docs/ingestion.md)

**Earnings yield was inflated by the cumulative split factor.** As-reported EDGAR
EPS was being divided by back-adjusted yfinance prices, which are different split
bases, so BKNG showed an implied P/E of 1.3 on a 25:1 split and KLAC 6.4 on 10:1.
A second defect compounded it: the as-of query ordered only by `filing_date`, and
a 10-K's comparative periods all share one, so ties resolved to arbitrary storage
order. Restating EPS through a local splits cache took the composite from 2.32 to
1.78 and left standalone value at 0.17, which is nothing.
[docs/data-model.md](docs/data-model.md)

**The promotion bar is computed, not chosen.** CORTEX used to hardcode `t >= 3.0`
and call it Bonferroni-corrected, and neither half was right.
`significance.build_gate(n_tests)` now derives two Benjamini-Hochberg-Yekutieli
bars from the run's own test count, with factors assigned to a family in code
ahead of the run so the choice cannot follow the result. Adding the short-interest
factor moved the own-family bar from 3.21 to 3.24, which is the honest cost of
testing another idea, charged automatically.
[docs/evaluation.md](docs/evaluation.md)

**Form 4 XML filenames are not standardised.** `form4.xml` resolves for roughly
half of filers; filing agents use their own names, and Edgar Online writes
`rdgdoc.xml` while Workiva writes `wf-form4-*.xml`. The canonical path is
`data.sec.gov/submissions/CIK{cik10}.json` and its `primaryDocument` field, except
that the field sometimes returns an `xslF345X06/` XSLT rendering path rather than
the data file. Pre-loading that map costs about 75 seconds for 503 CIKs and
replaces 282,000 filename guesses.
[docs/ingestion.md](docs/ingestion.md)

## How it is verified

`uv run pytest`: **198 tests pass in 13.4s**, 40% line coverage over 5,874
statements. 3,339 lines of test against 13,903 lines of source, one test line per
4.2 source lines. Coverage is deliberately uneven, high in the code that produces
numbers (`thesis.py` 98%, `storage/schemas.py` 96%, `sources/short_interest.py`
94%) and low in fetch plumbing (`sources/prices.py` 44%, `sources/house.py` 0%).
HTTP sources are mocked with `respx`; nothing touches live EDGAR.

Several tests exist only because a bug shipped and was found later: dropped 13F
exits, unparsed House transaction codes, an unquoted YAML wildcard that removed
notes from the index. Each carries the story in its docstring.

`cortex audit-integrity` reports event yield per source, rows stored against
events actually scored, because five separate defects had the same shape:
well-formed data the loader could not read, which no row-level check catches.

The backtest checks itself. Every run reports a price-only null model for
comparison, decile monotonicity, the factor IC correlation matrix and its mean
off-diagonal absolute correlation, a size split, a tail decomposition, the
long-short spread gross and net of costs, and point-in-time universe coverage
mean and worst month.

`ruff check` passes repo-wide. `ruff format --check` flags 5 files. `pyright`
(basic) reports 50 errors, 24 in `src` and 26 in tests; the factor, storage and
decision core is clean and the rest is tracked type debt.

## Known limitations

**No factor clears its bar, and the composite does not beat the index.** Composite
NW t is 1.67 against a price-only null of 0.36; long-short is 1.19 gross and 0.82
net. The composite's Sharpe is 0.89 against SPY's 1.00 over the same window. It
beats the equal-weight benchmark on CAGR (+15.2% against +12.5%) and loses to
buy-and-hold SPY risk-adjusted.

**Four factors carry nothing or the wrong sign.** value 0.17, insider -0.26, vol
-0.56, activism -1.58. These are measured null results, kept in the ablation
rather than quietly dropped.

**The fund factor is largely one manager.** Renaissance Technologies is 73.7% of
`fund_holdings` rows since 2017 and Bridgewater another 13.3%; the six
high-conviction managers are 3.3% combined. It therefore does not measure the Best
Ideas mechanism it cites, which is about concentrated conviction.

**The congress factor is fragile.** 1.74 raw collapses to 1.13 on a log scale,
replicated across two data vintages, so the signal lives in a handful of very
large disclosures rather than in breadth.

**Activism has no paper behind it**, only a comment citing Brav & Jiang (2008),
so it is scored ungrounded on 15% coverage. **Short interest cannot reach the
backtest start**: FINRA's archive is rolling at roughly 8 years, so the factor has
zero coverage for the first 19 months and sits on a shorter, later sample than
every other factor.

**The universe has a residual delisting gap.** 621 of 742 union names are
priceable; monthly priced-member coverage averages 91% with a worst month of 81%.
The Stooq fallback for delisted prices has been blocked by a proof-of-work
challenge since 2026-07-16 and currently prices zero names.

**Event-study CARs do not support the congress result.** They are flat to negative
at long horizons. Whatever signal exists is carried by the monthly IC framing, not
by event CARs.

**The recorded trial count is a lower bound**: 104 since instrumentation began on
2026-08-10, so the true N for a Harvey-Liu haircut is higher than anything
reported here. **The frontend has no tests**, across 8,932 lines of TypeScript in
40 files. **`fund_holdings.period` is misnamed**: it holds the 13F filing date,
not the quarter end. No lookahead hides in it, but the name says otherwise.

## Documentation

[docs/README.md](docs/README.md) is the full index. The three worth opening first:

| Doc | Covers |
|---|---|
| [factor-journal.md](docs/factor-journal.md) | Seven changes with measured before and after. Six of them lowered the result |
| [evaluation.md](docs/evaluation.md) | How the significance bar is derived, what the harness reports, current numbers |
| [ingestion.md](docs/ingestion.md) | Fourteen sources and the failure mode of each |

Also: [architecture.md](docs/architecture.md),
[data-model.md](docs/data-model.md),
[research-sources.md](docs/research-sources.md),
[design-system.md](docs/design-system.md),
[operations.md](docs/operations.md),
[deploy/README.md](deploy/README.md).

## The portal

A dark-only terminal instrument panel. Gains and losses render in muted green and
red on purpose: the UI signals direction, never excitement. Seven views, plus a
per-ticker case workspace that opens as a modal. More in
[docs/screenshots/](docs/screenshots/).

<p align="center">
  <img src="docs/screenshots/dashboard.png" alt="CORTEX dashboard: ranked candidates with per-factor z-score meters" width="100%"/>
</p>

## Disclaimer

CORTEX is a personal research and decision-support tool. It is not financial
advice, does not execute trades, and makes no recommendations. Nothing here is an
offer or solicitation.

## License

Source-available, all rights reserved. Published for portfolio review and
evaluation only. You may read the code. You may not copy, modify, reuse,
redistribute, or deploy it, in whole or in part, without prior written permission.
See [LICENSE](LICENSE) for the full terms.

Copyright Rob Savage. All rights reserved.
