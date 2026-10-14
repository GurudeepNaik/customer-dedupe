import pytest

from customer_dedupe.domain import Contact
from customer_dedupe.normalize import (
    fold,
    normalize_company,
    normalize_email,
    normalize_name,
    normalize_phone,
    normalize_postal,
    normalize_street,
    profile,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(816) 517-2606", "+18165172606"),
        ("816.517.2606", "+18165172606"),
        ("+1 816 517 2606", "+18165172606"),
        ("18165172606", "+18165172606"),
        ("8165172606", "+18165172606"),
        ("", ""),
        ("n/a", ""),
    ],
)
def test_phone_formats_normalise_to_e164(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("John.Smith+shop@GMAIL.com", "johnsmith@gmail.com"),
        ("john.smith@googlemail.com", "johnsmith@gmail.com"),
        ("j.smith@acme.com", "j.smith@acme.com"),  # dots matter outside Gmail
        ("not-an-email", ""),
    ],
)
def test_email(raw: str, expected: str) -> None:
    assert normalize_email(raw) == expected


def test_names_and_accents() -> None:
    assert normalize_name("Dr. José  Núñez Jr.") == "jose nunez"
    assert fold("ÉLODIE") == "elodie"


def test_company_suffixes_and_ampersand() -> None:
    assert normalize_company("Smith & Sons, LLC") == normalize_company("Smith and Sons Inc.")


def test_street_abbreviations() -> None:
    assert normalize_street("12 North Main Street, Apartment 4") == "12 n main st apt 4"


def test_zip_plus_four() -> None:
    assert normalize_postal("64111-2233") == "64111"
    assert normalize_postal("sw1a 1aa", "GB") == "SW1A1AA"


def test_profile_resolves_nickname() -> None:
    p = profile(Contact(id="1", first_name="Bob", last_name="Smith"))
    assert (p.first, p.first_canonical, p.last) == ("bob", "robert", "smith")
