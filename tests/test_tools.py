from datetime import datetime, timedelta

import pytest

from agent import (
    SEARCH_MIN_SCORE,
    SEARCH_TOP_K,
    calculate_refund,
    get_booking,
    load_sections,
    search_policies,
)

CW_1007_START = datetime.fromisoformat("2026-06-12T09:00:00+02:00")


@pytest.mark.parametrize(
    "booking_id, percent, rental_refund, deposit_refund, total",
    [
        ("CW-1001", 100, 40, 50, 90),
        ("CW-1002", 50, 40, 300, 340),
        ("CW-1003", 0, 0, 50, 50),
        ("CW-1004", 100, 23, 50, 73),
        ("CW-1007", 100, 36, 150, 186),
        ("CW-1009", 100, 119, 50, 169),
        ("CW-1010", 50, 20, 150, 170),
    ],
)
def test_refund_for_confirmed_bookings(
    booking_id, percent, rental_refund, deposit_refund, total
):
    refund = calculate_refund(booking_id)

    assert refund["found"] is True
    assert refund["can_cancel"] is True
    assert refund["refund_percent"] == percent
    assert refund["rental_refund_eur"] == rental_refund
    assert refund["deposit_refund_eur"] == deposit_refund
    assert refund["total_refund_eur"] == total


@pytest.mark.parametrize(
    "time_before_start, percent, total",
    [
        (timedelta(hours=72), 100, 186),
        (timedelta(hours=48), 100, 186),
        (timedelta(hours=47, minutes=59), 50, 168),
        (timedelta(hours=24), 50, 168),
        (timedelta(hours=23, minutes=59), 0, 150),
        (timedelta(minutes=1), 0, 150),
    ],
)
def test_refund_percent_depends_on_time_before_start(
    monkeypatch, time_before_start, percent, total
):
    monkeypatch.setattr("agent.NOW", CW_1007_START - time_before_start)

    refund = calculate_refund("CW-1007")

    assert refund["refund_percent"] == percent
    assert refund["total_refund_eur"] == total


@pytest.mark.parametrize(
    "booking_id, status",
    [
        ("CW-1005", "cancelled"),
        ("CW-1006", "completed"),
        ("CW-1008", "in_progress"),
    ],
)
def test_only_confirmed_bookings_can_be_cancelled(booking_id, status):
    refund = calculate_refund(booking_id)

    assert refund["found"] is True
    assert refund["can_cancel"] is False
    assert refund["status"] == status
    assert "total_refund_eur" not in refund


def test_booking_fee_is_never_refunded():
    # CW-1001 has a 2 EUR booking fee: 40 EUR rental + 50 EUR deposit, without the fee.
    refund = calculate_refund("CW-1001")

    assert refund["booking_fee_refund_eur"] == 0
    assert refund["total_refund_eur"] == 90


@pytest.mark.parametrize(
    "booking_id, paid_with",
    [
        ("CW-1001", "card"),
        ("CW-1004", "voucher"),
    ],
)
def test_refund_reports_payment_method(booking_id, paid_with):
    assert calculate_refund(booking_id)["paid_with"] == paid_with


def test_refund_for_unknown_booking():
    assert calculate_refund("CW-9999") == {"found": False, "booking_id": "CW-9999"}


@pytest.mark.parametrize("booking_id", ["cw-1002", " CW-1002 "])
def test_refund_accepts_differently_written_booking_number(booking_id):
    assert calculate_refund(booking_id)["total_refund_eur"] == 340


def test_get_booking_returns_details():
    booking = get_booking("CW-1004")

    assert booking["id"] == "CW-1004"
    assert booking["status"] == "confirmed"
    assert booking["add_ons"] == ["child_seat"]
    assert booking["paid_with"] == "voucher"


@pytest.mark.parametrize("booking_id", ["cw-1002", " CW-1002 "])
def test_get_booking_accepts_differently_written_booking_number(booking_id):
    assert get_booking(booking_id)["id"] == "CW-1002"


def test_get_booking_reports_unknown_booking():
    assert get_booking("CW-9999") == "Booking not found"


def test_load_sections_splits_documents_by_heading():
    sections = load_sections()

    assert len(sections) == 22
    assert {section["file"] for section in sections} == {
        "cancellations.md",
        "faq.md",
        "prices.md",
    }
    assert all(section["text"] for section in sections)
    assert not any("## " in section["text"] for section in sections)


def test_load_sections_keeps_heading_and_text_together():
    sections = load_sections()

    dog = next(s for s in sections if s["heading"] == "Can I take my dog?")
    assert dog["file"] == "faq.md"
    assert dog["text"] == "Dogs are not allowed in bike baskets or child seats."


def test_load_sections_keeps_text_before_first_heading():
    sections = load_sections()

    prices = next(s for s in sections if s["heading"] == "Prices")
    assert prices["file"] == "prices.md"
    assert "include VAT" in prices["text"]


def fake_embed(scores, requests=None):
    """Replaces the embeddings API: a section's vector gives its score against the query [1, 0]."""

    def embed(texts):
        if requests is not None:
            requests.append(texts)
        if texts == ["the query"]:
            return [[1, 0]]
        return [[scores.get(text.split("\n")[0], 0), 0] for text in texts]

    return embed


def test_search_returns_best_sections_in_order(monkeypatch):
    scores = {"Deposit": 0.5, "Bad weather": 0.9, "Late return": 0.7}
    monkeypatch.setattr("agent.embed", fake_embed(scores))

    result = search_policies("the query")

    assert result["found"] is True
    assert [section["heading"] for section in result["results"]] == [
        "Bad weather",
        "Late return",
        "Deposit",
    ]
    assert [section["score"] for section in result["results"]] == [0.9, 0.7, 0.5]


def test_search_returns_file_heading_and_text(monkeypatch):
    monkeypatch.setattr("agent.embed", fake_embed({"Can I take my dog?": 0.9}))

    section = search_policies("the query")["results"][0]

    assert section == {
        "file": "faq.md",
        "heading": "Can I take my dog?",
        "text": "Dogs are not allowed in bike baskets or child seats.",
        "score": 0.9,
    }


def test_search_returns_at_most_top_k_sections(monkeypatch):
    scores = {
        "Deposit": 0.9,
        "Bad weather": 0.8,
        "Late return": 0.7,
        "Booking fee": 0.6,
        "Add-ons": 0.5,
    }
    monkeypatch.setattr("agent.embed", fake_embed(scores))

    result = search_policies("the query")

    assert len(result["results"]) == SEARCH_TOP_K
    assert "Booking fee" not in [section["heading"] for section in result["results"]]


def test_search_skips_sections_below_min_score(monkeypatch):
    scores = {"Deposit": SEARCH_MIN_SCORE, "Bad weather": SEARCH_MIN_SCORE - 0.01}
    monkeypatch.setattr("agent.embed", fake_embed(scores))

    result = search_policies("the query")

    assert [section["heading"] for section in result["results"]] == ["Deposit"]


def test_search_reports_when_nothing_matches(monkeypatch):
    monkeypatch.setattr("agent.embed", fake_embed({"Deposit": SEARCH_MIN_SCORE - 0.01}))

    assert search_policies("the query") == {"found": False, "results": []}


def test_search_embeds_headings_with_text_and_the_query(monkeypatch):
    requests = []
    monkeypatch.setattr("agent.embed", fake_embed({}, requests))

    search_policies("the query")

    section_texts, query_texts = requests
    assert len(section_texts) == 22
    assert (
        "Can I take my dog?\nDogs are not allowed in bike baskets or child seats."
        in section_texts
    )
    assert query_texts == ["the query"]
