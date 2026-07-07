"""The one true CORTEX composite definition.

Both the backtest (``backtest._build_signals``) and live discovery
(``discovery.run_discovery``) compute THIS composite — a live ranking that
diverges from the tested signal is a bug, not a feature.

Definition (three equal blocks, each the nanmean of its factors; the
composite is the nanmean of the available block means — no z-imputation):

- price block:       momentum 12-1, trend (continuous distance to 200d SMA)
- fundamental block: earnings yield, ROE (point-in-time EDGAR filings,
                     gated on filing_date)
- flow block:        congressional net-buy, 13F institutional net-buy
                     (exponentially decayed, disclosure-gated)

All factor inputs are cross-sectional z-scores winsorized at ±Z_CLIP.

Pre-registration history (decisions are journaled, never silently changed):
- 2026-05-23 — low-vol removed from the price block (underperforms in
  sustained bull regimes; Ang et al. 2006, Baker et al. 2011).
- 2026-05-28 — insider Form 4 excluded from the flow block ("drop if
  t < 1.0 after first sync"; measured NW t = -0.43, contrarian to momentum).
- Sharpe was never part of any tested composite.
- Activism is scored ablation-only (event timescale is days, monthly IC ≈ 0).

Known, accepted live-vs-backtest divergence: discovery applies a hard
200d-SMA trend gate before scoring (conservatism filter), so its z
cross-section is the ~300-500 above-trend names rather than the full
eligible universe the backtest scores. Documented, monitored, accepted.
"""

from __future__ import annotations

import warnings

import numpy as np

# Half-lives / windows (days) chosen a priori from the literature — NOT fitted.
CONGRESS_HALFLIFE = 180.0
CONGRESS_WINDOW = 365
FUND_HALFLIFE = 270.0
FUND_WINDOW = 540
# Insider (Form 4) decays fast — Cohen et al. (2012) show ~6-month drift.
INSIDER_HALFLIFE = 90.0
INSIDER_WINDOW = 180
# Activism (SC 13D) drifts slowly — Brav & Jiang (2008), 12-18 months.
ACTIVISM_HALFLIFE = 365.0
ACTIVISM_WINDOW = 730

Z_CLIP = 3.0


def build_blocks(
    zmom: np.ndarray,
    ztrend: np.ndarray,
    zval: np.ndarray,
    zqual: np.ndarray,
    zcong: np.ndarray,
    zfund: np.ndarray,
) -> dict[str, np.ndarray]:
    """Composite variants from the three equal blocks.

    Returns ``cortex`` (price + fundamental + flow), ``price`` (null model)
    and ``price_fund`` (no flow). Inputs are winsorized z-score arrays.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=RuntimeWarning)
        price = np.nanmean(np.vstack([zmom, ztrend]), axis=0)
        fund = np.nanmean(np.vstack([zval, zqual]), axis=0)
        flow = np.nanmean(np.vstack([zcong, zfund]), axis=0)
        cortex = np.nanmean(np.vstack([price, fund, flow]), axis=0)
        price_fund = np.nanmean(np.vstack([price, fund]), axis=0)
    return {
        "cortex": cortex,
        "price": price,
        "price_fund": price_fund,
    }
