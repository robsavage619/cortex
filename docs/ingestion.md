# Ingestion

Last verified 2026-09-19.

Fourteen source modules under `src/cortex/sources/`, every one of them a free
public feed. There are no paid data vendors. That constraint is what makes most of
the problems below problems: a vendor sells you a clean panel, and reconstructing
one from raw filings means meeting each source's own idiosyncrasies head on.

| Source | Feed | Rows in the store |
|---|---|---:|
| Prices | yfinance, cached in DuckDB | 1,555,751 |
| 13F institutional holdings | SEC EDGAR via edgartools, 14 curated managers | 432,922 |
| Congressional trades | Senate eFD + House Clerk PTR | 26,227 |
| Fundamentals | SEC EDGAR XBRL | 21,538 |
| Insider buys | SEC EDGAR Form 4, P-coded non-derivative | 13,008 |
| Short volume | FINRA Reg SHO daily files | 1,136,046 |
| Activist stakes | SEC EDGAR SC 13D | 1,546 |
| Executive mentions | White House transcripts | 30 |

All sync commands are idempotent through `ON CONFLICT (id) DO NOTHING`.

## SEC EDGAR

### Form 4 XML filenames are not standardised

`form4.xml` works for roughly half of filers. Filing agents use their own names:
Edgar Online writes `rdgdoc.xml`, Workiva writes `wf-form4-*.xml`, and so on.
Guessing the filename does not work at scale.

The canonical source is `data.sec.gov/submissions/CIK{cik10}.json`, field
`filings.recent.primaryDocument`. One gotcha: `primaryDocument` is sometimes
`xslF345X06/filename.xml`, which is an XSLT rendering path rather than the data
file. Strip the subdirectory. Older filings paginate through `filings.files[]`,
each page fetched from `data.sec.gov/submissions/{name}`.

### Use the bulk index, not per-company queries

`https://www.sec.gov/Archives/edgar/full-index/{year}/QTR{N}/form.idx` is about
10 MB per quarter and contains every filing. Parse it right to left, because the
company-name field contains spaces: `parts[-1]` is the filename, `parts[-2]` the
date, `parts[-3]` the CIK.

Pre-loading the primary-document map costs roughly 75 seconds for 503 CIKs at
0.15s each. That pays for itself immediately against 282,000 filename guesses.

### Rate limits

The hard cap is about 10 requests per second. The ingestion runs 3 workers with a
12-second back-off on a 429. After several failed runs the whole IP gets
throttled, and the way to tell is to poll a known-good file until it returns 200:

```bash
curl -s -o /dev/null -w "%{http_code}" https://www.sec.gov/files/company_tickers.json
```

The `User-Agent` comes from `CORTEX_SEC_USER_AGENT` via
`cortex.config.sec_user_agent` and must be in `"Name email"` format. SEC returns
403 for anything else. It is never hardcoded, because it is a contact identity.

## Congress: two chambers, two languages

Senate eFD writes English: "Purchase", "Sale (Full)", "Sale (Partial)". House PTRs
carry SEC letter codes: "P", "S", "S (partial)", "E".

Any parser touching `transaction_type` has to handle both, and has to test the
leading token as a code **first**. Test the English words first and a bare "s"
falls through while "p" matches the "partial" inside "S (partial)". Getting this
wrong silently zeroed about 14,300 of 14,551 House rows, and the table looked
full the whole time. See [factor-journal.md](factor-journal.md).

Congress notional is weighted raw rather than through `log1p`, unlike the fund and
insider loaders. This is deliberate: log scaling collapses the factor, from 1.72
to 1.13 on two-chamber data and 2.24 to 1.52 on Senate-only. The signal genuinely
lives in a handful of very large disclosures, which makes the factor fragile. Do
not normalise the inconsistency away without reading that result first.

Amendments are marked rather than deleted. Roughly 17% of the Senate table was
amendment double-counts; the serving paths and the backtest loader exclude rows
flagged `amended` and rows quarantined by `ticker_ok = FALSE`.

## FINRA Reg SHO

The CDN answers **403, not 404**, for any file it is not serving. A weekend and a
2017 session are indistinguishable at the HTTP layer, so treating 403 as fatal
aborts a backfill on its first Saturday.

The archive is rolling, roughly 8 years. 2018-08 onward returns 200; 2018-07-02
and earlier returns 403. The short factor therefore cannot reach the 2017 backtest
start and has zero coverage for the first 19 months.

## Prices

All research prices go through `cortex.sources.prices`, backed by the DuckDB
`prices` and `price_coverage` tables. Research code never calls `yf.download`
directly, because a backtest that hits the network is not reproducible.

yfinance signals failure two different ways, and the difference matters. A dead
ticker in a mixed batch comes back as an all-NaN **column**. A batch where every
ticker is dead comes back as an **empty frame**, which is indistinguishable from
yfinance being down. The cache runs a SPY canary probe to tell those apart before
it records names as permanently unpriceable.

The Stooq CSV endpoint, the intended fallback for delisted names, has been behind
a JavaScript proof-of-work challenge since 2026-07-16. It currently prices zero
names. The resulting gap shows up as the backtest's universe-coverage ratio:
621 of 742 union names priceable, monthly coverage mean 91%, worst month 81%.

## Splits, and the two bases problem

The price cache is yfinance with `auto_adjust=True`, back-adjusted to today.
EDGAR EPS is as-reported at the filing's share count. These are different bases,
and dividing one by the other inflates earnings yield by the full cumulative split
factor.

`cortex.sources.splits` restates EPS inside `_load_fundamentals`. It reads the
cache only and never the network, so backtests stay reproducible. Coverage is
tracked per ticker in `split_coverage`, because "no splits ever" and "never
fetched" are otherwise the same empty result.

## Point-in-time S&P 500 membership

`sp500_members_asof()` and `sp500_union()` read a vendored CSV at
`data/reference/sp500_history.csv`, sourced from fja05680/sp500 with the retrieval
date and a payload SHA256 in the file header. Refresh by re-downloading.

`sp500_members_asof` raises rather than returning the earliest snapshot for dates
before 1996-01-02, because silently returning it would fabricate history.

## LLM-assisted extraction

Two paths use the Anthropic API: House PTR PDF extraction (`sources/house.py`) and
executive-mention significance classification (`sources/executive.py`, Haiku).
Both are gated on `RAILWAY_ENVIRONMENT` or `CORTEX_PRODUCTION` through
`cortex.config.llm_calls_enabled`, so local development and the test suite never
spend tokens. `CORTEX_ALLOW_LLM=1` overrides it for a deliberate one-off.

The executive-mentions pipeline is precision-first: official White House
transcripts as the source, a multi-stage entity matcher to keep false positives
out, an abnormal-return gate against SPY, and the LLM only as a final significance
classifier on what survives.
