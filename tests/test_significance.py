from __future__ import annotations

import pytest

from cortex.significance import (
    ZOO_FACTORS,
    bhy,
    bonferroni_t,
    build_gate,
    two_sided_p,
    yekutieli_c,
)


def test_two_sided_p_known_values():
    assert two_sided_p(1.96) == pytest.approx(0.05, abs=1e-3)
    assert two_sided_p(0.0) == pytest.approx(1.0)
    # sign is irrelevant — a reliably negative factor is still a discovery
    assert two_sided_p(-2.5) == pytest.approx(two_sided_p(2.5))


def test_bonferroni_rises_with_test_count():
    assert bonferroni_t(1) == pytest.approx(1.96, abs=0.01)
    assert bonferroni_t(9) == pytest.approx(2.77, abs=0.01)
    assert bonferroni_t(12) == pytest.approx(2.87, abs=0.01)
    # Harvey/Liu/Zhu report 3.78 for the 316-factor published zoo
    assert bonferroni_t(316) == pytest.approx(3.78, abs=0.02)


def test_bonferroni_is_monotonic():
    ts = [bonferroni_t(n) for n in (1, 5, 10, 50, 100, 316)]
    assert ts == sorted(ts)


def test_yekutieli_c_is_the_harmonic_number():
    assert yekutieli_c(1) == pytest.approx(1.0)
    assert yekutieli_c(3) == pytest.approx(1 + 0.5 + 1 / 3)
    assert yekutieli_c(9) == pytest.approx(2.829, abs=1e-3)


def test_bhy_passes_nothing_when_no_test_is_strong():
    """CORTEX's 2026-08-10 readings: the best is fund at 2.42 and it is short."""
    result = bhy(
        {
            "congress": 2.24,
            "fund": 2.42,
            "quality": 1.10,
            "trend": 0.71,
            "mom": 0.38,
            "value": 0.13,
            "insider": -0.35,
            "vol": -0.47,
            "activism": -1.71,
        }
    )
    assert result.passed == frozenset()
    assert result.implied_t == pytest.approx(3.10, abs=0.02)


def test_bhy_admits_a_genuine_discovery():
    result = bhy({"strong": 5.0, "weak": 0.2, "middling": 1.1})
    assert "strong" in result.passed
    assert "weak" not in result.passed


def test_bhy_step_up_admits_the_whole_prefix():
    """BH is step-up: if rank k passes, every better-ranked test passes too."""
    result = bhy({"a": 6.0, "b": 5.5, "c": 0.1})
    assert result.passed == frozenset({"a", "b"})


def test_bhy_negative_tstat_can_be_a_discovery():
    result = bhy({"short_leg": -6.0, "noise": 0.3})
    assert "short_leg" in result.passed


def test_bhy_empty_family():
    result = bhy({})
    assert result.passed == frozenset()
    assert result.implied_t is None


def test_gate_applies_a_higher_bar_to_zoo_factors():
    """A factor lifted from the published literature inherits its burden."""
    gate = build_gate(12)
    assert gate.threshold_for("mom") > gate.threshold_for("congress")
    assert gate.threshold_for("value") == gate.zoo_bhy_t
    assert gate.threshold_for("fund") == gate.own_family_bhy_t
    # every zoo name routes to the zoo bar
    for name in ZOO_FACTORS:
        assert gate.threshold_for(name) == gate.zoo_bhy_t


def test_gate_bar_rises_with_the_test_count():
    """Adding signals raises the bar for the whole own-family set."""
    assert build_gate(13).own_family_bhy_t > build_gate(9).own_family_bhy_t


def test_gate_verdict_ignores_sign():
    gate = build_gate(12)
    strong = gate.own_family_bhy_t + 1.0
    assert gate.verdict("fund", strong) == "PASS"
    assert gate.verdict("fund", -strong) == "PASS"
    assert gate.verdict("fund", 0.5) == "FAIL"


def test_bhy_is_stricter_than_bonferroni_for_a_lone_discovery():
    """Yekutieli's dependence correction costs a factor of c(n) at rank 1.

    Worth asserting because the intuition runs the other way: BHY is the more
    lenient procedure only once several tests are significant.
    """
    gate = build_gate(12)
    assert gate.own_family_bhy_t > gate.own_family_bonferroni_t
