# CORTEX — Discovery Algorithm Reading List

Source material for the Phase 0/Phase 1 discovery engine. Every factor in the screen
traces to a specific peer-reviewed paper below — nothing in the model is invented.
Ingesting these into the vault is what lets the algorithm's factor weights eventually be
**shaped by the research** instead of hardcoded.

- **Tier 1** — directly powers one of the six factors in the Phase 0 screen. Ingest first.
- **Tier 2** — portfolio construction, factor combination, and practitioner context. Ingest for Phase 1+.

Ingest pipeline: use the `ingest-paper` skill for papers, `ingest-textbook` for books.
Where to find them: most papers have free working-paper versions on **SSRN** or **NBER**;
AQR-authored papers (Asness/Frazzini/Pedersen) are free in the **AQR Research Library**;
the rest are in the journal of record (search the exact title — they're all heavily cited).

---

## Papers

### Momentum factor — `momentum (12–1)`
| Tier | Citation | Find it |
|---|---|---|
| 1 | **Jegadeesh, N., & Titman, S. (1993).** "Returns to Buying Winners and Selling Losers: Implications for Stock Market Efficiency." *Journal of Finance*, 48(1), 65–91. | JSTOR / journal |
| 1 | **Carhart, M. M. (1997).** "On Persistence in Mutual Fund Performance." *Journal of Finance*, 52(1), 57–82. — adds the momentum (UMD) factor | JSTOR / journal |
| 2 | **Moskowitz, T. J., Ooi, Y. H., & Pedersen, L. H. (2012).** "Time Series Momentum." *Journal of Financial Economics*, 104(2), 228–250. | AQR Library / SSRN |

### Trend regime — `price vs 200-day SMA`
| Tier | Citation | Find it |
|---|---|---|
| 1 | **Faber, M. T. (2007).** "A Quantitative Approach to Tactical Asset Allocation." *Journal of Wealth Management*, Spring 2007. | SSRN (widely downloaded) |

### Value factor — `P/E, P/B, EV/EBITDA composite`
| Tier | Citation | Find it |
|---|---|---|
| 1 | **Fama, E. F., & French, K. R. (1992).** "The Cross-Section of Expected Stock Returns." *Journal of Finance*, 47(2), 427–465. | JSTOR / journal |
| 1 | **Fama, E. F., & French, K. R. (1993).** "Common Risk Factors in the Returns on Stocks and Bonds." *Journal of Financial Economics*, 33(1), 3–56. — the three-factor model | journal / NBER |
| 2 | **Asness, C. S., Moskowitz, T. J., & Pedersen, L. H. (2013).** "Value and Momentum Everywhere." *Journal of Finance*, 68(3), 929–985. | AQR Library / SSRN |

### Quality factor — `gross profitability, ROE, low debt/equity`
| Tier | Citation | Find it |
|---|---|---|
| 1 | **Novy-Marx, R. (2013).** "The Other Side of Value: The Gross Profitability Premium." *Journal of Financial Economics*, 108(1), 1–28. | author website / journal |
| 1 | **Asness, C. S., Frazzini, A., & Pedersen, L. H. (2019).** "Quality Minus Junk." *Review of Accounting Studies*, 24(1), 34–112. | AQR Library / SSRN |
| 2 | **Piotroski, J. D. (2000).** "Value Investing: The Use of Historical Financial Statement Information to Separate Winners from Losers." *Journal of Accounting Research*, 38(Suppl.), 1–41. — the F-Score | JSTOR / journal |

### Low-volatility factor — `inverse trailing realized vol`
| Tier | Citation | Find it |
|---|---|---|
| 1 | **Frazzini, A., & Pedersen, L. H. (2014).** "Betting Against Beta." *Journal of Financial Economics*, 111(1), 1–25. | AQR Library / SSRN |
| 1 | **Baker, M., Bradley, B., & Wurgler, J. (2011).** "Benchmarks as Limits to Arbitrage: Understanding the Low-Volatility Anomaly." *Financial Analysts Journal*, 67(1), 40–54. | journal / SSRN |

### Risk-adjusted return — `Sharpe-like ranking`
| Tier | Citation | Find it |
|---|---|---|
| 1 | **Sharpe, W. F. (1966).** "Mutual Fund Performance." *Journal of Business*, 39(1), 119–138. — origin of the Sharpe ratio | JSTOR / journal |

---

## Books

| Tier | Citation | Why it matters |
|---|---|---|
| 1 | **Ilmanen, A. (2011).** *Expected Returns: An Investor's Guide to Harvesting Market Rewards.* Wiley. | The single best synthesis of factor premia and why equal-weighting beats fitted weights |
| 1 | **Berkin, A. L., & Swedroe, L. E. (2016).** *Your Complete Guide to Factor-Based Investing.* BAM Alliance Press. | Plain-English vetting of which factors survive scrutiny (persistence, pervasiveness, robustness) |
| 2 | **Gray, W. R., & Vogel, J. R. (2016).** *Quantitative Momentum.* Wiley. | Implementation detail for the momentum factor |
| 2 | **Gray, W. R., & Carlisle, T. E. (2012).** *Quantitative Value.* Wiley. | Implementation detail for the value + quality factors |
| 2 | **Grinold, R. C., & Kahn, R. N. (1999).** *Active Portfolio Management* (2nd ed.). McGraw-Hill. | The math of combining signals into a single score (information ratio, the Fundamental Law) |
| 2 | **Qian, E. E., Hua, R. H., & Sorensen, E. H. (2007).** *Quantitative Equity Portfolio Management.* Chapman & Hall/CRC. | Cross-sectional ranking and factor-composite construction — exactly our method |

---

## Suggested ingest order

1. **Ilmanen — *Expected Returns*** (book) — gives you the mental model for everything else.
2. The **six Tier-1 factor papers** (one per factor) — these are what the screen literally implements.
3. **Berkin & Swedroe** — sanity-check on factor durability.
4. Everything Tier 2 as time allows.

---

## How each maps to the algorithm

```
momentum (12–1)        ← Jegadeesh-Titman 1993, Carhart 1997
trend regime           ← Faber 2007, Moskowitz-Ooi-Pedersen 2012
value composite        ← Fama-French 1992/1993, Asness et al. 2013
quality composite      ← Novy-Marx 2013, Asness-Frazzini-Pedersen 2019, Piotroski 2000
low volatility         ← Frazzini-Pedersen 2014, Baker-Bradley-Wurgler 2011
risk-adjusted return   ← Sharpe 1966
combination method     ← Qian et al. 2007 (rank composite), Grinold-Kahn 1999
weighting philosophy   ← Ilmanen 2011, Berkin-Swedroe 2016 (equal-weight > overfit)
```

> **Honest caveat carried into the product:** these factor premia are long-horizon and
> statistical — they work *on average across many names over years*, not as per-stock
> predictions, and can underperform for long stretches. The screen surfaces *candidates to
> investigate*, never buy signals.
