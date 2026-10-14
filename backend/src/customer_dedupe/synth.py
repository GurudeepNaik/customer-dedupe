"""Synthetic CRM/ERP/web-shop contacts with a known answer key.

Each person gets 1-4 records across systems with the corruption real data has: typos,
nicknames, swapped first/last, phone formats, Gmail dots and +tags, ZIP+4, abbreviations,
missing fields, people who moved. It also plants the hard negatives that break naive dedupe:
family members sharing an address and landline, colleagues sharing a company switchboard,
and unrelated people with very common names in the same town.
"""

from __future__ import annotations

import random
import string
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from customer_dedupe.domain import Contact
from customer_dedupe.nicknames import _GROUPS

FIRST = [
    "william", "robert", "richard", "james", "john", "joseph", "michael", "thomas", "charles",
    "edward", "daniel", "david", "anthony", "matthew", "andrew", "benjamin", "nicholas",
    "steven", "gregory", "kenneth", "elizabeth", "margaret", "katherine", "jennifer", "rebecca",
    "patricia", "susan", "deborah", "victoria", "jessica", "maria", "priya", "wei", "fatima",
    "olumide", "sofia", "lucas", "aarav", "yuki", "mateo", "amara", "noah", "emma", "olivia",
    "ava", "mia", "ethan", "chloe", "isabella", "grace",
]  # fmt: skip
LAST = [
    "smith", "johnson", "williams", "brown", "jones", "garcia", "miller", "davis", "rodriguez",
    "martinez", "hernandez", "lopez", "wilson", "anderson", "thomas", "taylor", "moore",
    "jackson", "martin", "lee", "thompson", "white", "harris", "clark", "lewis", "robinson",
    "walker", "young", "allen", "king", "wright", "scott", "nguyen", "hill", "flores", "green",
    "adams", "nelson", "baker", "hall", "rivera", "campbell", "mitchell", "carter", "roberts",
    "okonkwo", "patel", "kowalski", "fitzgerald", "nakamura", "haddad", "oyelaran", "lindqvist",
    "castellanos", "abernathy", "vasquez", "oconnor", "sullivan", "murphy", "chen",
]  # fmt: skip
STREETS = [
    "Main", "Oak", "Maple", "Cedar", "Pine", "Elm", "Washington", "Lake", "Hill", "Park",
    "Sunset", "Ridge", "Highland", "Meadow", "Forest", "River", "Spring", "Church", "Mill", "Grove",
]  # fmt: skip
SUFFIX = [("Street", "St"), ("Avenue", "Ave"), ("Road", "Rd"), ("Drive", "Dr"), ("Lane", "Ln")]
CITIES = [
    ("Kansas City", "MO", "641", "816"), ("Overland Park", "KS", "662", "913"),
    ("Austin", "TX", "787", "512"), ("Denver", "CO", "802", "303"),
    ("Portland", "OR", "972", "503"), ("Columbus", "OH", "432", "614"),
    ("Raleigh", "NC", "276", "919"), ("Madison", "WI", "537", "608"),
]  # fmt: skip
COMPANIES = [
    "Acme Robotics",
    "Northwind Traders",
    "Blue Harbor Media",
    "Summit Analytics",
    "Redwood Labs",
    "Brightline Logistics",
    "Copperleaf Health",
    "Ironbridge Capital",
]
DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "icloud.com"]
SOURCES = ["crm", "erp", "shop"]
VARIANTS = {canonical: variants for canonical, variants in _GROUPS.items()}


@dataclass
class Person:
    entity: str
    first: str
    last: str
    email: str
    phone: str
    company: str
    street: str
    city: str
    region: str
    zip5: str


@dataclass
class Dataset:
    contacts: list[Contact] = field(default_factory=list)
    truth: dict[str, str] = field(default_factory=dict)  # contact id -> entity id


def generate(people: int = 1500, seed: int = 11) -> Dataset:
    rng = random.Random(seed)
    data = Dataset()
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    used_phones: set[str] = set()
    used_emails: set[str] = set()

    def phone(area: str) -> str:
        while True:
            number = f"{area}{rng.randint(200, 999)}{rng.randint(0, 9999):04d}"
            if number not in used_phones:
                used_phones.add(number)
                return number

    def new_person(i: int, **overrides: str) -> Person:
        first, last = rng.choice(FIRST), rng.choice(LAST)
        city, region, zip3, area = rng.choice(CITIES)
        while True:
            local = rng.choice(
                [f"{first}.{last}", f"{first[0]}{last}", f"{first}{last}{rng.randint(1, 99)}"]
            )
            email = f"{local}@{rng.choice(DOMAINS)}"
            if email not in used_emails:
                used_emails.add(email)
                break
        num, (sfull, _) = rng.randint(10, 9999), rng.choice(SUFFIX)
        p = Person(
            entity=f"E{i:05d}",
            first=first,
            last=last,
            email=email,
            phone=phone(area),
            company=rng.choice(COMPANIES) if rng.random() < 0.5 else "",
            street=f"{num} {rng.choice(STREETS)} {sfull}",
            city=city,
            region=region,
            zip5=f"{zip3}{rng.randint(0, 99):02d}",
        )
        return replace(p, **overrides)

    persons: list[Person] = [new_person(i) for i in range(people)]

    # Hard negatives: households sharing address + landline, different first names.
    household_firsts: dict[str, set[str]] = {}
    for k in range(people // 15):
        host = rng.choice(persons[:people])
        taken = household_firsts.setdefault(host.entity, {host.first})
        member_first = rng.choice([f for f in FIRST if f not in taken])
        taken.add(member_first)
        persons.append(
            new_person(
                people + k,
                first=member_first,
                last=host.last,
                phone=host.phone,
                street=host.street,
                city=host.city,
                region=host.region,
                zip5=host.zip5,
                email=f"{member_first}.{host.last}{rng.randint(1, 9)}@{rng.choice(DOMAINS)}",
            )
        )
    # Hard negatives: same common name, same town, otherwise unrelated.
    start = len(persons)
    for k in range(people // 20):
        host = rng.choice([p for p in persons if p.last in LAST[:10]])
        persons.append(
            new_person(start + k, first=host.first, last=host.last, city=host.city,
                       region=host.region, zip5=host.zip5)
        )  # fmt: skip

    counter = 0
    for person in persons:
        n_records = rng.choices([1, 2, 3, 4], weights=[45, 30, 17, 8])[0]
        for _ in range(n_records):
            counter += 1
            cid = f"C{counter:06d}"
            data.contacts.append(_corrupt(rng, person, cid, base_time))
            data.truth[cid] = person.entity
    rng.shuffle(data.contacts)
    return data


def _typo(rng: random.Random, s: str) -> str:
    if len(s) < 4:
        return s
    i = rng.randint(1, len(s) - 2)
    op = rng.choice(["swap", "drop", "sub"])
    if op == "swap":
        return s[:i] + s[i + 1] + s[i] + s[i + 2 :]
    if op == "drop":
        return s[:i] + s[i + 1 :]
    return s[:i] + rng.choice(string.ascii_lowercase) + s[i + 1 :]


def _fmt_phone(rng: random.Random, digits: str) -> str:
    a, b, c = digits[:3], digits[3:6], digits[6:]
    return rng.choice(
        [f"({a}) {b}-{c}", f"{a}-{b}-{c}", f"{a}.{b}.{c}", f"+1 {a} {b} {c}", digits, f"1{digits}"]
    )


def _corrupt(rng: random.Random, p: Person, cid: str, base: datetime) -> Contact:
    first, last = p.first, p.last
    if rng.random() < 0.25 and first in VARIANTS:
        first = rng.choice(VARIANTS[first])
    if rng.random() < 0.08:
        first = _typo(rng, first)
    if rng.random() < 0.06:
        last = _typo(rng, last)
    if rng.random() < 0.05:
        first = first[0]

    def title(s: str) -> str:
        return s.title() if rng.random() < 0.8 else s.upper()

    first_out, last_out = title(first), title(last)
    if rng.random() < 0.03:
        first_out, last_out = last_out, first_out

    email = p.email
    if rng.random() < 0.3 and email.endswith("gmail.com"):
        local, domain = email.split("@")
        email = rng.choice([local.replace(".", ""), f"{local}+shop", local.upper()]) + "@" + domain
    if rng.random() < 0.25:
        email = ""

    phone = _fmt_phone(rng, p.phone) if rng.random() > 0.25 else ""

    street = p.street
    for full, short in SUFFIX:
        if rng.random() < 0.5:
            street = street.replace(full, short)
    if rng.random() < 0.1:
        street = f"{street} Apt {rng.randint(1, 30)}"
    zip_code = p.zip5 + (f"-{rng.randint(1000, 9999)}" if rng.random() < 0.2 else "")
    city = p.city
    if rng.random() < 0.15:
        street, city, zip_code = "", "", ""

    company = p.company
    if company and rng.random() < 0.4:
        company = company + rng.choice([" Inc", ", LLC", " Inc.", " Ltd"])

    return Contact(
        id=cid,
        source=rng.choice(SOURCES),
        first_name=first_out,
        last_name=last_out,
        email=email,
        phone=phone,
        company=company,
        street=street,
        city=city,
        region=p.region if city else "",
        postal_code=zip_code,
        country="US",
        updated_at=base + timedelta(days=rng.randint(0, 900)),
    )
