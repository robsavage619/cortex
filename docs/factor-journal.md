# Factor journal: what changed, and what it cost

Every entry is a code or data change with the measured before and after. The
convention is that a t-statistic is never reported without the change that moved
it, and a change that lowers a t-statistic is kept and written up the same way as
one that raises it.

The headline: over seven changes the composite went from 1.89 to 1.67. Six of the
seven lowered it. That is the expected shape when the defects being fixed were all
feeding the model signal it had not earned.

## Summary

| Date | Change | congress | fund | composite | L/S gross | L/S net |
|---|---|---:|---:|---:|---:|---:|
| 2026-07-06 | pre-remediation baseline | 2.40 | 2.58 | 1.89 | n/a | n/a |
| 2026-07-06 | dedupe keys, amendment exclusion, brain alignment | 2.59 | 2.29 | 2.40 | 2.98 | n/a |
| 2026-07-16 | point-in-time universe, costed L/S | 2.36 | 2.64 | 2.32 | 2.55 | 2.08 |
| 2026-08-10 | value-factor split basis and period ordering | 2.24 | 2.48 | **1.78** | 1.39 | 0.96 |
| 2026-08-10b | 13F EXIT events restored | 2.24 | 2.42 | 1.65 | 1.23 | 0.78 |
| 2026-08-10c | derived bar, 3 pre-registered constructions | 2.24 | 2.62 | 1.90 | 1.61 | 1.21 |
| 2026-08-10d | House backfill and the transaction-code defect | **1.72** | 2.62 | 1.83 | 1.41 | 1.02 |
| 2026-08-10e | short-interest factor added | 1.72 | 2.62 | 1.83 | 1.41 | 1.02 |
| 2026-09-19 | no code change, one more month of data | 1.74 | 2.66 | 1.67 | 1.19 | 0.82 |

All figures are Newey-West HAC t-statistics on the monthly information
coefficient. The last row is a re-measurement, not a change: the backtest window
extended from 2026-07-31 to 2026-08-31 (T = 114 to T = 115) and the numbers moved
on their own. That drift is worth its own line, because it is the scale of noise
against which every delta above should be read.

---

## 2026-07-06: dedupe keys, amendment duplicates, brain alignment

congress 2.40 -> 2.59, fund 2.58 -> 2.29, composite 1.89 -> 2.40, L/S first
measured at 2.98.

Three defects, found by the first data-integrity audit. Roughly 17% of the Senate
congress table was amendment double-counts: 1,978 excess rows out of 11,738. Every
congress statistic computed before this included them. The insider dedupe key was
3 fields and collapsed 34% of all Form 4 purchase rows, because same-filer
same-day lots share those three fields; re-syncing on a 5-field SHA256 key
recovered 4,417 rows, a 51% increase. And discovery was computing a different
signal from the backtest, so the live ranking was not the thing that had been
tested.

Full audit trail: [archive/remediation-audit-2026-07-06.md](archive/remediation-audit-2026-07-06.md).

## 2026-07-16: point-in-time universe and costed long-short

congress 2.59 -> 2.36, fund 2.29 -> 2.64, composite 2.40 -> 2.32, L/S 2.98 -> 2.55
gross, 2.08 net.

The universe had been the 503 current S&P 500 members, which is survivorship bias
in its purest form. It became the 742-name historical union since the warmup
start, with each monthly cross-section masked to that month's true members.
Priced-member coverage runs at a mean of 91% and a worst month of 81%, and the
residual delisting gap is now reported in the backtest output rather than left
implicit.

The long-short spread picked up transaction costs at the same time: 10bps long
and 25bps short, per side. The out-of-sample verdict was re-keyed from the raw t
to the NW t.

Event-study CARs were rebuilt as market-model with overlap collapsing, and came
out flat-to-negative for congress at long horizons. The monthly IC framing carries
whatever signal is there; the event CARs do not.

## 2026-08-10: the value factor was measuring a split artefact

congress 2.36 -> 2.24, fund 2.64 -> 2.48, composite 2.32 -> **1.78**, L/S 2.55 ->
1.39 gross, 0.96 net. Standalone value fell to 0.13.

Two defects, both in `_load_fundamentals`, both feeding the fundamental block
signal that did not exist.

First, the as-of query ordered only by `filing_date`. A 10-K carries comparative
prior periods that all share one filing date, so they tied and last-wins kept an
arbitrary row. WDC was priced off a 2023 quarter. SNDK was left with a NULL EPS.
Any as-of query against `fundamentals` has to order by `(filing_date, period_end)`
or the tie-break is storage order.

Second, and worse: as-reported EDGAR EPS was being divided by back-adjusted
yfinance prices. Those are different split bases. Earnings yield came out inflated
by the full cumulative split factor, so BKNG showed an implied P/E of 1.3 on a
25:1 split and KLAC 6.4 on a 10:1. The fix restates EPS onto the adjusted basis
through a cached `splits` table, read locally so backtests stay reproducible.

Standalone value is now 0.17. The value leg carries nothing, and the 2.32
composite had been borrowing from it. Part of the delta is confounded with a
same-day congress and house refresh.

## 2026-08-10b: every 13F exit was being dropped

fund 2.48 -> 2.42, composite 1.78 -> **1.65**, L/S 1.39 -> 1.23 gross, 0.78 net.
congress (2.24) and value (0.13) unchanged to the decimal, which pins the delta to
this fix alone.

`_load_fund_events` sized every event off the `value` column. An EXIT closes the
position, so `value` is 0 by construction, `log1p(0)` is 0, and the `weight <= 0`
guard dropped the row. All 71,958 EXIT rows were being discarded. The negative leg
of the fund factor had only ever been TRIM.

Events are now sized as `prev_shares` times the last close on or before the filing
date, with a 10-day lookback, from the local price cache. That restores 7,309 of
8,100 in-universe exits, about 21% more event flow, all of it sell-side.

This was the third consecutive defect that lived in what the pipeline discarded
rather than in the scorer. The pattern is now the first thing to check.

## 2026-08-10c: the derived bar, and three pre-registered constructions

fund 2.42 -> **2.62**, composite 1.65 -> **1.90**, insider -0.35 -> -0.19, L/S
1.23 -> 1.61 gross, 1.21 net. congress unchanged.

The bar stopped being a constant. See [evaluation.md](evaluation.md).

Three construction changes, all with hypotheses written to the vault before any
run:

**13F sells damped to 0.5 of buy weight.** Agarwal (2013) finds acquisitions at
+7.06% DGTW over 12 months (t = 3.95) against disposals at +2.94% (t = 1.42), so
signing them symmetrically was unsupported. Pre-registered at two fixed values and
deliberately not swept, because a swept constant is a fitted parameter and the
honest test count would then be the number of values tried. Measured: 1.0 gives
2.42, 0.5 gives 2.62, 0.0 gives 1.73. An interior optimum is the shape the theory
predicts.

**Insider reweighted** to count distinct filers and rank dollars within-month
instead of raw `log1p`. It moved toward zero as predicted and is still dead,
because Lakonishok & Lee find the effect is entirely small-cap and this universe
is not.

**Congress on a log scale: tested and reverted.** It collapsed congress from 2.24
to 1.52, firing the pre-registered falsifier. The reading is that the signal lives
in a handful of very large disclosures, which makes the factor far more fragile
than 2.24 suggested.

## 2026-08-10d: the congress factor had been Senate-only for eight years

congress 2.24 -> **1.72**, coverage 33% -> 61%, composite 1.90 -> 1.83, L/S 1.61 ->
1.41 gross, 1.02 net.

Two changes, both data completeness, and the second is the interesting one.

The House PTR backfill had never been run. All 967 House rows carried 2026 dates,
so the congress factor was Senate-only for 2017 through 2025. Backfilling added
13,584 trades and took House to 14,551 against Senate's 11,676.

That alone changed nothing. `_congress_sign` only understood the Senate's English
words ("Purchase", "Sale (Full)"), while House PTRs carry SEC letter codes ("P",
"S", "S (partial)", "E"). About 14,300 of 14,551 House rows returned 0 and were
dropped. The data was in the table and the factor could not see it.

Fixed, congress events went from 12.6k to 23.2k. The halving of the signal is what
Ziobrowski (2011) predicts: the House effect is weaker than the Senate's, 55
against 85 bps per month, so pooling dilutes. **The old 2.24 was a Senate-only
number.**

Any parser touching `transaction_type` has to handle both languages, and has to
test the leading token as a code first. Test for "s" before "S (partial)" and a
bare "s" falls through while "p" matches the "partial" in "S (partial)".

Congress log-scale was retested on the complete two-chamber data and reverted
again, 1.72 to 1.13. The fragility finding holds across both chambers.

## 2026-08-10e: short interest, pre-registered before the download

New `short` factor at NW t 1.87, coverage 79%, positive in 58% of months. Third
strongest, correct sign, and the hypothesis and falsifier were written before the
data existed locally.

Construction is fixed from Boehmer, Jones & Zhang (2008) and not swept: short
volume over total volume, 5-day formation, 20-day hold, negative sign. Flow, not
level, because the paper finds short flow drives out short interest in 13 of 15
reversed sorts.

Adding it moved the own-family bar from 3.21 to 3.24, which is the derived gate
working as intended. Nothing clears.

Two operational notes. FINRA's CDN answers 403, not 404, for any file it is not
serving, so a Sunday and a 2017 session look identical at the HTTP layer; treating
403 as fatal aborts a backfill on its first weekend. And the archive is rolling at
roughly 8 years: 2018-08 onward returns 200, 2018-07-02 and earlier returns 403.
The short factor cannot reach the 2017 backtest start and has zero coverage for
the first 19 months, so its t-statistic sits on a shorter and later sample than
every other factor.

A `research_trials` table was added in the same change, logging the cumulative
trial count. It reads 104 since instrumentation began and is a lower bound, since
runs before it are unrecorded. That count is the Harvey-Liu haircut input nobody
records.

## Standing tensions, unresolved

**Log-scaled congress is worse standalone and better in the composite** (1.13
against 1.98). Replicated on two data vintages, so it is not noise. Settled by
scoring standalone, not by averaging the two readings.

**The fund factor does not measure the mechanism it cites.** Renaissance
Technologies is 73.7% of `fund_holdings` rows since 2017 and Bridgewater another
13.3%; the six high-conviction managers are 3.3% combined. Cohen/Polk/Silli's Best
Ideas is about concentrated conviction, and RenTec runs diversified statistical
arbitrage. Any fund-factor result is largely a statement about one manager.

**The table holds quarter-over-quarter diffs for 14 curated managers**, not full
portfolios, so there are no HOLD rows and conviction weighting against a passive
benchmark is not computable from it.

**Flow factors are stronger in large caps inside this universe**, which contradicts
the literature's prior: fund 3.04 large against 1.49 small, congress 1.76 against
0.68, quality 1.38 against 0.50. Only short and trend lean small. So widening the
universe downward on the "these anomalies are small-cap" argument is not supported
by this data. The caveat on the caveat is that both halves of the S&P 500 are
large-cap by the papers' standards, so this cannot refute Lakonishok or
Bernard-Thomas, only show that their prior does not hold inside this range.
