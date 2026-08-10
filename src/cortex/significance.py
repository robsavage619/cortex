"""Multiple-testing thresholds for the pre-registration gate.

CORTEX used to hardcode ``t >= 3.0`` and describe it as Bonferroni-corrected.
Neither half was quite right. 3.0 is the *headline recommendation* of Harvey,
Liu & Zhu (2016) — their own Bonferroni benchmark for the 316-factor published
zoo is 3.78 — and both Harvey papers recommend Benjamini-Hochberg-Yekutieli
(false discovery rate) over Bonferroni, because factor tests are correlated and
family-wise control is punishing when they are.

Two bars, not one. The gap between them is a disagreement about what counts as
the family of tests, and the two answers apply to different CORTEX factors:

* **Zoo draws** — momentum, trend, low-vol, value, quality, and PEAD when it
  lands — are lifted straight from the published literature. The family is the
  literature, so HLZ's N applies and the bar is high.
* **Own-family signals** — congress, fund, insider, activism — are a small
  private set CORTEX assembled. The family is CORTEX's own test count, and the
  bar is correspondingly lower.

A single global constant cannot be correct for both, and picking per factor
*after* seeing a result is exactly what the gate exists to prevent. So the
assignment is fixed here, in code, ahead of the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist

# Two-sided significance level for every threshold below.
ALPHA = 0.05

# Harvey, Liu & Zhu (2016) count 316 factors in the published cross-sectional
# asset-pricing literature. Their reported cutoffs for that N: Bonferroni 3.78,
# Holm 3.64, BHY 3.35 at alpha_d=1% and 2.82 at 5%.
ZOO_N = 316

# Factors whose hypotheses were drawn from the published zoo, and therefore
# inherit its multiple-testing burden. Everything else is scored against
# CORTEX's own per-run test count.
ZOO_FACTORS = frozenset({"mom", "trend", "vol", "value", "quality", "pead"})

_NORM = NormalDist()


def two_sided_p(t: float) -> float:
    """Two-sided normal p-value for a t-statistic."""
    return 2.0 * (1.0 - _NORM.cdf(abs(t)))


def bonferroni_t(n_tests: int, alpha: float = ALPHA) -> float:
    """Two-sided t threshold controlling family-wise error over n_tests."""
    n = max(1, n_tests)
    return _NORM.inv_cdf(1.0 - alpha / (2.0 * n))


def yekutieli_c(n_tests: int) -> float:
    """Harmonic correction that makes BH valid under arbitrary dependence."""
    n = max(1, n_tests)
    return sum(1.0 / i for i in range(1, n + 1))


@dataclass(frozen=True)
class BHYResult:
    """Outcome of a BHY sweep over one family of tests."""

    passed: frozenset[str]
    critical_values: dict[str, float]
    implied_t: float | None
    """Smallest |t| that would have passed this family, or None if nothing can."""


def bhy(tstats: dict[str, float], alpha: float = ALPHA) -> BHYResult:
    """Benjamini-Hochberg-Yekutieli false-discovery-rate sweep.

    Ranks the family by p-value and finds the largest rank k whose p-value
    clears ``k * alpha / (n * c(n))``; everything at or below that rank passes.

    Args:
        tstats: Test name to t-statistic. Sign is ignored — a factor that is
            reliably *negative* is still a discovery.
        alpha: Target false discovery rate.

    Returns:
        The set that passed, each test's critical value, and the |t| a test
        would have needed to be the single best discovery in this family.
    """
    if not tstats:
        return BHYResult(frozenset(), {}, None)

    n = len(tstats)
    denom = n * yekutieli_c(n)
    ranked = sorted(tstats.items(), key=lambda kv: two_sided_p(kv[1]))

    crit = {name: (i + 1) * alpha / denom for i, (name, _) in enumerate(ranked)}
    cutoff_rank = 0
    for i, (name, t) in enumerate(ranked, start=1):
        if two_sided_p(t) <= crit[name]:
            cutoff_rank = i
    passed = frozenset(name for name, _ in ranked[:cutoff_rank])

    # The rank-1 critical value is the bar a lone discovery must clear.
    best_crit = alpha / denom
    implied = _NORM.inv_cdf(1.0 - best_crit / 2.0)
    return BHYResult(passed, crit, implied)


@dataclass(frozen=True)
class Gate:
    """The bars in force for one backtest run."""

    n_tests: int
    own_family_bhy_t: float
    own_family_bonferroni_t: float
    zoo_bhy_t: float
    zoo_bonferroni_t: float

    def threshold_for(self, factor: str) -> float:
        """The bar this factor has to clear, fixed by family before the run."""
        return self.zoo_bhy_t if factor in ZOO_FACTORS else self.own_family_bhy_t

    def verdict(self, factor: str, tstat: float) -> str:
        return "PASS" if abs(tstat) >= self.threshold_for(factor) else "FAIL"


def record_trial(
    db_path: Path,
    *,
    n_tests: int,
    factors: list[str],
    best_factor: str | None,
    best_tstat: float | None,
    mean_abs_rho: float | None,
) -> int:
    """Append this run to the trial log and return the cumulative trial count.

    Bailey & López de Prado's central practical claim is that a backtest whose
    author cannot say how many trials were attempted is worthless, and Harvey &
    Liu's Sharpe haircut literally takes that count as an input. It is the one
    number nobody records. This records it.

    Cumulative, not per-run: thirteen configurations inside one backtest is one
    research decision; forty backtests over a month is forty chances to have
    found something by luck, and only the second number belongs in a haircut.
    """
    from cortex.storage.db import connect
    from cortex.storage.schemas import apply_schema

    sha = None
    try:
        import subprocess

        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            cwd=Path(__file__).resolve().parent.parent.parent,
        ).stdout.strip()
    except Exception:  # noqa: BLE001 - provenance is nice to have, not required
        sha = None

    with connect(db_path) as conn:
        apply_schema(conn)
        row = conn.execute(
            "SELECT COALESCE(MAX(id), 0) FROM research_trials"
        ).fetchone()
        next_id = (row[0] if row else 0) + 1
        conn.execute(
            "INSERT INTO research_trials "
            "(id, n_tests, factors, best_factor, best_tstat, mean_abs_rho, git_sha) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                next_id,
                n_tests,
                ",".join(sorted(factors)),
                best_factor,
                best_tstat,
                mean_abs_rho,
                sha or None,
            ],
        )
        total = conn.execute(
            "SELECT COALESCE(SUM(n_tests), 0) FROM research_trials"
        ).fetchone()
    return int(total[0]) if total else n_tests


def build_gate(n_tests: int, alpha: float = ALPHA) -> Gate:
    """Derive this run's bars from its actual test count.

    n_tests grows as signals are added, so the bar is recomputed per run rather
    than frozen: 9 ablations imply a Bonferroni bar of 2.77, 13 imply 2.90.
    """
    own_denom = max(1, n_tests) * yekutieli_c(max(1, n_tests))
    zoo_denom = ZOO_N * yekutieli_c(ZOO_N)
    return Gate(
        n_tests=n_tests,
        own_family_bhy_t=_NORM.inv_cdf(1.0 - (alpha / own_denom) / 2.0),
        own_family_bonferroni_t=bonferroni_t(n_tests, alpha),
        zoo_bhy_t=_NORM.inv_cdf(1.0 - (alpha / zoo_denom) / 2.0),
        zoo_bonferroni_t=bonferroni_t(ZOO_N, alpha),
    )
