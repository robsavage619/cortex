# Research sources behind each factor

Last verified 2026-09-19 against `src/cortex/backtest.py` and `src/cortex/composite.py`.

Every factor in the model traces to a paper, with one exception noted below. The
papers are held in a local Obsidian vault, embedded into DuckDB by
`cortex rag-index`, and linked to the factors they bear on through
`cortex_factors` frontmatter. Findings that carry a verdict print as caveats next
to the factor's number in `cortex backtest`. See [evaluation.md](evaluation.md).

## What is actually scored

The ten factors in the per-factor ablation are `mom`, `trend`, `vol`, `value`,
`quality`, `congress`, `fund`, `insider`, `activism`, `short`. The composite that
discovery and the backtest both compute uses six of them in three equal blocks:

| Block | Factors |
|---|---|
| Price | `mom` (12-1), `trend` (continuous distance to the 200d SMA) |
| Fundamental | `value` (earnings yield), `quality` (ROE) |
| Flow | `congress` (net buy pressure), `fund` (13F net buy, sells damped to 0.5) |

Three things are deliberately not in it, and the reasons are journaled in
`composite.py` rather than left implicit:

- Low volatility was removed from the price block on 2026-05-23.
- Insider Form 4 was excluded from the flow block on 2026-05-28 after measuring
  NW t = -0.43 against a pre-registered "drop if t < 1.0" rule.
- Sharpe was never in any tested composite. The dashboard renders an `SHR` meter
  and the `candidates` table stores `z_sharpe`, both marked display-only in code.

`value` is earnings yield alone, not a P/E and P/B and EV/EBITDA composite.
`quality` is ROE alone, not gross profitability and ROE and debt-to-equity. Earlier
versions of this list described the wider composites; they were never built.

## Papers, by factor

Tier 1 directly powers a factor. Tier 2 is portfolio construction and practitioner
context.

### Momentum, `mom` (12-1 trailing return)

| Tier | Citation | Find it |
|---|---|---|
| 1 | Jegadeesh, N., & Titman, S. (1993). "Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency." *Journal of Finance*, 48(1), 65-91. | JSTOR |
| 1 | Carhart, M. M. (1997). "On Persistence in Mutual Fund Performance." *Journal of Finance*, 52(1), 57-82. Adds the momentum (UMD) factor. | JSTOR |
| 2 | Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012). "Time Series Momentum." *Journal of Financial Economics*, 104(2), 228-250. | AQR Library / SSRN |

### Trend, `trend` (distance to the 200-day SMA)

| Tier | Citation | Find it |
|---|---|---|
| 1 | Faber, M. T. (2007). "A Quantitative Approach to Tactical Asset Allocation." *Journal of Wealth Management*, Spring 2007. | SSRN |

### Value, `value` (earnings yield, split-basis corrected)

| Tier | Citation | Find it |
|---|---|---|
| 1 | Fama, E. F., & French, K. R. (1992). "The Cross-Section of Expected Stock Returns." *Journal of Finance*, 47(2), 427-465. | JSTOR |
| 1 | Fama, E. F., & French, K. R. (1993). "Common Risk Factors in the Returns on Stocks and Bonds." *Journal of Financial Economics*, 33(1), 3-56. | NBER |
| 2 | Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013). "Value and Momentum Everywhere." *Journal of Finance*, 68(3), 929-985. | AQR Library / SSRN |

### Quality, `quality` (return on equity)

| Tier | Citation | Find it |
|---|---|---|
| 1 | Novy-Marx, R. (2013). "The Other Side of Value: The Gross Profitability Premium." *Journal of Financial Economics*, 108(1), 1-28. | author website |
| 1 | Asness, C. S., Frazzini, A., & Pedersen, L. H. (2019). "Quality Minus Junk." *Review of Accounting Studies*, 24(1), 34-112. | AQR Library / SSRN |
| 2 | Piotroski, J. D. (2000). "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers." *Journal of Accounting Research*, 38(Suppl.), 1-41. The F-Score. | JSTOR |

### Low volatility, `vol` (inverse trailing realised vol)

Scored in the ablation, not in the composite.

| Tier | Citation | Find it |
|---|---|---|
| 1 | Frazzini, A., & Pedersen, L. H. (2014). "Betting Against Beta." *Journal of Financial Economics*, 111(1), 1-25. | AQR Library / SSRN |
| 1 | Baker, M., Bradley, B., & Wurgler, J. (2011). "Benchmarks as Limits to Arbitrage: Understanding the Low-Volatility Anomaly." *Financial Analysts Journal*, 67(1), 40-54. | journal / SSRN |

### Congressional flow, `congress`

| Tier | Citation | Find it |
|---|---|---|
| 1 | Ziobrowski, A. J., et al. (2004, 2011). Senate and House trading abnormal returns. The 2011 House paper is the source of the prediction that pooling the two chambers dilutes the signal. | journal |
| 2 | Eggers, A. C., & Hainmueller, J. (2013). Political capital and legislator portfolios. | journal |

### Institutional flow, `fund` (13F)

| Tier | Citation | Find it |
|---|---|---|
| 1 | Agarwal, V., et al. (2013). Acquisitions +7.06% DGTW at 12 months (t = 3.95) against disposals +2.94% (t = 1.42). This asymmetry is why sells are damped to 0.5. | SSRN |
| 2 | Cohen, R., Polk, C., & Silli, B. Best Ideas. Cited by the factor but not measured by it, see the concentration caveat in the README. | SSRN |

### Insider buys, `insider` (Form 4)

| Tier | Citation | Find it |
|---|---|---|
| 1 | Lakonishok, J., & Lee, I. (2001). The effect is entirely small-cap; the large-cap NPR coefficient is -0.30 (t = -0.65). This predicts the dead reading in an S&P 500 universe. | journal |
| 2 | Cohen, L., Malloy, C., & Pomorski, J. (2012). Routine versus opportunistic insiders, roughly a 6-month drift. | journal |

### Short volume, `short` (FINRA Reg SHO)

| Tier | Citation | Find it |
|---|---|---|
| 1 | Boehmer, E., Jones, C. M., & Zhang, X. (2008). Short flow drives out short interest in 13 of 15 reversed sorts. Construction (5-day formation, 20-day hold, negative sign) is taken from the paper and is not swept. | journal / SSRN |

### Activism, `activism` (SC 13D initial stakes)

Ungrounded. The code cites Brav & Jiang (2008) in a comment, but no source note
exists in the vault, so the factor is scored without a paper behind it. It also
reads -1.58 on 15% coverage, the weakest evidence base in the model.

## Methodology papers

| Citation | What it governs |
|---|---|
| Harvey, C. R., Liu, Y., & Zhu, H. (2016). ". . . and the Cross-Section of Expected Returns." | The promotion bar. N = 316 for zoo draws. Both Harvey papers recommend false-discovery-rate control (BHY), not Bonferroni. |
| Benjamini, Y., & Yekutieli, D. (2001). | The dependence correction. With it, BHY is stricter than Bonferroni for a lone discovery. |
| Newey, W. K., & West, K. D. (1987). | HAC standard errors. The paper does not specify lag selection; the `4(T/100)^(2/9)` plug-in rule is from later literature and gives lag 4 at T = 115. |
| Bernard, V. L., & Thomas, J. K. | SUE-return correlation is 1.00 at decile level but 0.09 at firm level. Read before building PEAD: the monthly cross-sectional IC is structurally the firm-level statistic. |
| Grinold, R. C., & Kahn, R. N. (1999). *Active Portfolio Management*. | Combining signals; the sensibleness guard that says a fix which lowers a t-statistic is the credible kind. |
| Qian, E. E., Hua, R. H., & Sorensen, E. H. (2007). *Quantitative Equity Portfolio Management*. | Cross-sectional ranking and factor-composite construction, which is the method used here. |
| Ilmanen, A. (2011). *Expected Returns*. | Why equal weighting beats fitted weights. The three blocks are equal-weighted for this reason. |
| Berkin, A. L., & Swedroe, L. E. (2016). *Your Complete Guide to Factor-Based Investing*. | Their five durability tests for a factor: persistence, pervasiveness, robustness, investability, intuitiveness.  |

## Caveat carried into the product

These premia are long-horizon and statistical. They work on average, across many
names, over years. They are not per-stock predictions and can underperform for
long stretches. The screen surfaces candidates to investigate, never buy signals.
