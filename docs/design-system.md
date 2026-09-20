# Design system

The visual contract for the `web/` React portal. Tokens are defined once in
`web/src/index.css` under Tailwind 4's `@theme` block. Read them from the theme;
do not hardcode hex or px in component JSX.

Last verified 2026-09-19 against `web/src/index.css` and
`web/src/components/Layout.tsx`.

An earlier "glass premium" system (Inter, 16px radii, translucent cards over
`backdrop-blur`, a 240px sidebar, shadcn/ui and Tremor) was replaced before
2026-08. It is kept at [archive/design-system-glass.md](archive/design-system-glass.md)
for history. None of its tokens are live.

## Intent

A terminal instrument panel. Dark only, no light mode, no toggle. Dense, quiet,
monospace numerics, hairline borders, almost no radius. The product is an
anti-action-bias decision tool, so gains and losses signal direction rather than
excitement, and nothing in the chrome rewards trading.

## Tokens

### Canvas and borders

| Token | Value | Use |
|---|---|---|
| `--color-bg` | `#080b0f` | Page base |
| `--color-bg-panel` | `#0d1117` | Panels, header, surfaces |
| `--color-bg-row` | `#0d1117` | Table row |
| `--color-bg-row-alt` | `#0b0e12` | Zebra stripe |
| `--color-bg-hover` | `#131a22` | Row hover |
| `--color-bg-selected` | `#1a2230` | Selected row |
| `--color-border` | `#1e2530` | Default hairline |
| `--color-border-dim` | `#161d26` | Subdivision inside a panel |
| `--color-border-bright` | `#2a3545` | Emphasis, scrollbar hover |
| `--color-surface` | `#0d1117` | Card background |
| `--color-surface-raised` | `#131a22` | Raised card |

### Semantic colour

| Token | Value | Use |
|---|---|---|
| `--color-up` | `#4ade80` | Gains, confirmed, correct |
| `--color-down` | `#f87171` | Losses, invalidated, wrong |
| `--color-warn` | `#fbbf24` | Review due, unclear outcome |
| `--color-cyan` | `#22d3ee` | Brand and interactive only |
| `--color-open` | `#38bdf8` | Open-status data colour |
| `--color-accent` | `#22d3ee` | Alias of cyan |

Cyan is reserved for brand and interaction. It is not a data colour. `--color-open`
exists so that "open" status can be blue in a chart without competing with the
interactive cyan.

### Text

| Token | Value | Contrast |
|---|---|---|
| `--color-ink` | `#e2e8f0` | Body and figures |
| `--color-muted` | `#6b7280` | Labels, captions. Passes WCAG AA at 4.0:1 |
| `--color-faint` | `#4b5563` | Placeholders, disabled. Passes 3.0:1 |

### Type

- Sans: **Geist Variable**, self-hosted through `@fontsource-variable/geist`
- Mono: **Geist Mono Variable**, with `JetBrains Mono` and `ui-monospace` as
  fallbacks
- Root size 13px, line-height 1.5

Two utility classes carry most of the typographic weight:

- `.num` puts every figure in the mono face with `tabular-nums` and the `ss01`
  feature at `0.02em` tracking. Prices, tickers, dates and scores all use it, so
  digits align in columns.
- `.label` is the all-caps 10px 600-weight 0.12em-tracked muted label used for
  section headers and column headings.

### Shape

`--radius-sm: 2px`, `--radius-md: 3px`, `--radius-card: 3px`. Nothing is round.
Scrollbars are 6px with a square thumb.

## Layout

A fixed 44px top bar, not a sidebar. Brand mark, then seven nav tabs
(`DASHBOARD`, `REVIEW`, `SWING`, `CONGRESS`, `WHALES`, `CALIBRATE`, `NEW THESIS`),
then a live ticker strip, then a persistent `NOT FINANCIAL ADVICE` label. Per-ticker
detail opens as a modal rather than a route.

## Utilities

| Utility | Definition |
|---|---|
| `terminal-panel` | `bg-panel` plus a 1px `--color-border` |
| `accent-gradient` | `linear-gradient(135deg, cyan, open)` |
| `accent-text` | cyan |
| `conv-low` / `conv-mid` / `conv-high` | Conviction bar stops: open at 40% opacity, warn, up |

## Motion

`flash-up` and `flash-down` are 180ms ease-out colour animations from white into
the up or down colour, used when a price ticks. Everything else is a 150ms to
250ms ease-out transition or a framer-motion layout animation.

All animation and transition durations collapse to 0.01ms under
`prefers-reduced-motion: reduce`.

## Rules

- Read colours from theme tokens; never hardcode hex in a component.
- Every figure gets `.num`. Right-align numeric table columns.
- Cyan is for brand and interaction only. A chart series never uses it.
- Green and red are muted and signal direction, not excitement.
- No buy/sell language, no "recommended", no signal framing anywhere in copy.
- Every interactive element has a visible focus state.
- Dark only. Do not add a light-mode toggle.
- Every API response carries `banner: "Decision tool, not financial advice."`
  Surface it persistently in the chrome.

## Stack

React 19, Vite 8, TypeScript, Tailwind 4 (`@tailwindcss/vite`), TanStack Query for
server state, lightweight-charts for price, Recharts for the calibration diagram,
framer-motion for transitions, lucide-react for icons. There is no component
library; primitives live in `web/src/components/ui/`.
