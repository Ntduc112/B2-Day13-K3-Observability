import pytest

from app.pii import scrub_text, scrub_value


def test_scrub_email() -> None:
    out = scrub_text("Email me at student@vinuni.edu.vn")
    assert "student@" not in out
    assert "REDACTED_EMAIL" in out


def test_scrub_email_with_plus_tag_without_leaving_partial_address() -> None:
    email = "student+observability@example.com"

    out = scrub_text(f"Email: {email}")

    assert "student+" not in out
    assert "[REDACTED_EMAIL]" in out


def test_scrub_common_vietnamese_phone_formats() -> None:
    phone_numbers = (
        "0901234567",
        "090 123 4567",
        "090.123.4567",
        "090-123-4567",
        "+84 90 123 4567",
    )

    for phone_number in phone_numbers:
        out = scrub_text(f"Contact: {phone_number}")
        assert phone_number not in out
        assert "REDACTED_PHONE_VN" in out


@pytest.mark.parametrize(
    ("pii_type", "value"),
    (
        ("CCCD", "001203004567"),
        ("CREDIT_CARD", "4111 1111 1111 1111"),
        ("PASSPORT", "B1234567"),
        ("ADDRESS", "Dia chi: 123 Duong Vi Du, Phuong Mau, Ha Noi"),
    ),
)
def test_scrub_supported_identity_and_payment_data(
    pii_type: str, value: str
) -> None:
    out = scrub_text(f"Customer data: {value}")

    assert value not in out
    assert f"[REDACTED_{pii_type}]" in out


@pytest.mark.parametrize(
    ("pii_type", "value"),
    (
        ("PHONE_VN", 84901234567),
        ("CCCD", 123456789012),
        ("CREDIT_CARD", 4111111111111111),
    ),
)
def test_scrub_numeric_pii_in_structured_payloads(
    pii_type: str, value: int
) -> None:
    out = scrub_value({"value": value})

    assert out["value"] == f"[REDACTED_{pii_type}]"
