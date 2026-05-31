export function cn(...parts: Array<string | false | null | undefined>): string {
  return parts.filter(Boolean).join(' ')
}

export function fmtPercent(v: number | null | undefined, digits = 1): string {
  if (v == null || Number.isNaN(v)) return '—'
  return `${(v * 100).toFixed(digits)}%`
}

export function fmtSignedPercent(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v.toFixed(2)}%`
}

export function fmtPrice(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return v.toLocaleString('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: 2,
  })
}

export function fmtCompact(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return v.toLocaleString('en-US', { notation: 'compact', maximumFractionDigits: 1 })
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}

export function daysUntil(iso: string): number {
  const target = new Date(iso).getTime()
  const now = Date.now()
  return Math.ceil((target - now) / 86_400_000)
}

/** Returns true for any purchase/buy transaction type (handles Senate "Purchase" and House "P"/"P (partial)"). */
export function isBuy(tx: string | null | undefined): boolean {
  const t = (tx ?? '').toLowerCase().trim()
  return t === 'p' || t.startsWith('p ') || t.startsWith('p(') || t.includes('purchase')
}

/** Normalises a transaction_type string to "BUY" or "SELL" for display. */
export function txLabel(tx: string | null | undefined): string {
  return isBuy(tx) ? 'BUY' : 'SELL'
}

/** Strips honorary prefixes ("Hon.", "Sen.", "Rep.", etc.) for display. */
export function stripTitle(name: string | null | undefined): string {
  return (name ?? '').replace(/^(Hon|Sen|Rep)\.?\s+/i, '').trim()
}

/** Shared thesis signal score used on Dashboard cards and StockModal ThesisTab. */
export function computeFactors(
  thesis: { conviction: number; why_now: string | null; base_rate: string | null; pre_mortem: string | null },
  market: { price?: number | null; week_52_high?: number | null; week_52_low?: number | null; day_change_percent?: number | null } | undefined,
) {
  const conviction = (thesis.conviction / 5) * 40

  let valueZone = 0
  if (market?.price != null && market.week_52_high != null && market.week_52_low != null) {
    const range = market.week_52_high - market.week_52_low
    if (range > 0) {
      const pos = (market.price - market.week_52_low) / range
      valueZone = pos < 0.33 ? 25 : pos < 0.5 ? 15 : pos < 0.75 ? 5 : 0
    }
  }

  let momentum = 0
  if (market?.day_change_percent != null) {
    const d = market.day_change_percent
    momentum = d > 2 ? 20 : d > 0 ? 10 : d > -2 ? 5 : 0
  }

  const research =
    (thesis.why_now ? 5 : 0) + (thesis.base_rate ? 5 : 0) + (thesis.pre_mortem ? 5 : 0)

  return {
    conviction,
    valueZone,
    momentum,
    research,
    total: Math.min(100, Math.round(conviction + valueZone + momentum + research)),
  }
}
