// Single source of truth for translating CORTEX's quant surface into plain
// English. Used by Plain-English mode so the app reads clearly for non-quants.

export interface FactorTerm {
  /** Technical label shown when plain mode is off (e.g. "MOM"). */
  tech: string
  /** Plain label shown when plain mode is on (e.g. "Price trend"). */
  plain: string
  /** Hover explanation — always available regardless of mode. */
  tip: string
}

// Keyed by the technical factor code used throughout the dashboard.
export const FACTORS: Record<string, FactorTerm> = {
  MOM: {
    tech: 'MOM',
    plain: 'Price trend',
    tip: 'Momentum — 12-month price trend vs. the S&P 500. High = a sustained outperformer.',
  },
  LVOL: {
    tech: 'LVOL',
    plain: 'Steadiness',
    tip: 'Low volatility — smaller daily swings than peers. High = a steadier ride, historically better risk-adjusted returns.',
  },
  SHR: {
    tech: 'SHR',
    plain: 'Efficiency',
    tip: 'Risk-adjusted return (Sharpe) — return per unit of volatility over 12 months. High = efficient gains for the risk taken.',
  },
  VAL: {
    tech: 'VAL',
    plain: 'Value',
    tip: 'Value (earnings yield) — earnings relative to price. High = cheaper on fundamentals.',
  },
  QUAL: {
    tech: 'QUAL',
    plain: 'Quality',
    tip: 'Quality / profitability — return on equity + gross profits. High = a durable business with pricing power.',
  },
}

/** Compact plain phrase for a single factor's standardised score (z). */
export function zPhrase(z: number | null): string {
  if (z === null) return 'no data'
  if (z >= 1.5) return 'much stronger'
  if (z >= 0.5) return 'stronger'
  if (z >= -0.5) return 'average'
  if (z >= -1.5) return 'weaker'
  return 'much weaker'
}

// Standard-normal CDF (Abramowitz-Stegun 7.1.26) — turns a z-score into a
// percentile so "+2.88z" can be shown as the plain "top 0.2%".
function normalCdf(z: number): number {
  const t = 1 / (1 + 0.2316419 * Math.abs(z))
  const d = 0.3989423 * Math.exp((-z * z) / 2)
  let p =
    d *
    t *
    (0.3193815 +
      t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))))
  if (z > 0) p = 1 - p
  return p
}

/** Plain percentile label for a composite/standardised score, e.g. "top 2%". */
export function zPercentileLabel(z: number | null): string {
  if (z === null) return 'no data'
  const pct = normalCdf(z)
  if (z >= 0) {
    const top = Math.max(0.1, Math.round((1 - pct) * 1000) / 10)
    return `top ${top < 1 ? top.toFixed(1) : Math.round(top)}%`
  }
  const bottom = Math.max(0.1, Math.round(pct * 1000) / 10)
  return `bottom ${bottom < 1 ? bottom.toFixed(1) : Math.round(bottom)}%`
}

// Section / label translations for the discovery views.
export const SECTION_LABELS: Record<string, string> = {
  DISCOVERED: 'TOP PICKS',
  'ALGO BUYS': 'STRONG BUYS',
}

export function plainSection(label: string): string {
  return SECTION_LABELS[label] ?? label
}
