"""Normalisation. Compare `(816) 517-2606` with `8165172606` as raw strings and you will conclude
they differ. Every field is normalised before any comparison is made."""

from __future__ import annotations

import re
import unicodedata

import phonenumbers

from customer_dedupe.domain import Contact, Profile
from customer_dedupe.nicknames import canonical_first_name

_HONORIFICS = {"mr", "mrs", "ms", "miss", "dr", "prof", "sir", "mx"}
_NAME_SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "phd", "md", "esq"}
_COMPANY_SUFFIXES = {
    "inc", "incorporated", "llc", "ltd", "limited", "corp", "corporation", "co", "company",
    "plc", "gmbh", "pty", "pvt", "lp", "llp", "the",
}  # fmt: skip
_STREET_ABBREV = {
    "street": "st", "avenue": "ave", "av": "ave", "road": "rd", "boulevard": "blvd",
    "drive": "dr", "lane": "ln", "court": "ct", "place": "pl", "terrace": "ter",
    "parkway": "pkwy", "highway": "hwy", "circle": "cir", "square": "sq", "suite": "ste",
    "apartment": "apt", "unit": "apt", "#": "apt", "north": "n", "south": "s", "east": "e",
    "west": "w", "northeast": "ne", "northwest": "nw", "southeast": "se", "southwest": "sw",
}  # fmt: skip
_GMAIL_DOMAINS = {"gmail.com", "googlemail.com"}


def fold(text: str) -> str:
    """Lowercase, strip accents, collapse whitespace: 'José  Núñez' -> 'jose nunez'."""
    decomposed = unicodedata.normalize("NFKD", text)
    ascii_text = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", ascii_text).strip().lower()


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9#]+", fold(text))


def normalize_name(text: str) -> str:
    tokens = [t for t in _tokens(text) if t not in _HONORIFICS and t not in _NAME_SUFFIXES]
    return " ".join(tokens)


def normalize_email(text: str) -> str:
    email = fold(text)
    if "@" not in email:
        return ""
    local, _, domain = email.rpartition("@")
    local = local.split("+", 1)[0]
    if domain in _GMAIL_DOMAINS:
        local = local.replace(".", "")
        domain = "gmail.com"
    return f"{local}@{domain}" if local and "." in domain else ""


def normalize_phone(text: str, default_region: str = "US") -> str:
    """E.164 when parseable and valid, otherwise the bare digits (so we still compare something)."""
    if not text or not re.search(r"\d", text):
        return ""
    try:
        parsed = phonenumbers.parse(text, default_region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except phonenumbers.NumberParseException:
        pass
    digits = re.sub(r"\D", "", text)
    return digits if len(digits) >= 7 else ""


def normalize_company(text: str) -> str:
    return " ".join(t for t in _tokens(text.replace("&", " and ")) if t not in _COMPANY_SUFFIXES)


def normalize_street(text: str) -> str:
    tokens = [_STREET_ABBREV.get(t, t) for t in _tokens(text)]
    return " ".join(tokens)


def normalize_postal(text: str, country: str = "") -> str:
    compact = re.sub(r"[\s-]", "", text).upper()
    if (not country or fold(country) in {"us", "usa", "united states"}) and re.fullmatch(
        r"\d{5}(\d{4})?", compact
    ):
        return compact[:5]  # ZIP+4 -> ZIP
    return compact


def profile(contact: Contact, default_region: str = "US") -> Profile:
    first = normalize_name(contact.first_name)
    last = normalize_name(contact.last_name)
    first_main = first.split(" ")[0] if first else ""
    return Profile(
        contact=contact,
        first=first_main,
        first_canonical=canonical_first_name(first_main),
        last=last,
        email=normalize_email(contact.email),
        phone=normalize_phone(contact.phone, default_region),
        company=normalize_company(contact.company),
        street=normalize_street(contact.street),
        city=fold(contact.city),
        postal=normalize_postal(contact.postal_code, contact.country),
    )
