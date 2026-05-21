import re

NH_SIRE_SCORES: dict[str, float] = {
    # Premium NH sires (9-10)
    "Flemensfirth": 9.5,
    "Presenting": 9.0,
    "Oscar": 9.0,
    "King's Theatre": 9.0,
    "Mahler": 8.5,
    "Milan": 8.5,
    "Robin des Champs": 8.5,
    "Stowaway": 8.5,
    "Kayf Tara": 8.5,
    # Very good NH sires (7-8.5)
    "Yeats": 8.0,
    "Walk In The Park": 8.0,
    "Galiway": 7.5,
    "Getaway": 7.5,
    "Doyen": 7.5,
    "Authorized": 7.5,
    "High Chaparral": 7.5,
    "Westerner": 7.5,
    "Shantou": 7.5,
    "Midnight Legend": 7.5,
    "Mount Nelson": 7.5,
    "Shirocco": 7.5,
    "Galileo": 7.0,
    "Dylan Thomas": 7.0,
    "Gold Well": 7.0,
    "Jeremy": 7.0,
    "Beneficial": 7.0,
    "Kalanisi": 7.0,
    "Scorpion": 7.0,
    "Black Sam Bellamy": 7.0,
    "Dr Massini": 7.0,
    "Montjeu": 7.0,
    "Luso": 7.0,
    "Sadler's Wells": 7.0,
    "Strong Gale": 7.0,
    "Roselier": 7.0,
    # Good NH sires (5.5-7)
    "Old Vic": 6.5,
    "Bob Back": 6.5,
    "Be My Native": 6.5,
    "Hernando": 6.5,
    "Daylami": 6.5,
    "Winged Love": 6.5,
    "Indian River": 6.5,
    "Saddlers' Hall": 6.5,
    "Witness Box": 6.5,
    "Good Thyne": 6.0,
    "Phardante": 6.0,
    "Accordion": 6.0,
    "Great Palm": 6.0,
    "Definite Article": 6.0,
    "Be My Chief": 6.0,
    "Blueprint": 5.5,
}

_DEFAULT_SCORE = 4.0  # Unknown or unproven NH sire


def _normalise(name: str) -> str:
    """Strip country suffix like ' (IRE)', ' (FR)', ' (GB)', ' (USA)'."""
    return re.sub(r"\s*\([A-Z]{2,3}\)\s*$", "", name.strip())


def _lookup(name: str | None) -> float:
    if not name:
        return _DEFAULT_SCORE
    key = _normalise(name)
    if key in NH_SIRE_SCORES:
        return NH_SIRE_SCORES[key]
    if key.title() in NH_SIRE_SCORES:
        return NH_SIRE_SCORES[key.title()]
    return _DEFAULT_SCORE


def score_lot(sire: str | None, dam_sire: str | None, second_dam_sire: str | None) -> float:
    """Return 0-100 NH pedigree score. Sire 50%, dam sire 30%, 2nd dam sire 20%."""
    s = _lookup(sire) * 0.5
    ds = _lookup(dam_sire) * 0.3
    sds = _lookup(second_dam_sire) * 0.2
    return round((s + ds + sds) * 10, 1)
