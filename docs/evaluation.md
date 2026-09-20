# How a factor is evaluated

Last verified 2026-09-19. Every number below is the output of
`uv run cortex backtest` on that date, against the live DuckDB store.

The design goal of this harness is not to find alpha. It is to make it hard to
believe in alpha that is not there. Most of what follows exists because a
plausible-looking number turned out to be an artefact.

## The bar is derived, not asserted

CORTEX used to hardcode `t >= 3.0` and call it Bonferroni-corrected. Neither half
was right. 3.0 is the headline recommendation of Harvey, Liu & Zhu (2016); their
own Bonferroni benchmark for the 316-factor published zoo is 3.78. And both Harvey
papers recommend Benjamini-Hochberg-Yekutieli false-discovery-rate control rather
than Bonferroni, because factor tests are correlated and family-wise control is
punishing when they are.

`significance.build_gate(n_tests)` now computes the bar from the run's own test
count. Two bars, assigned by family in code ahead of the run, so the choice cannot
be made after seeing a result:

| Family | Factors | Bar (2026-09-19, 13 tests) |
|---|---|---:|
| Own-family BHY | congress, fund, insider, activism, short | **3.24** (Bonferroni 2.89) |
| Zoo-draw BHY | mom, trend, vol, value, quality, pead | **4.21** (Bonferroni 3.78, HLZ N = 316) |

The zoo draws are lifted from the published literature, so the family of tests is
the literature and HLZ's N applies. The own-family signals are a private set, so
the family is CORTEX's own test count.

Two consequences worth stating plainly:

- **With the Yekutieli dependence correction, BHY is stricter than Bonferroni for
  a lone discovery.** The rank-1 critical value carries a factor of c(N). BHY only
  becomes more lenient once several tests are already significant.
- **Adding a factor raises the bar for every other factor.** Pre-registering the
  short-interest signal moved the own-family bar from 3.21 to 3.24. That is the
  honest cost of testing another idea, and it is charged automatically.

If you test k configurations of a factor, the honest N includes all k. Two extra
fund configurations moved the bar from 3.21 to 3.26 in an earlier run.

## The gate scores the standalone factor, not the composite

This kept resurfacing because the two disagree: log-scaled congress is worse
standalone (1.13) and better in the composite (1.98), replicated on two data
vintages. It is settled in `significance.py` rather than re-argued each time.

Standalone wins for two reasons. The factor is the empirical claim and the
composite is packaging layered on top, so the claim should be judged before its
packaging. And the composite has free parameters (block weights, membership) while
an ablation has none, so promoting on composite performance invites exactly the
fitting the gate exists to prevent.

The composite is still reported and is still the thing that would be traded. It
just does not earn a factor its place.

## What the harness reports

Every t-statistic is Newey-West HAC-adjusted with a Bartlett kernel. Newey & West
(1987) do not specify lag selection; the `4(T/100)^(2/9)` plug-in rule comes from
later literature and gives lag 4 at T = 115, which is at the edge of the paper's
own growth condition.

Alongside the per-factor ablation:

- **Long-short spread**, gross and net of costs (10bps long, 25bps short, per side)
- **Factor-IC correlation matrix**, plus the mean off-diagonal absolute
  correlation the Harvey-Liu Sharpe haircut needs as an input
- **Size split**: each factor's NW t within the larger and smaller half of each
  month's cross-section, split at that month's median trailing-60d dollar volume
- **Tail decomposition**: mean monthly excess return of each tail against its own
  cross-section, because an IC cannot say which end of a factor carries it
- **Direction homogeneity**: share of months with positive IC
- **Decile monotonicity** across D1 to D10
- **Point-in-time universe coverage**, mean and worst month
- **Cumulative trial count**, labelled as a lower bound

Subsample t-statistics are diagnostics, never promotion candidates. Selecting a
subsample after seeing it is the oldest way to manufacture significance.

## Current results

`uv run cortex backtest`, 2026-09-19. Window 2017-01-31 to 2026-08-31, 622 names,
monthly rebalance, 115 observations.

```
factor       mean IC       t    NW t    bar   cover    +mo   lgNWt   smNWt     topD     botD
fund         +0.0189    2.58    2.66   3.24    97%    62%    3.04    1.49   +0.40%   -0.36%
short        +0.0149    1.73    1.88   3.24    79%    58%    1.30    1.54   +0.24%   -0.22%
congress     +0.0104    1.69    1.74   3.24    62%    59%    1.76    0.68   +0.19%   -0.14%
quality      +0.0110    1.13    1.10   4.21    83%    54%    1.38    0.50   +0.19%   +0.34%
trend        +0.0073    0.36    0.57   4.21   100%    51%    0.39    0.80   +0.27%   -0.19%
mom          +0.0036    0.18    0.23   4.21   100%    53%    0.30   -0.02   +0.33%   +0.16%
value        +0.0022    0.16    0.17   4.21    89%    50%   -0.24    0.60   +0.24%   +0.50%
insider      -0.0029   -0.28   -0.26   3.24    22%    55%    0.31   -0.34   -0.17%   +0.11%
vol          -0.0114   -0.49   -0.56   4.21   100%    49%   -0.76   -0.21   -0.26%   +0.64%
activism     -0.0179   -1.49   -1.58   3.24    15%    43%   -1.13   -1.20   -0.72%   -0.23%
```

Nothing clears. The BHY sweep over all ten factors returns no discoveries.

| Series | IC | NW t | CAGR | Sharpe | maxDD |
|---|---:|---:|---:|---:|---:|
| CORTEX composite | +0.0178 | 1.67 | +15.2% | 0.89 | -22.5% |
| Price-only null model | +0.0051 | 0.36 | +14.6% | 0.84 | -20.3% |
| Price + fundamental, no flow | +0.0090 | 0.72 | +13.2% | 0.77 | -24.4% |
| Equal-weight S&P 500 benchmark | | | +12.5% | 0.79 | |
| SPY, cap-weighted reality check | | | +15.3% | 1.00 | |

Long-short spread (D10 minus D1, beta-stripped): gross +0.5217% per month,
NW t 1.19, CAGR +4.3%, Sharpe 0.31. Net of costs: +0.3583% per month, NW t 0.82,
CAGR +2.2%, Sharpe 0.21.

Mean off-diagonal absolute IC correlation is 0.200. Deciles are broadly monotone
(D1 +7% to D10 +16%) but not cleanly so in the middle.

The composite beats the equal-weight benchmark on CAGR and loses to SPY on
Sharpe. Read that as the honest summary: over this sample the model does not beat
holding the index.

## Caveats print next to the numbers

A vault note declares which factors it bears on through `cortex_factors`
frontmatter. Notes typed `research-finding` with a `current_verdict` are treated
as caveats and printed beside the factor's number, because a citation rarely
changes a decision but a caveat does:

```
KNOWN CAVEATS (first-party findings from the vault):
 congress   fragile, 1.72 raw collapses to 1.13 on a log scale
 fund       structural concern; no change made, pre-registration candidate
 fund       defect fixed; fund and composite fall, which is the credible direction
 insider    blocked, needs S-coded Form 4 ingestion before the fix is testable
 short      evaluated 2026-08-10, NW t 1.87, falsifier survived, not promoted
```

Wildcard notes (`cortex_factors: ["*"]`, methodology that applies to everything)
are deliberately excluded from the per-factor caveat list. A global finding is a
real caveat, but surfacing it against every factor buries "distrust this number"
under "distrust all numbers".

The link is synced into DuckDB by `cortex rag-index`, not read live, because the
deployed app has no vault on disk. Write a note, re-index; that is the whole
update path.

## Test suite

```
198 passed in 13.38s
40% line coverage over 5,874 statements
```

3,339 lines of tests against 13,903 lines of source, one test line per 4.2 source
lines. Coverage is deliberately uneven: it is high in the code that produces
numbers and low in fetch plumbing.

| Area | Coverage |
|---|---:|
| `storage/schemas.py` | 96% |
| `thesis.py` | 98% |
| `sources/short_interest.py` | 94% |
| `storage/db.py` | 82% |
| `volatility_screen.py` | 83% |
| `sources/universe.py` | 67% |
| `sources/prices.py` | 44% |
| `sources/house.py`, `sync_job.py`, `sources/legislators.py` | 0% |

HTTP sources are mocked with `respx`; nothing in the suite touches live EDGAR.
The frontend has no tests at all.

Several tests exist only because a specific bug shipped and was found later: 13F
exit events silently dropped, House transaction codes unparsed, an unquoted YAML
wildcard removing notes from the index. Each carries the story in its docstring so
the reason survives the fix. See [factor-journal.md](factor-journal.md).

## The audit that checks its own blind spot

`cortex audit-integrity` reports event yield per source: rows stored against
events actually scored. It exists because every other check was row-level, and
row-level checks missed five separate defects of the same shape, which is
well-formed data the loader cannot read. A table can be full and a factor can
still see nothing.

## Static analysis

- `ruff check` passes repo-wide.
- `ruff format --check` reports 5 files that would be reformatted:
  `src/cortex/calibration.py`, `src/cortex/sources/executive.py`,
  `src/cortex/sources/legislators.py`, `tests/test_congress.py`,
  `tests/test_funds.py`.
- `pyright` (basic) reports 50 errors: 24 in `src` (12 in `sources/house.py`,
  11 in `sources/executive.py`, 1 in `api.py`) and 26 in `tests` (20 of them in
  `tests/test_thesis.py`). The factor, storage and decision core is clean. The two
  source files are third-party response parsers and are tracked as type debt.
