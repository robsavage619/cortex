# web/

The CORTEX portal. React 19, Vite 8, TypeScript, Tailwind 4.

FastAPI serves the compiled output from `web/dist/` on the same origin as the
API, so in production there is one process and one port. `web/dist/` is not
committed; Railway rebuilds it from source on every deploy through the root
`nixpacks.toml`.

## Develop

```bash
npm install
npm run dev      # :5173, proxies /api to the FastAPI service on :8000
```

Start the backend separately with `uv run cortex serve` from the repository root.
The API allows CORS only from `http://localhost:5173` and `http://127.0.0.1:5173`.

## Build

```bash
npm run build    # type-check, then emit to dist/
npm run lint
```

There is no test script and no test files.

## Layout

```
src/
  App.tsx            router, seven routes behind one Layout
  index.css          the whole theme: Tailwind 4 @theme tokens and utilities
  components/
    Layout.tsx       top bar, nav, live ticker strip
    ThesisCard.tsx
    charts/          lightweight-charts and Recharts wrappers
    ui/              primitives, there is no component library
  views/             Dashboard, Congress, Whales, SwingScreen, Calibration,
                     ReviewQueue, NewThesis, ThesisDetail, StockModal, MemberModal
  lib/               API client (TanStack Query), plain-mode toggle, helpers
```

## Conventions

Colours, type, radii and utilities are defined once in `src/index.css` under
Tailwind 4's `@theme` block. Read them from the theme; do not hardcode hex or px
in a component. The contract is written up in
[../docs/design-system.md](../docs/design-system.md).
