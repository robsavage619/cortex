# CORTEX Portal — Design System (Glass Premium)

The visual contract for the `web/` React portal. Any agent generating UI for this
project reads this file first. Tokens are **locked** — do not invent new colors,
radii, or fonts. Dark-only; there is no light mode.

## Visual Theme & Atmosphere
Glass premium, dark-only. A calm, high-trust instrument panel — not a trading-floor
ticker. Deep near-black canvas, frosted translucent cards floating over it, a single
cyan→violet accent reserved for primary actions and highlights. Generous whitespace,
tabular figures, restrained motion. The feeling is "private wealth dashboard," not
"retail buy-feed": confident, quiet, honest. Every data point reads as evidence for a
decision, never a recommendation.

## Color Palette & Roles
Dark-only. The "Light" column is intentionally identical — there is no light theme;
the column exists only to satisfy tooling that expects both.

| Role | Light | Dark | Usage |
|------|-------|------|-------|
| Background | #0A0E1A | #0A0E1A | Page base (near-black navy) |
| Surface (glass) | rgba(255,255,255,0.04) | rgba(255,255,255,0.04) | Cards, panels — over `backdrop-blur` |
| Surface raised | rgba(255,255,255,0.06) | rgba(255,255,255,0.06) | Hover / active card, popovers |
| Border (hairline) | rgba(255,255,255,0.08) | rgba(255,255,255,0.08) | Card edges, dividers, inputs |
| Accent start | #22D3EE | #22D3EE | Gradient origin (cyan) |
| Accent end | #8B5CF6 | #8B5CF6 | Gradient terminus (violet) |
| Accent solid | #6366F1 | #6366F1 | Flat fallback when a gradient can't be used (focus ring, single-color icon) |
| Up / positive | #34D399 | #34D399 | Gains, confirmed, correct — muted green |
| Down / negative | #F87171 | #F87171 | Losses, invalidated, wrong — muted red |
| Warning | #FBBF24 | #FBBF24 | Review-due, unclear outcome |
| Text primary | #E5E9F0 | #E5E9F0 | Headings, figures, body |
| Text muted | #8B93A7 | #8B93A7 | Labels, captions, metadata |
| Text faint | #5A6177 | #5A6177 | Placeholders, disabled |

Semantic rule: green/red are **muted**, never neon. They signal direction, not
excitement — this is an anti-action-bias product.

## Typography Rules
Font: **Inter** (UI). No secondary display font. Monospace only inside code/JSON blocks
(`ui-monospace, "JetBrains Mono", monospace`).

- Headings: 600 weight, -0.01em tracking
- Body: 400 weight, 1.5 line-height
- Labels / captions: 500 weight, 0.875rem, text-muted
- **All numeric figures use `font-variant-numeric: tabular-nums`** — prices, percentages,
  Brier scores, conviction, dates. Non-negotiable; figures must align in columns.

Scale (px): 12 / 14 / 16 / 20 / 24 / 32 / 48
Max 3 distinct sizes per screen.

## Component Stylings
**Button primary**: cyan→violet gradient (`linear-gradient(135deg, #22D3EE, #8B5CF6)`),
white text, 16px radius, 10/20px padding, weight 600. Hover: soft outer glow
(`0 0 24px rgba(34,211,238,0.25)`), no color shift. Active: scale 0.98.

**Button secondary (glass)**: surface bg, hairline border, text-primary, 16px radius,
same sizing. Hover: surface-raised + border brightens to rgba(255,255,255,0.16).

**Button ghost**: transparent, text-muted, no border. Hover: text-primary.

**Input / Select / Textarea**: surface bg, hairline border, 12px radius, 10/14px padding,
text-primary, faint placeholder. Focus: 2px ring `accent-solid` at 50% opacity, no glow.

**Card (glass)**: surface bg, `backdrop-blur: 16px`, hairline border, 16px radius, 24px
padding. Hover (when interactive): surface-raised + soft outer glow
`0 8px 32px rgba(0,0,0,0.4), 0 0 0 1px rgba(255,255,255,0.06)`.

**Stat / KPI tile** (Tremor): glass card, label in text-muted 14px above a 32px
tabular-nums figure. Delta badge: up=green/down=red pill at 12px.

**Conviction meter**: 1–5 segmented bar; filled segments use the accent gradient,
empty use border color.

**Status badge**: pill, 12px, 500 weight. `open`=accent-solid tint, `confirmed`=green
tint, `invalidated`=red tint, `closed`=text-muted tint. Tints are the color at ~15%
opacity over surface.

**Logo mark**: real logos via **logo.dev** free tier
(`https://img.logo.dev/ticker/{TICKER}?token=${VITE_LOGODEV_TOKEN}`). **Default fallback**
is a gradient monogram — a 16px-radius square with the cyan→violet gradient and the
ticker's first 1–2 letters in white 600. The portal must look complete with monograms
alone; logo.dev is an enhancement, never a dependency.

**Chart (price)**: TradingView lightweight-charts, transparent background, grid lines at
border color, up/down candles in muted green/red, crosshair in accent-solid.

**Chart (calibration)**: Recharts reliability diagram — diagonal "perfect" reference line
in text-faint dashed; actual curve in accent gradient stroke.

## Layout Principles
- 8px base unit — all spacing is a multiple of 8 (4px allowed only for icon insets).
- Max content width: 1280px, centered.
- Sidebar: 240px fixed (nav between the 5 views); collapses to a top bar under 1024px.
- Page padding: 16px mobile, 32px tablet, 48px desktop.
- Card grid: 12-col, 24px gutter. Dashboard scorecard spans full width; thesis tiles are
  4-col (3-up desktop), stacking to 1-up on mobile.

## Depth & Elevation
Depth comes from blur + translucency + soft glow, not hard drop shadows.
- Level 0 (page): flat, no shadow.
- Level 1 (glass card): `backdrop-blur 16px` + hairline border, no shadow at rest.
- Level 2 (hover / popover): soft outer glow `0 8px 32px rgba(0,0,0,0.4)`.
- Level 3 (modal / dialog): backdrop scrim `rgba(10,14,26,0.6)` + blur, card glow
  `0 16px 48px rgba(0,0,0,0.5)`.

## Do's and Don'ts
✓ Use semantic color roles via Tailwind tokens — never hardcode hex in components.
✓ `tabular-nums` on every figure; right-align numeric table columns.
✓ Reserve the accent gradient for primary actions, active nav, and key highlights — scarcity keeps it premium.
✓ Subtle motion only: 150–250ms ease-out on hover; a brief fade/slide when data updates (Framer Motion `layout` + opacity).
✓ Glass cards always sit over the dark canvas so `backdrop-blur` reads.
✗ No neon green/red — keep gains/losses muted.
✗ No gradient on body text, borders, or large fills — accent gradient is for actions/highlights only.
✗ No hard drop shadows or skeuomorphic bevels — depth is blur + glow.
✗ No more than 3 font sizes per screen.
✗ No buy/sell language, no "recommended," no signal framing. This is a decision tool.
✗ Never block the UI on logo.dev — monogram fallback must render instantly.

## Responsive Behaviour
- Mobile (<640px): single column, full-width glass cards, 16px padding, sidebar → top hamburger, charts shrink to 240px tall.
- Tablet (640–1024px): 2-column card grid, sidebar collapsed to icons or hamburger, 32px padding.
- Desktop (>1024px): full layout, 240px sidebar visible, 3-up thesis grid, 48px padding.

## Agent Prompt Guide
When generating UI for this project:
- Read tokens from the Tailwind theme (extend `colors`, `borderRadius`, `backdropBlur`) — never hardcode hex or px in component JSX.
- Default radius is `16px` (`rounded-2xl`); inputs use `12px` (`rounded-xl`).
- Every glass surface: `bg-white/[0.04] backdrop-blur-xl border border-white/[0.08] rounded-2xl`.
- Primary action: gradient `from-[#22D3EE] to-[#8B5CF6]`; everything else is glass or ghost.
- All figures: wrap in a class applying `tabular-nums`; format percentages and prices consistently.
- Every interactive element has a visible focus state (2px accent-solid ring).
- Use shadcn/ui primitives, Tremor for KPI/stat blocks, lightweight-charts for price, Recharts for the calibration diagram, lucide-react for icons, Framer Motion for transitions.
- Data comes from the FastAPI service via TanStack Query; assume the `/theses`, `/review-queue`, `/calibration`, `/context/{ticker}` shapes. Every response carries a `banner: "Decision tool — not financial advice."` — surface it persistently in the chrome.
- Dark-only. Do not add a light-mode toggle.
