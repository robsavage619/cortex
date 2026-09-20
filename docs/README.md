# Documentation index

Start at the [repository README](../README.md) for what CORTEX is and why it is
built the way it is. These are the deeper docs.

## Start here if you have ten minutes

1. [factor-journal.md](factor-journal.md) has the most engineering content per
   page: seven changes, each with the measured before and after, including four
   defects that were silently inflating results.
2. [evaluation.md](evaluation.md) explains how the significance bar is derived
   rather than chosen, and carries the current numbers.

## Reference

| Doc | Covers |
|---|---|
| [architecture.md](architecture.md) | Process shape, module layout, why one process and an embedded database |
| [data-model.md](data-model.md) | 23 DuckDB tables, the migration mechanism, three keys that were wrong |
| [ingestion.md](ingestion.md) | The fourteen sources, EDGAR filename and rate-limit behaviour, FINRA's 403, yfinance failure modes |
| [evaluation.md](evaluation.md) | Significance gate, what the harness reports, current results, test coverage |
| [factor-journal.md](factor-journal.md) | Change-by-change record with measured deltas |
| [research-sources.md](research-sources.md) | The paper behind each factor, and the one factor with no paper |
| [design-system.md](design-system.md) | Live visual tokens, layout, motion rules |
| [operations.md](operations.md) | Local dev, build topology, credentials, the LLM spend gate |
| [../deploy/README.md](../deploy/README.md) | Railway services, cron topology, schedules |
| [../CHANGELOG.md](../CHANGELOG.md) | Release history |

## Archive

Kept because the before-and-after evidence is useful. Neither file describes the
current system.

| Doc | Why it is here |
|---|---|
| [archive/remediation-audit-2026-07-06.md](archive/remediation-audit-2026-07-06.md) | Audit trail for the 2026-07-06 data-integrity remediation, schema v15 to v17 |
| [archive/design-system-glass.md](archive/design-system-glass.md) | The original glass-premium visual language, replaced before 2026-08 |

## Screenshots

`screenshots/` holds the images used by the repository README: `dashboard.png`,
`congress.png`, `swing.png`, `stock-modal.png`, `calibration.png`. `banner.png` is
the header image.
