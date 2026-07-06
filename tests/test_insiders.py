from __future__ import annotations

import datetime as dt
import io
import zipfile

from cortex.sources.insiders import (
    InsiderBuyEvent,
    _parse_dataset_date,
    _parse_quarter_zip,
    _role_from_relationship,
)


def test_parse_dataset_date_handles_sec_format():
    assert _parse_dataset_date("28-FEB-2024") == dt.date(2024, 2, 28)
    assert _parse_dataset_date("01-JAN-2017") == dt.date(2017, 1, 1)
    assert _parse_dataset_date("31-dec-2025") == dt.date(2025, 12, 31)
    # junk / wrong format
    assert _parse_dataset_date("2024-02-28") is None
    assert _parse_dataset_date("") is None
    assert _parse_dataset_date("99-XXX-2024") is None


def test_role_from_relationship_priority():
    assert _role_from_relationship("Officer") == "officer"
    assert _role_from_relationship("Director,Officer") == "officer"  # officer wins
    assert _role_from_relationship("Director") == "director"
    assert _role_from_relationship("TenPercentOwner") == "owner"
    assert _role_from_relationship("Other") == "other"
    assert _role_from_relationship("") == "other"


def _make_zip(submission: str, owner: str, trans: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("SUBMISSION.tsv", submission)
        zf.writestr("REPORTINGOWNER.tsv", owner)
        zf.writestr("NONDERIV_TRANS.tsv", trans)
    return buf.getvalue()


def test_parse_quarter_zip_extracts_universe_p_buys():
    """Only P/A non-deriv buys for universe form-4 filings become events."""
    submission = (
        "ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\tISSUERTRADINGSYMBOL\n"
        # in universe, form 4 → kept
        "acc-1\t05-FEB-2024\t4\t320193\tAAPL\n"
        # not in universe → dropped
        "acc-2\t05-FEB-2024\t4\t111111\tZZZZ\n"
        # in universe but a Form 3 → dropped
        "acc-3\t06-FEB-2024\t3\t789019\tMSFT\n"
    )
    owner = (
        "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNERNAME\tRPTOWNER_RELATIONSHIP\n"
        "acc-1\t0001234567\tTim Insider\tDirector,Officer\n"
        "acc-2\t0009999999\tNobody\tDirector\n"
    )
    trans = (
        "ACCESSION_NUMBER\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES"
        "\tTRANS_PRICEPERSHARE\tTRANS_ACQUIRED_DISP_CD\n"
        # valid open-market purchase for AAPL
        "acc-1\t02-FEB-2024\tP\t1000\t150.0\tA\n"
        # a sale coded S → dropped
        "acc-1\t02-FEB-2024\tS\t500\t151.0\tD\n"
        # P for the out-of-universe issuer → dropped (acc-2 not in submissions)
        "acc-2\t02-FEB-2024\tP\t9999\t10.0\tA\n"
    )

    events = _parse_quarter_zip(_make_zip(submission, owner, trans), {"AAPL", "MSFT"})

    assert len(events) == 1
    ev = events[0]
    assert ev.ticker == "AAPL"
    assert ev.issuer_cik == "0000320193"
    assert ev.filer_cik == "1234567"
    assert ev.filer_role == "officer"
    assert ev.shares == 1000.0
    assert ev.value_usd == 150000.0
    assert ev.transaction_date == dt.date(2024, 2, 2)
    assert ev.filing_date == dt.date(2024, 2, 5)


def test_parse_quarter_zip_skips_zero_and_bad_rows():
    submission = (
        "ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\tISSUERTRADINGSYMBOL\n"
        "acc-1\t05-FEB-2024\t4\t320193\tAAPL\n"
    )
    owner = (
        "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNERNAME\tRPTOWNER_RELATIONSHIP\n"
        "acc-1\t0001234567\tTim Insider\tOfficer\n"
    )
    trans = (
        "ACCESSION_NUMBER\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES"
        "\tTRANS_PRICEPERSHARE\tTRANS_ACQUIRED_DISP_CD\n"
        "acc-1\t02-FEB-2024\tP\t0\t150.0\tA\n"  # zero shares → dropped
        "acc-1\t02-FEB-2024\tP\t100\t0\tA\n"  # zero price → dropped
        "acc-1\tbad-date\tP\t100\t150.0\tA\n"  # bad date → dropped
    )
    events = _parse_quarter_zip(_make_zip(submission, owner, trans), {"AAPL"})
    assert events == []


def _buy(**overrides) -> InsiderBuyEvent:
    base = dict(
        ticker="AAPL",
        issuer_cik="0000320193",
        filer_cik="1234567",
        filer_name="Tim Insider",
        filer_role="officer",
        transaction_date=dt.date(2024, 2, 2),
        filing_date=dt.date(2024, 2, 5),
        shares=1000.0,
        value_usd=150000.0,
        accession="acc-1",
    )
    base.update(overrides)
    return InsiderBuyEvent(**base)


def test_dedupe_id_keeps_same_day_lots_distinct():
    lot_a = _buy(shares=1000.0)
    lot_b = _buy(shares=500.0)
    assert lot_a.dedupe_id != lot_b.dedupe_id


def test_dedupe_id_distinct_per_accession():
    original = _buy(accession="acc-1")
    amendment = _buy(accession="acc-1a")
    assert original.dedupe_id != amendment.dedupe_id


def test_dedupe_id_stable_for_identical_event():
    assert _buy().dedupe_id == _buy().dedupe_id


def test_parse_quarter_zip_carries_accession():
    submission = (
        "ACCESSION_NUMBER\tFILING_DATE\tDOCUMENT_TYPE\tISSUERCIK\tISSUERTRADINGSYMBOL\n"
        "acc-1\t05-FEB-2024\t4\t320193\tAAPL\n"
    )
    owner = (
        "ACCESSION_NUMBER\tRPTOWNERCIK\tRPTOWNERNAME\tRPTOWNER_RELATIONSHIP\n"
        "acc-1\t0001234567\tTim Insider\tOfficer\n"
    )
    trans = (
        "ACCESSION_NUMBER\tTRANS_DATE\tTRANS_CODE\tTRANS_SHARES"
        "\tTRANS_PRICEPERSHARE\tTRANS_ACQUIRED_DISP_CD\n"
        "acc-1\t02-FEB-2024\tP\t1000\t150.0\tA\n"
        "acc-1\t02-FEB-2024\tP\t500\t151.0\tA\n"  # second same-day lot
    )
    events = _parse_quarter_zip(_make_zip(submission, owner, trans), {"AAPL"})
    assert len(events) == 2
    assert all(e.accession == "acc-1" for e in events)
    assert events[0].dedupe_id != events[1].dedupe_id


def test_activist_dedupe_id_distinct_per_filer():
    from cortex.sources.activism import ActivistEvent

    pershing = ActivistEvent(
        ticker="MSFT",
        subject_cik="0000789019",
        filer="Pershing Square",
        filing_date=dt.date(2024, 3, 15),
    )
    elliott = ActivistEvent(
        ticker="MSFT",
        subject_cik="0000789019",
        filer="Elliott Management",
        filing_date=dt.date(2024, 3, 15),
    )
    assert pershing.dedupe_id != elliott.dedupe_id
