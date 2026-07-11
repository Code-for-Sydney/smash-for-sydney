"""Character-roster logic for AniketBot.

The 25 spec-list names (``BOWSER``, ``CPTFALCON``, ..., ``ZELDA_SHEIK``) are
mapped to libmelee ``Character`` enums. A few special cases:

* ``ICE_CLIMBERS`` -> ``Character.POPO``. Melee spawns Nana automatically
  when Popo is selected at the CSS; libmelee exposes Popo and Nana as
  separate ``Character`` enum values, but the CSS slot is Popo.
* ``ZELDA_SHEIK`` -> ``Character.SHEIK``. ``MenuHelper`` already implements
  the "pick Zelda on the CSS, hold A after stage select to transform into
  Sheik" trickery, so from our perspective the playable character is Sheik.
"""
from typing import List

import melee
from melee.enums import Character


# ``name -> Character``. Order is preserved for nice log lines; nothing about
# the protocol depends on it.
SPEC_TO_ENUM = {
    "BOWSER":         Character.BOWSER,
    "CPTFALCON":      Character.CPTFALCON,
    "DK":             Character.DK,
    "DOC":            Character.DOC,
    "FALCO":          Character.FALCO,
    "FOX":            Character.FOX,
    "GAMEANDWATCH":   Character.GAMEANDWATCH,
    "GANONDORF":      Character.GANONDORF,
    "ICE_CLIMBERS":   Character.POPO,
    "JIGGLYPUFF":     Character.JIGGLYPUFF,
    "KIRBY":          Character.KIRBY,
    "LINK":           Character.LINK,
    "LUIGI":          Character.LUIGI,
    "MARIO":          Character.MARIO,
    "MARTH":          Character.MARTH,
    "MEWTWO":         Character.MEWTWO,
    "NESS":           Character.NESS,
    "PEACH":          Character.PEACH,
    "PICHU":          Character.PICHU,
    "PIKACHU":        Character.PIKACHU,
    "ROY":            Character.ROY,
    "SAMUS":          Character.SAMUS,
    "YLINK":          Character.YLINK,
    "YOSHI":          Character.YOSHI,
    "ZELDA_SHEIK":    Character.SHEIK,
}

# The pool of playable Character enums we draw from. Duplicates are dropped so
# the random draw stays a fair uniform pick over distinct characters.
_ENUM_POOL: List[Character] = list(dict.fromkeys(SPEC_TO_ENUM.values()))


def spec_names_for(char: Character) -> List[str]:
    """Return the spec-list labels that map to ``char`` (usually one)."""
    return [name for name, c in SPEC_TO_ENUM.items() if c == char]


def pick_roster(size: int = 3) -> List[Character]:
    """Return ``size`` distinct ``Character`` enums sampled from the spec pool.

    ``random.sample`` guarantees distinctness, which matters because the
    collision-avoidance logic in ``AniketBot`` assumes ``len(set(roster))``
    equals ``len(roster)`` so that it can always find a slot that differs
    from the opponent's pick.
    """
    import random
    return random.sample(_ENUM_POOL, k=size)


def first_slot_away_from(roster: List[Character], opponent_char: Character) -> Character:
    """Pick the first roster slot whose enum differs from ``opponent_char``.

    Returns ``roster[0]`` if every slot matches (only possible if the roster
    was constructed with duplicates, which ``pick_roster`` never does).
    """
    for c in roster:
        if c != opponent_char:
            return c
    return roster[0]