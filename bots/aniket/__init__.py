"""AniketBot: a port-agnostic Smash bot that commits to a 3-character roster.

Importing from this package:

    from bots.aniket import AniketBot

The bot:
  * randomly selects 3 distinct characters at construction from the 25 spec
    names (BOWSER, CPTFALCON, DK, DOC, FALCO, FOX, GAMEANDWATCH, GANONDORF,
    ICE_CLIMBERS, JIGGLYPUFF, KIRBY, LINK, LUIGI, MARIO, MARTH, MEWTWO, NESS,
    PEACH, PICHU, PIKACHU, ROY, SAMUS, YLINK, YOSHI, ZELDA_SHEIK) and rotates
    only within those three -- it never plays anything outside the roster.
  * finds out which port it lives on at runtime (see ``AniketBot.connect``)
    and which port the other player occupies (see ``AniketBot.menu``).
  * lets the other player commit a character at the character-select screen
    first, then snaps to a roster slot whose enum differs from the opponent's
    CSS-committed character. libmelee's ``MenuHelper`` reclaims our coin and
    walks us to the new slot on the next frame, so the collision resolves
    automatically without any inter-bot channel.
"""

from .aniket_bot import AniketBot

__all__ = ["AniketBot"]