"""Common English given-name variants mapped to one canonical form. Deliberately conservative:
ambiguous short forms (e.g. 'Chris', 'Alex', 'Sam') map to the most common long form only when
that is overwhelmingly likely in a customer database, otherwise they are left alone."""

_GROUPS: dict[str, tuple[str, ...]] = {
    "william": ("bill", "billy", "will", "willy", "liam"),
    "robert": ("bob", "bobby", "rob", "robbie"),
    "richard": ("rick", "ricky", "rich", "dick"),
    "james": ("jim", "jimmy", "jamie"),
    "john": ("jack", "johnny", "jon"),
    "joseph": ("joe", "joey"),
    "michael": ("mike", "mikey", "mick"),
    "thomas": ("tom", "tommy"),
    "charles": ("charlie", "chuck", "chas"),
    "edward": ("ed", "eddie", "ted", "ned"),
    "daniel": ("dan", "danny"),
    "david": ("dave", "davey"),
    "anthony": ("tony",),
    "matthew": ("matt",),
    "andrew": ("andy",),
    "benjamin": ("ben", "benny"),
    "nicholas": ("nick", "nicky"),
    "steven": ("steve", "stephen", "stevie"),
    "gregory": ("greg",),
    "kenneth": ("ken", "kenny"),
    "timothy": ("tim", "timmy"),
    "jeffrey": ("jeff", "geoffrey"),
    "patrick": ("paddy",),
    "peter": ("pete",),
    "samuel": ("sam", "sammy"),
    "zachary": ("zach", "zack"),
    "elizabeth": ("liz", "lizzie", "beth", "betty", "eliza", "betsy"),
    "margaret": ("maggie", "meg", "peggy", "marge"),
    "katherine": ("kate", "kathy", "katie", "catherine", "kathryn", "cathy"),
    "jennifer": ("jen", "jenny"),
    "rebecca": ("becky", "becca"),
    "patricia": ("patty", "trish", "tricia"),
    "susan": ("sue", "susie"),
    "deborah": ("deb", "debbie", "debra"),
    "victoria": ("vicky", "tori"),
    "christina": ("tina", "christine"),
    "jessica": ("jess", "jessie"),
    "alexandra": ("lexi",),
    "abigail": ("abby",),
    "pamela": ("pam",),
    "kimberly": ("kim",),
    "barbara": ("barb",),
    "theresa": ("tess", "teresa"),
}

NICKNAMES: dict[str, str] = {
    variant: canonical for canonical, variants in _GROUPS.items() for variant in variants
}


def canonical_first_name(name: str) -> str:
    return NICKNAMES.get(name, name)


FORMS: dict[str, frozenset[str]] = {
    canonical: frozenset((canonical, *variants)) for canonical, variants in _GROUPS.items()
}


def name_forms(canonical: str, written: str) -> frozenset[str]:
    """Every spelling we accept for this person's given name."""
    return FORMS.get(canonical, frozenset()) | {canonical, written}
