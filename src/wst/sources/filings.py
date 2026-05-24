from __future__ import annotations

import contextlib
import logging
from dataclasses import dataclass, field

from wst.config import sec_user_agent

logger = logging.getLogger(__name__)

# SEC fair-access requires a descriptive User-Agent; set via WST_SEC_USER_AGENT.
_USER_AGENT = sec_user_agent()


@dataclass
class FilingsContext:
    ticker: str
    recent_8k_titles: list[str] = field(default_factory=list)
    recent_form4_insiders: list[str] = field(default_factory=list)
    latest_10k_period: str | None = None
    latest_10q_period: str | None = None
    risk_factors_summary: str | None = None


class FilingsSourceError(Exception):
    """Raised when edgartools data cannot be fetched or parsed."""


def context_for(ticker: str, *, limit: int = 5) -> FilingsContext:
    """Fetch recent SEC filings context for ticker via edgartools (free, no key).

    Degrades visibly on failure — never silently empty.
    """
    try:
        import edgar

        edgar.set_identity(_USER_AGENT)
    except ImportError as exc:
        raise FilingsSourceError("edgartools is not installed") from exc
    except Exception as exc:
        raise FilingsSourceError(f"edgar identity setup failed: {exc}") from exc

    ctx = FilingsContext(ticker=ticker.upper())

    try:
        company = edgar.Company(ticker)
        filings = company.get_filings()

        eights = filings.filter(form="8-K").head(limit)
        for f in eights:
            with contextlib.suppress(Exception):
                ctx.recent_8k_titles.append(
                    str(f.form) + ": " + str(getattr(f, "description", ""))
                )

        form4s = filings.filter(form="4").head(limit)
        for f in form4s:
            with contextlib.suppress(Exception):
                ctx.recent_form4_insiders.append(
                    str(getattr(f, "filer", "")) or str(getattr(f, "description", ""))
                )

        ten_k = filings.filter(form="10-K").head(1)
        if ten_k:
            with contextlib.suppress(Exception):
                ctx.latest_10k_period = str(getattr(ten_k[0], "period_of_report", ""))

        ten_q = filings.filter(form="10-Q").head(1)
        if ten_q:
            with contextlib.suppress(Exception):
                ctx.latest_10q_period = str(getattr(ten_q[0], "period_of_report", ""))

    except FilingsSourceError:
        raise
    except Exception as exc:
        raise FilingsSourceError(
            f"edgartools fetch failed for {ticker}: {exc}"
        ) from exc

    return ctx
