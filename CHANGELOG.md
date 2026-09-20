# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Contents

**[Unreleased]**

- [Vault to factor evidence link](#vault-to-factor-evidence-link-2026-08-10-schema-v22) (2026-08-10, schema v22)
- [Short-interest factor and the trial log](#short-interest-factor-and-the-trial-log-2026-08-10-schema-v20v21) (2026-08-10, schema v20/v21)
- [The promotion bar is derived, not asserted](#the-promotion-bar-is-derived-not-asserted-2026-08-10) (2026-08-10)
- [Three pre-registered construction changes](#three-pre-registered-construction-changes-2026-08-10) (2026-08-10)
- [Congress was Senate-only for 2017 to 2025](#congress-was-senate-only-for-2017-to-2025-2026-08-10) (2026-08-10)
- [Audit: event yield and declared ingest filters](#audit-event-yield-and-declared-ingest-filters-2026-08-10) (2026-08-10)
- [Every 13F EXIT was being dropped from the fund factor](#every-13f-exit-was-being-dropped-from-the-fund-factor-2026-08-10) (2026-08-10)
- [Vault retrieval actually reaches the vault](#vault-retrieval-actually-reaches-the-vault-2026-08-10) (2026-08-10)
- [Value-factor data integrity](#value-factor-data-integrity-2026-08-10-schema-v19) (2026-08-10, schema v19)
- [Methodology hardening and re-baseline](#methodology-hardening--re-baseline-2026-07-16) (2026-07-16)
- [Security](#security), [Changed](#changed), [Added](#added)

**[0.1.0], 2026-05-24**

- [Added](#added-1), [Engineering](#engineering)

For the same changes written as a research log with measured before and after,
see [docs/factor-journal.md](docs/factor-journal.md).

## [Unreleased]

### Vault to factor evidence link (2026-08-10, schema v22)

The RAG retriever could answer "what does the corpus say about momentum?", which is good
for browsing, useless at the moment of decision, because it was attached to
nothing. `/research/ticker/AAPL` and `/research/ticker/XOM` returned
byte-identical snippets. A reader looking at `fund 2.62` had no way to learn
from the app that 74% of that factor is one manager.

A vault note now declares what it bears on:

```yaml
cortex_factors: [fund]        # evidence about the fund factor
cortex_factors: ["*"]         # methodology, applies to every factor
```

Notes typed `research-finding` carrying a `current_verdict` are treated as
**caveats** and printed under the ablation table:

```
KNOWN CAVEATS (first-party findings from the vault):
 congress   fragile: 1.72 raw collapses to 1.13 on a log scale
 fund       structural concern; no change made, pre-registration candidate
 insider    blocked, needs S-coded Form 4 ingestion before the fix is testable
 short      evaluated 2026-08-10: NW t 1.87, falsifier survived, not promoted
```

A citation rarely changes a decision; a caveat does. `caveats_for()` excludes
wildcard notes deliberately. A global methodology finding is a real caveat, but
surfacing it per-factor buries "distrust this number" under "distrust all
numbers".

Synced into DuckDB by `cortex rag-index` rather than read live, because the
deployed app has no vault on disk. Also adds `GET /research/factor/{factor}`;
`/research/ticker/{ticker}` gains an additive `caveats` field with `by_factor`
unchanged so the existing web contract holds.

**Trap worth recording:** `cortex_factors: [*]` unquoted is a YAML alias token
that raises, silently dropping the note from the evidence map *and* the RAG
index. There is a regression test asserting the failure mode.

### Short-interest factor and the trial log (2026-08-10, schema v20/v21)

**New `short` factor** from FINRA Reg SHO daily short-volume files. Free, no
auth, 1.13M rows over 2,094 sessions and 690 tickers. Pre-registered before the
data was downloaded, including three recorded reasons to expect a null.

Construction fixed from Boehmer/Jones/Zhang, not tuned: `sfrac` = short / total
volume, 5-day formation, 20-day hold, sign negative. Flow rather than level,
because the paper finds flow drives out short interest in 13 of 15 reversed
sorts.

Result: **NW t = 1.87**, coverage 79%, positive in 58% of months, third
strongest, correct sign, nowhere near the bar. The pre-registered falsifier had
two limbs because IC alone could not settle it, and both are now evaluated: the
t-stat is not zero, and *both* tails carry (+0.24% / -0.22% per month). That
departs from the paper, whose spread is almost entirely its long leg.

Two properties of the source, both now in the module docstring:

- The CDN answers **403, not 404**, for a file it is not serving, so a Sunday
  and a 2017 session are identical at the HTTP layer. Treating 403 as fatal
  aborted the first backfill on its first weekend.
- **The archive is rolling, about eight years.** ~2018-08 onward returns 200;
  2018-07-02 and earlier returns 403. The factor cannot reach the 2017 backtest
  start and has zero coverage for the first ~19 months, so its t-stat sits on a
  shorter, later sample than every other factor.

**`research_trials`** logs every backtest with its test count, factor set, best
t-stat, mean |ρ| and git sha. Bailey & López de Prado's central claim is that a
backtest whose author cannot say how many trials were attempted is worthless,
and Harvey & Liu's haircut takes the count as a literal input. It is reported as
a **lower bound**: logging began 2026-08-10 and months of prior runs are
unrecoverable, so presenting it as N would understate the haircut, which is the
exact failure the counter exists to prevent.

### The promotion bar is derived, not asserted (2026-08-10)

`t >= 3.0` was a hardcoded literal described as Bonferroni-corrected. Neither
half held up. 3.0 is Harvey/Liu/Zhu's *headline recommendation*, and their own
Bonferroni benchmark for the 316-factor zoo is 3.78. **Both Harvey papers
recommend BHY (false discovery rate)**, not Bonferroni.

`significance.py` now derives the bar from each run's actual test count, with
**two bars assigned by family in code ahead of the run** so the choice can never
be made after seeing a result:

| Family | Bar | Applies to |
|---|---:|---|
| Own-family BHY | 3.24 | congress, fund, insider, activism, short |
| Zoo-draw BHY | 4.21 | mom, trend, vol, value, quality, pead |

Factors lifted from the published literature inherit its multiple-testing
burden; CORTEX's own alt-data signals are scored against CORTEX's own family. A
single global constant cannot be right for both.

Note the direction: **BHY with the Yekutieli dependence correction is stricter
than Bonferroni for a lone discovery** (3.24 vs 2.89), because the rank-1
critical value carries a factor of c(N). BHY is the more lenient procedure only
once several tests are already significant. Adding the short factor moved the
own-family bar 3.21 to 3.24: every new idea raises the bar for all of them.

**Promotion target settled: standalone, not composite.** The two disagree:
log-scaled congress is worse standalone and better in the composite, and it
resurfaced on every construction change. The factor is the empirical claim; the
composite is packaging, and it has free parameters an ablation does not.

Three new diagnostics, none of which move a result:

- **Size split**: each factor's NW t within the larger and smaller half of the
  cross-section, split at its own median dollar volume.
- **Tail decomposition**: mean monthly excess return of each factor's top and
  bottom decile. An IC is a rank correlation and cannot say which *end* carries
  a factor.
- **Direction homogeneity**: percent of months with positive IC, per MacKinlay
  via Katz et al. Result: fund 61%, congress 59%, short 58%, everything else
  50 to 54%, i.e. coin flips.
- **Mean |ρ|** across the factor-IC matrix (0.189), the haircut input that could
  not previously be computed.

### Three pre-registered construction changes (2026-08-10)

Hypotheses and falsifiers were written to the vault **before** any run, and each
change was evaluated separately so the deltas stay attributable.

**Fund: asymmetric buy/sell signing.** Agarwal puts 13F acquisitions at +7.06%
DGTW/12m (t=3.95) against disposals at +2.94% (t=1.42); Lakonishok finds the
same asymmetry for insiders. CORTEX signed them +/-1. Two pre-registered values,
not a sweep:

| `sell_weight` | fund | composite | L/S net |
|---|---:|---:|---:|
| 1.0 (old) | 2.42 | 1.65 | 0.78 |
| **0.5 (kept)** | **2.62** | **1.90** | **1.21** |
| 0.0 | 1.73 | 1.73 | 1.25 |

0.5 is the Agarwal ratio, taken from the paper rather than fitted. The interior
optimum is the shape theory predicts: sells carry some information but less than
buys, so both extremes are wrong.

**Insider: distinct-filer count and size-relative dollar rank.** Lakonishok's
strongest screen is built on the number of distinct insiders buying, which
CORTEX ignored despite storing `filer_cik`; and raw `log1p(value_usd)`
mechanically favours mega-caps where LL use dollars only as a within-size rank.
Insider -0.35 to -0.19: directionally as predicted, and still dead, which is
what the pre-registration recorded as the honest prior, because LL find the
effect is entirely small-cap.

**Congress log scale: tested and reverted.** Moving raw notional to `log1p` for
consistency with the other flow loaders collapsed congress 1.72 to 1.13, firing
the pre-registered falsifier. The signal genuinely lives in a handful of very
large disclosures. Raw notional stays, now a deliberate evidence-backed choice
rather than an accident, but the factor is far more fragile than its t-stat
suggests. Standing tension, recorded not resolved: log-scaled congress is worse
standalone and better in the composite (1.98 vs 1.83), replicated on two data
vintages.

### Congress was Senate-only for 2017 to 2025 (2026-08-10)

Two compounding defects. The House PTR backfill had **never been run**, so all
967 House rows were dated 2026. Backfilling added 13,584 trades, and the
congress factor did not move by a single decimal.

Reason: `_congress_sign` understood only Senate eFD's English words
("Purchase", "Sale (Full)"). House PTRs carry SEC letter codes: P (6,689),
S (4,583), S (partial) (2,113), all of which returned 0. Roughly **14,300 of
14,551 House rows never became events.**

Congress events 12.6k to 23.2k, coverage 33% to 61%, and the factor **2.24 to 1.72**. The halving is what Ziobrowski et al. (2011) predict: the House effect
is weaker than the Senate's (55 vs 85 bps/month, attributed to power dilution),
so pooling dilutes. **Every congress figure before this, 2.24, 2.36 and 2.59,
was a Senate number wearing a congress label.**

Parsing order is asserted in tests: the leading token is tested as a code first,
because a bare "s" otherwise falls through to the substring test and "p" would
match the "partial" in "S (partial)".

### Audit: event yield and declared ingest filters (2026-08-10)

Every existing check in `audit.py` is row-level: is what we stored well-formed?
None asked whether the **loaders can read it**, which is the question that
mattered. 71,958 13F EXIT rows produced 0 events; 14,551 House rows produced
~247. Both were invisible to row-level checks and are glaring in a yield column.

Current: congress 88.4%, fund 85.2% (unpriceable EXITs), insider 100%, activism
100%. Reported as a ratio, not pass/fail, because a low yield can be legitimate.

Event yield covers the storage to scoring seam. Nothing covers source to storage,
because those rows never arrive, so the audit now **declares each source's
ingest-time filters**. `insider_buys` holding only P codes is the live example,
and it is why Lakonishok's net purchase ratio is uncomputable.

`sources/house.py` also now counts **scanned** filings separately from **empty**
ones. Those have opposite remedies (one is recoverable by enabling OCR, the
other is nothing to recover), and conflating them made the coverage gap
unmeasurable. Measured for 2024: 442 PTRs to 154 with trades, 240 empty, 48
scanned, 0 failures. So OCR on Railway recovers ~11%, not the majority.

### Every 13F EXIT was being dropped from the fund factor (2026-08-10)

`_load_fund_events` sized every event off `fund_holdings.value`. An EXIT closes
the position, so its `value` is 0, and `log1p(0) == 0` tripped the loader's
`if weight <= 0: continue` guard and **all 71,958 EXIT rows were discarded**.
The fund factor's negative leg had been carrying TRIM alone.

| action | total | dropped |
|---|---:|---:|
| **EXIT** | **71,958** | **71,958 (100%)** |
| NEW | 76,602 | 20 |
| ADD | 153,226 | 0 |
| TRIM | 131,136 | 27 |

`prev_shares` is populated on 71,898 of the 71,958, so the magnitude was
recoverable: an EXIT is now sized as `prev_shares x last close on or before the
filing date` (10-day lookback) from the local `prices` cache, keeping backtests
network-free. Restricted to what the backtest actually scores (S&P 500 union,
2017 onward) this restores 7,309 of 8,100 in-universe EXITs (90.2%) against 34,923
surviving non-EXIT events, roughly **21% more event flow, all on the sell side**.
EXITs with no cached price are still dropped but now log a count instead of
vanishing.

Re-baselined (same DB, same parameters, loader the only change: congress 2.24
and value 0.13 are unchanged to the decimal, which pins the deltas to this fix):

| metric (NW t) | before | after |
|---|---:|---:|
| fund | 2.48 | **2.42** |
| composite | 1.78 | **1.65** |
| L/S spread (gross) | 1.39 | **1.23** |
| L/S spread (net) | 0.96 | **0.78** |

Restoring genuinely missing information lowered the measured edge, the same
direction as the value/split-basis fix, and the third time a CORTEX defect has
turned out to live in what the pipeline threw away rather than in the scorer.

Also confirmed while in here: `fund_holdings.period` stores the 13F **filing
date**, not the quarter-end (only 10 of 432,922 rows fall on a quarter-end; the
modes are the mid-Feb/May/Aug/Nov statutory deadlines). There is no 45-day
lookahead. The column name is misleading and should be renamed.

### Vault retrieval actually reaches the vault (2026-08-10)

The research retriever had been serving a stale, diluted index that no shipped
command could refresh. Three independent faults:

- **`rag-index` was a silent no-op.** `settings.research_dir` defaulted to
  `vault_dir / "research"`, that is `~/Vault/savage_vault/investing/research`, a
  directory that has never existed. `index_vault` logged a warning, returned 0,
  and the CLI printed "Indexed 0 chunks", which reads like success. Meanwhile
  the live index was a 2026-05-23 snapshot of 529 notes built by some one-off
  override. New `DEFAULT_RESEARCH_DIR` points at `savage_vault/wiki/`, and the
  command now exits non-zero when it matches no notes.
- **The corpus was the whole knowledge base.** All 1,278 wiki notes were
  eligible, so exercise science, sabermetrics and frontend notes crowded the
  finance corpus at query time. A query about the CORTEX composite returned
  HRV standards and a McElreath covariance chapter. `index_vault` now parses
  YAML frontmatter and keeps only notes whose `tags`/`domains` intersect
  `rag.RESEARCH_TAGS`. 39 notes, 109 chunks. The same queries now return
  `cortex-signal-register` and `cortex-research-promotion-policy`.
- **Chunk text was half punctuation.** The YAML block was embedded verbatim
  into each note's first chunk, and later chunks carried no indication of which
  paper they came from. Frontmatter is now stripped, `title` and `summary` are
  lifted into the body, and every chunk is prefixed with the note title.

Also: `tier` is populated from the vault's own `retrieval_priority` instead of
a path regex that never matched (all 1,783 old rows had `tier IS NULL`);
re-indexing clears the whole tree so renamed/deleted/newly-excluded notes cannot
survive as orphan chunks; and `retrieve()` returns at most one chunk per note,
so a `k=2` factor panel no longer spends both slots on the same paper.

### Value-factor data integrity (2026-08-10, schema v19)

Two independent defects were corrupting the fundamental block. Both are fixed;
**the pre-registered t-stats below were computed on the corrupted inputs and
must be re-measured before they are quoted again.**

- **Comparative-period tie-break.** `_load_fundamentals` ordered only by
  `filing_date`. One 10-K discloses several comparative periods under a single
  filing date, so tied rows fell in arbitrary storage order and the last-wins
  scan in `_fundamental_asof` kept whichever landed last. WDC was priced off a
  2023 quarter (EPS -2.17); SNDK resolved to a 2022 row with a NULL EPS. Now
  ordered by `(filing_date, period_end)`. Live effect: SNDK #1 to #3, WDC #8 to #5.
- **As-reported EPS vs back-adjusted prices.** The price cache is yfinance
  `auto_adjust=True` (re-based retroactively by every split); EDGAR EPS is on
  the share count in force at filing. Their ratio inflates earnings yield by the
  cumulative split factor: BKNG showed an implied P/E of 1.3, KLAC 6.4, EIX
  5.9. New `splits` + `split_coverage` tables (`cortex.sources.splits`) restate
  EPS onto the adjusted basis inside `_load_fundamentals`. ROE is a ratio of
  aggregates and is left untouched.

`_load_fundamentals` reads only the cached `splits` table and never the network,
so backtests stay reproducible; the cache is warmed by the new `fundamentals`
sync step. Coverage is tracked per ticker because "no splits ever" and "never
fetched" are otherwise indistinguishable, and uncovered names are reported
rather than silently treated as unsplit.

- **`sync-all` now runs `fundamentals`.** `_STEPS` was
  `congress, funds, discover, volatility, executive`. `sync_runs` confirms a
  fundamentals sync had never once run from the refresh path, so the value and
  quality legs were computed against whatever EDGAR data was last pulled by
  hand. The step runs before `discover` and also warms the split cache.

### Methodology hardening + re-baseline (2026-07-16)

The pre-registered suite was re-measured on a hardened pipeline (same data
vintage as the 2026-07-06 journal; only methodology changed. The t>=3.0 bar
itself did not move):

| metric (NW t) | old (2026-07-06) | new (2026-07-16) | why it moved |
|---|---|---|---|
| congress ablation | 2.59 | 2.36 | point-in-time universe |
| fund ablation | 2.29 | 2.64 | point-in-time universe |
| composite | 2.40 | 2.32 | point-in-time universe |
| L/S spread (gross) | 2.98 | 2.55 | point-in-time universe |
| L/S spread (net) | n/a | 2.08 | now costed (10bps long / 25bps short per side) |
| congress OOS verdict | naive t | NW t 2.33 | verdict re-keyed to NW |

Still no factor clears the t>=3.0 gate. **No live trading.**

What changed:

- **Survivorship bias corrected.** Universe is now point-in-time S&P 500
  membership (vendored snapshot history at `data/reference/sp500_history.csv`,
  1996 to present, validated against known adds/removes). Monthly cross-sections
  keep only that month's true members: 742-name union since 2016 vs the 503
  current members the old backtest saw. Residual delisting bias is *measured*
  per month (priced members / true members: mean 91%, worst month 81%) and
  printed with every run; 123 dead tickers are unpriceable by any free source
  (yfinance dropped them; Stooq now fronts a JS challenge that blocks headless
  CSV fetches; fallback code kept, degrades gracefully).
- **Prices persisted in DuckDB** (`prices` + `price_coverage`, schema v18).
  All research price access goes through `cortex.sources.prices` with
  fetch-missing-then-cache semantics, adjustment-drift self-healing on
  dividend re-basing, and a canary probe that distinguishes dead tickers from
  yfinance outages. A backtest re-run is now network-free, ~2s, and
  bit-identical. Live screens (discovery, swing) top up only the missing tail.
- **OOS verdict keys off the Newey-West t-stat** (monthly ICs are
  autocorrelated; the naive IID t overstated significance). Both stats still
  printed.
- **Event study upgraded to a market model**: per-name (α, β) estimated on a
  252d pre-event window (30d gap, min 120 obs), market-adjusted fallback
  disclosed. Overlapping same-ticker events are collapsed per horizon
  (collapsed counts printed). CARs explicitly labeled GROSS. Post-upgrade the
  congress CAR is flat-to-negative at long horizons with a small negative
  pre-event placebo. The monthly-IC framing, not the event CAR, carries the
  congress signal.
- **L/S spread now reported net of costs** (turnover-based, +15bps/side
  short-leg borrow assumption) alongside gross; SPY added as a cap-weighted
  reality-check benchmark next to the EW null.
- **Offline test harness**: `tests/fixtures/prices.py` seeds the price cache
  with deterministic synthetic universes; `tests/test_backtest_integration.py`
  runs the full backtest/OOS/event-study stack network-free (planted-factor
  recovery, PIT-coverage semantics, NW verdict keying, market-model
  beta-stripping, overlap collapse, cost accounting).

### Security
- Removed all hardcoded personal contact details from source. The SEC EDGAR
  `User-Agent` / identity is now read from `CORTEX_SEC_USER_AGENT` via a single helper,
  with a generic placeholder default.
- Removed a hardcoded, machine-specific absolute path from the LLM-analysis code path;
  the `claude` binary is now resolved from `PATH` with an optional `CORTEX_CLAUDE_BIN`
  override.
- **Anthropic token spend gated to the deployment.** All Claude API calls (House-PDF
  OCR and the new executive-mention significance analysis) run only when
  `RAILWAY_ENVIRONMENT` / `CORTEX_PRODUCTION` is set, via `config.llm_calls_enabled()`,
  so local development and testing never bill the API key. `CORTEX_ALLOW_LLM=1`
  overrides for a deliberate local run.

### Changed
- **Frontend is now built during the Railway deploy** instead of committing `web/dist`.
  The NIXPACKS plan (`nixpacks.toml`) extends the Python toolchain with Node and runs
  `npm install && npm run build`, so the served SPA can never go stale relative to source.
  `web/dist` is no longer tracked in git. Getting this to work required three rounds of
  fixes against nixpkgs version pinning constraints:
  - Railway's nixpkgs snapshot resolves `nodejs_22` to 22.10.0, which is below Vite 8's
    minimum (20.19+ or 22.12+), causing the rolldown native binding to install the wrong
    linux variant.
  - `npm ci` strictly follows `package-lock.json` (generated on macOS), so
    `@rolldown/binding-linux-x64-gnu` is absent and the build fails on the Railway host.
    Switched to `npm install` so the linux binding is resolved at build time.
  - Railway does not expand `[variables]` from `nixpacks.toml` as build-time env vars,
    so `pip install uv==$NIXPACKS_UV_VERSION` expands to `pip install uv==` and fails.
    The uv version is now hardcoded in `[phases.install]`.
  - The nixpkgs snapshot contains no `nodejs_24` and caps `nodejs_22` at 22.10.0. The
    final fix sidesteps nixpkgs entirely: the build phase downloads the official Node
    22.15.0 tarball and prepends `/usr/local/bin` to `PATH`.

### Added
- **WHALES tab**: dedicated institutional 13F view for hedge-fund and asset-manager
  positioning. Surfaces a conviction-map bubble scatter (position size vs. number of
  holders), most-crowded names, biggest single bets, and a clickable manager leaderboard
  with action filters. 13F institutional buys were previously embedded in the main
  dashboard; they now live here with their own full-page workspace.
- **TradeImpactChart**: reusable price-at-trade visualization added to both the Congress
  and Whales tabs. Every filing row expands to show the stock's price on the trade date
  and how it has moved since, with a plain-language verdict ("up 12.6% since the buy").
- **`/admin/sync/executive` endpoint**: `railway run` cannot write to Railway's `/data`
  volume, so a POST endpoint was added that spawns the exec-mention sync as a subprocess
  on the live container, enabling manual seeding of the executive-mentions table on a
  fresh deployment.
- **Per-row significance glow** on White House Buzz entries: left border accent and
  subtle background tint (cyan = high significance, amber = medium) applied to each row
  so significance is visible at a glance, not just in the badge chip.
- **Executive-mentions signal**: organic discovery of companies named by the
  administration. Scans whitehouse.gov category RSS feeds (statements / fact-sheets /
  releases) for S&P 500 companies via a precision-first entity matcher (full-phrase
  multi-word names, distinctive single tokens, common-word/ticker stoplists), then
  enriches each hit with a market-reaction gate (abnormal return vs SPY at +1/+5/+20
  trading days) and a Claude Haiku significance verdict that doubles as a precision
  backstop. New `executive_mentions` table (schema v15), `event-study --signal
  executive`, and a dashboard "White House Buzz" reaction timeline (scrollable, with
  per-mention source links). CLI: `exec-mention add|list|sync`.
  - First iteration used GDELT for organic discovery but was rejected as too noisy
    (global news co-occurrence, common-word company-name collisions). Replaced with
    direct whitehouse.gov RSS ingestion, which carries full transcript text, exact dates,
    and a guaranteed administration speaker.
  - Entity matcher is precision-first: multi-word names match only as the full phrase;
    single tokens only if distinctive (len >= 4, not in the common-word stoplist); no
    bare-ticker matching (ICE / IP / WM acronym collisions); known generic-phrase names
    skipped; nav-boilerplate guard.
  - Verified on live data: 30 mentions / 22 tickers (Nvidia $500B commitment, Boeing,
    Intel, DoorDash, Pfizer, Freeport...); price-reaction gate correctly signs pharma
    price-cap deals as negative.
- **Plain-English mode**: an app-wide toggle (persisted) that translates the quant
  surface (factor codes, z-scores, composite percentiles, section labels) into plain
  language so the app reads clearly for non-quants. `MOM/LVOL/SHR/VAL/QUAL`  to 
  `Price trend / Steadiness / Efficiency / Value / Quality`; `+2.88z`  to  `top 0.2%`;
  `DISCOVERED / ALGO BUYS`  to  `TOP PICKS / STRONG BUYS`. `lib/plain.ts` is the single
  source of truth for term translations, reused across all views.
- **Operations & deployment layer**: per-source refresh (`sync-all --only ...`),
  per-source freshness telemetry (`/freshness` + a dashboard strip), failure alerting to
  a webhook, DuckDB snapshot/backups (`cortex backup`, pruning, optional S3), a nightly
  factor-stat history snapshot (`snapshot-factors`  to  `/factor-history`), and Railway cron
  services that trigger work over HTTP against the volume-owning web process
  (`trigger-refresh` / `trigger-backup` / `trigger-snapshot`). The full refresh runs as
  an isolated subprocess and survives crashes (health check + restart policy).
- Root `README.md` (portfolio overview) and this changelog.

## [0.1.0], 2026-05-24

The first complete build: factor engine, alt-data ingestion, decision-quality system,
and the React portal.

### Added
- **Decision-quality core**: thesis CRUD with mandatory falsifiers and review dates,
  Brier-score calibration with per-conviction hit-rate buckets, a review queue, and
  attachable dissents (schema v2). Markdown vault mirror of all theses.
- **CORTEX factor engine**: point-in-time multi-factor equity ranking (momentum,
  low-volatility, Sharpe, value, quality) over the S&P universe, with cross-sectional
  standardisation and a `discover` command.
- **Alternative-data factors & ingestion**: congressional trading flow (Senate eFD),
  Form 4 insider open-market buys via SEC bulk-index parsing, 13F institutional fund
  flow with historical backfill, 13D activist stakes, and point-in-time EDGAR XBRL
  fundamentals. All sources are free; all writes are idempotent (SHA-256 dedup).
- **Pre-registered backtest harness**: `backtest` and `congress-oos` evaluate factors
  against pre-registered hypotheses and an out-of-sample window, applying a
  multiple-testing-corrected t-statistic gate and reporting survivorship and
  coverage caveats inline.
- **Research RAG**: local `fastembed` embeddings indexed in DuckDB's native vector
  search (HNSW) for grounded per-ticker context.
- **FastAPI service**: typed JSON API (theses, reviews, calibration, congress, funds,
  candidates, screens, per-ticker context and history) that also serves the compiled
  SPA from a single origin. Optional LLM-backed factor commentary via the `claude` CLI.
- **React portal**: glass-premium, dark-only UI: CORTEX command-center dashboard with
  live factor z-score meters and price sparklines, congressional-flow analytics, a
  volatility / dollar-swing screen, the calibration reliability diagram, thesis
  management, and a stock detail modal. Built on TanStack Query, lightweight-charts,
  and Recharts.
- **Design system**: `DESIGN.md`, a locked anti-action-bias visual contract
  (tokens, components, motion) that all generated UI adheres to.
- **CLI**: `cortex` entrypoint covering database init, data syncs/backfills, discovery,
  screens, backtests, calibration, the RAG index, the vault mirror, and `serve`.
- **Storage**: DuckDB columnar store with a schema-version migration table and a
  context-managed connection helper.

### Engineering
- `src/` layout managed with `uv`; `ruff` + `pyright` configured.
- 69 tests covering storage, calibration, RAG, backtest math, and HTTP-mocked sources.

[Unreleased]: https://github.com/robsavage619/savage-wall-street-tracker/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/robsavage619/savage-wall-street-tracker/releases/tag/v0.1.0
