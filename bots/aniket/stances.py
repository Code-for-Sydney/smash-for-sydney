"""AniketBot's stance model.

Five mutually-exclusive behaviour modes, one active at a time:

    ATTACK   - rushdown: always close distance, jab/nair in, grab vs shield.
    DEFENCE  - hold a spacing radius, f-tilt approaches, shield projectiles.
    STANDOFF - retreat to the far side and zone with neutral-B projectiles.
               Deliberately rare (see ``select_stance`` gate).
    ROGUE    - dash-dance, cross-up jumps, grab-heavy, unpredictable.
    SLY      - hover just outside the opponent's range; whiff-punish off
               ``hitlag_left``/``hitstun``; edgeguard when they're off-stage.

Design rules this module encodes:

* Per-character disposition is derived from ``characterdata.csv`` (walk speed,
  air mobility, jump count, size) plus a hard-coded projectile set -- the
  spec's 25 chars get a hand-tuned ``{Stance: weight}`` table below.
* Situation overrides modulate the weights: stock differential, percent
  differential, opponent off-stage, distance.
* **If nothing is happening (neutral game), default to ATTACK.** Even
  stocks, neither side in kill range, opponent on-stage, not already in
  striking range -> the character's disposition can nudge but cannot
  overrule "move toward the opponent". This is the user-facing default.
* **If our health is really bad (>= ``KILL_HEALTH`` %), fall back to
  STANDOFF and SLY** (stall/bait) and strip rushdown. Projectile chars do
  *both* (the brief asks for "standoff and sly"); non-projectile chars lose
  STANDOFF at the gate and absorb into SLY. Close-range cancels camping
  (no room to zone) so SLY takes over.
* STANDOFF is otherwise gated to be rare: weight is forced to zero unless
  the character has a projectile AND distance > STANDOFF_MIN_RANGE AND one
  of (ahead on stocks / opponent % high / our % very low / our % really
  bad). The "preferably not often" rule made mechanical.
* A chosen stance locks for ``STANCE_LOCK_FRAMES`` game frames so we don't
  flip-flop between SLY and ATTACK every frame. When the top weights tie
  (the bad-health STANDOFF/SLY case), exploit picks randomly among the
  ties so both archetypes actually surface.
"""
import random
from enum import Enum
from typing import Dict

import melee
from melee.enums import Action, Button, Character

from . import movement as mv


class Stance(str, Enum):
    ATTACK = "ATTACK"
    DEFENCE = "DEFENCE"
    STANDOFF = "STANDOFF"
    ROGUE = "ROGUE"
    SLY = "SLY"


# Range/speed tuning (Melee units -- roughly stage tiles). Distances are in
# gamestate.distance / position.x units.
ATTACK_RANGE = 8.0     # in striking range; throw a hitbox
SPACING_RANGE = 18.0   # spacing radius -- tip of a f-tilt / safe poke
APPROACH_RANGE = 30.0  # inside dash distance -- commit to an approach
STANDOFF_MIN_RANGE = 40.0   # closer than this and STANDOFF is pointless
STAGE_HALF_WIDTH = 70.0     # ~ Final Destination blast-zone minus ledge

STANCE_LOCK_FRAMES = 18     # min frames before we re-select the stance (snappier switching)
STANDOFF_PROJECTILE_EVERY = 30  # frames between neutral-B shots while zoning
KILL_HEALTH = 100         # our_pct at/above this => "health is really bad"


# Projectiles that can actually zone a standoff from across the stage. A
# conservative set: each of these has a neutral-B (or pulled-item) projectile
# that travels a meaningful distance.
HAS_PROJECTILE = frozenset({
    Character.FOX,         # laser (neutral-B)
    Character.FALCO,       # laser (neutral-B)
    Character.SAMUS,       # missiles / charge shot
    Character.LINK,        # bow / bombs / boomerang (neutral-B arrow)
    Character.YLINK,       # same
    Character.MEWTWO,     # shadow ball
    Character.NESS,        # PK flash (neutral-B); situational
    Character.PIKACHU,     # thunder jolt (neutral-B)
    Character.PICHU,       # thunder jolt (self-damaging -- still zones)
    Character.DOC,         # Megavitamins
    Character.MARIO,       # fireball (weak -- low disposition)
    Character.SHEIK,       # needles (neutral-B)
    Character.BOWSER,      # fire breath (neutral-B) -- short range-ish
    Character.PEACH,       # turnip (down-B pull) -- treat neutral-B as float poke
})


# Per-character archetype disposition. Weights are *relative* within the
# character's own table; STANDOFF is omitted entirely for non-projectile
# chars (``select_stance`` zeroes it anyway, but omitting it here keeps the
# table readable). Weights are hand-tuned from the stat table + Smash matchups
# intuition; finer-grained per-char tuning is the obvious follow-up.
#
# Heuristics used:
#   walk>=1.3 or airmob>=0.07          -> ATTACK-friendly (rushdown fodder)
#   size>=14                           -> DEFENCE-friendly (big hurtbox, slower)
#   jumps>1 or airmob>=0.20            -> SLY-friendly (float/drift bait)
#   grab-centric kits (% change)       -> ROGUE-friendly
CHARACTER_DISPOSITION: Dict[Character, Dict[Stance, float]] = {
    Character.FOX:        {Stance.ATTACK: 1.4, Stance.ROGUE: 0.8, Stance.SLY: 0.2},
    Character.FALCO:      {Stance.ATTACK: 1.3, Stance.ROGUE: 0.6, Stance.SLY: 0.2},
    Character.CPTFALCON:  {Stance.ATTACK: 1.3, Stance.ROGUE: 1.1, Stance.SLY: 0.2},
    Character.SHEIK:      {Stance.ATTACK: 1.4, Stance.ROGUE: 0.9, Stance.SLY: 0.2},
    Character.MARTH:     {Stance.ATTACK: 0.9, Stance.DEFENCE: 0.7, Stance.SLY: 0.4, Stance.ROGUE: 0.6},
    Character.ROY:        {Stance.ATTACK: 1.2, Stance.ROGUE: 0.7, Stance.DEFENCE: 0.3},
    Character.DOC:        {Stance.ATTACK: 1.1, Stance.SLY: 0.4, Stance.ROGUE: 0.5},
    Character.MARIO:      {Stance.ATTACK: 1.1, Stance.SLY: 0.3, Stance.ROGUE: 0.5},
    Character.LUIGI:      {Stance.ROGUE: 1.2, Stance.ATTACK: 0.9, Stance.SLY: 0.2},
    Character.DK:         {Stance.ATTACK: 1.0, Stance.SLY: 0.3, Stance.ROGUE: 0.6},
    Character.BOWSER:     {Stance.ATTACK: 0.7, Stance.DEFENCE: 0.6, Stance.SLY: 0.3},
    Character.GANONDORF:   {Stance.SLY: 0.7, Stance.ATTACK: 0.6, Stance.DEFENCE: 0.4},
    Character.POPO:       {Stance.ROGUE: 1.3, Stance.ATTACK: 0.7, Stance.SLY: 0.3},
    Character.NANA:       {Stance.ROGUE: 1.3, Stance.ATTACK: 0.7, Stance.SLY: 0.3},
    Character.JIGGLYPUFF: {Stance.SLY: 0.9, Stance.ROGUE: 0.7, Stance.DEFENCE: 0.4},
    Character.KIRBY:      {Stance.SLY: 0.7, Stance.ROGUE: 0.7, Stance.ATTACK: 0.5},
    Character.PEACH:      {Stance.SLY: 0.6, Stance.ROGUE: 0.6, Stance.DEFENCE: 0.3},
    Character.SAMUS:      {Stance.ATTACK: 0.7, Stance.SLY: 0.5, Stance.ROGUE: 0.5},
    Character.LINK:       {Stance.ATTACK: 0.8, Stance.SLY: 0.4, Stance.ROGUE: 0.5},
    Character.YLINK:      {Stance.ROGUE: 0.8, Stance.ATTACK: 0.7, Stance.SLY: 0.3},
    Character.YOSHI:      {Stance.ROGUE: 0.8, Stance.SLY: 0.6, Stance.ATTACK: 0.4},
    Character.PIKACHU:     {Stance.ATTACK: 1.0, Stance.ROGUE: 0.8, Stance.SLY: 0.2},
    Character.PICHU:       {Stance.ATTACK: 1.2, Stance.ROGUE: 0.7, Stance.SLY: 0.1},
    Character.GAMEANDWATCH: {Stance.ROGUE: 0.8, Stance.ATTACK: 0.6, Stance.SLY: 0.4},
    Character.NESS:       {Stance.ROGUE: 1.0, Stance.ATTACK: 0.6, Stance.SLY: 0.3},
    Character.MEWTWO:     {Stance.ROGUE: 0.7, Stance.SLY: 0.5, Stance.ATTACK: 0.4},
}


# --------------------------------------------------------------------------
# Detection helpers (shared by behaviours)
# --------------------------------------------------------------------------

_SHIELD_ACTIONS = frozenset({
    Action.SHIELD, Action.SHIELD_START, Action.SHIELD_STUN, Action.SHIELD_REFLECT,
})
_LANDING_LAG_ACTIONS = frozenset({
    Action.LANDING, Action.LANDING_SPECIAL, Action.NAIR_LANDING, Action.FAIR_LANDING,
    Action.BAIR_LANDING, Action.UAIR_LANDING, Action.DAIR_LANDING,
})
_TECH_MISS_ACTIONS = frozenset({
    Action.TECH_MISS_UP, Action.TECH_MISS_DOWN,
})


def is_shielding(player) -> bool:
    return player.action in _SHIELD_ACTIONS


def in_landing_lag(player) -> bool:
    return player.action in _LANDING_LAG_ACTIONS or player.action in _TECH_MISS_ACTIONS


def in_punish_state(player) -> bool:
    """The opponent whiffed/got hit and is temporarily unable to act."""
    return (
        player.hitstun_frames_left > 0
        or player.hitlag_left > 0
        or in_landing_lag(player)
    )


# All grounded / aerial physical attacks. Specials (neutral-B, side-B, up-B)
# are excluded for simplicity — most are reactable and projectile-based.
_ATTACK_ACTIONS = frozenset({
    Action.NEUTRAL_ATTACK_1, Action.NEUTRAL_ATTACK_2, Action.NEUTRAL_ATTACK_3,
    Action.LOOPING_ATTACK_START, Action.LOOPING_ATTACK_MIDDLE, Action.LOOPING_ATTACK_END,
    Action.DASH_ATTACK,
    Action.FTILT_HIGH, Action.FTILT_HIGH_MID, Action.FTILT_MID, Action.FTILT_LOW_MID, Action.FTILT_LOW,
    Action.UPTILT, Action.DOWNTILT,
    Action.FSMASH_HIGH, Action.FSMASH_MID_HIGH, Action.FSMASH_MID, Action.FSMASH_MID_LOW, Action.FSMASH_LOW,
    Action.UPSMASH, Action.DOWNSMASH,
    Action.NAIR, Action.FAIR, Action.BAIR, Action.UAIR, Action.DAIR,
})


def is_attacking(player) -> bool:
    """True if the opponent is in an active physical-attack animation."""
    return player.action in _ATTACK_ACTIONS


def is_off_stage(player) -> bool:
    return bool(getattr(player, "off_stage", False)) or (
        not player.on_ground and player.position.y < -5 and abs(player.position.x) > STAGE_HALF_WIDTH - 10
    )


# --------------------------------------------------------------------------
# Stance selection
# --------------------------------------------------------------------------

def select_stance(bot, me, opp, gamestate) -> Stance:
    """Pick the active stance for this frame.

    Combines the character's static disposition weights with situation
    modifiers, zeroes STANDOFF unless it's both useful and safe, and locks the
    result for ``STANCE_LOCK_FRAMES`` frames to keep the bot from thrashing.
    """
    # Persist the current stance until its lock expires.
    if (
        bot._stance is not None
        and gamestate.frame < bot._stance_lock_until
    ):
        return bot._stance

    if opp is None:
        # Fallback: persist what we have, or ATTACK.
        chosen = bot._stance or Stance.ATTACK
        return chosen

    weights = dict(CHARACTER_DISPOSITION.get(me.character, {Stance.ATTACK: 1.0}))

    # --- Situation modifiers --------------------------------------------------
    distance = gamestate.distance or 0.0
    stock_diff = me.stock - opp.stock        # + ahead, - behind
    their_pct = opp.percent
    our_pct = me.percent

    # Behind on stocks -> chase a comeback, never camp.
    if stock_diff < 0:
        weights[Stance.ATTACK] = weights.get(Stance.ATTACK, 0) + 0.9
        weights[Stance.ROGUE] = weights.get(Stance.ROGUE, 0) + 0.5
        weights[Stance.STANDOFF] = 0.0

    # Ahead on stocks -> safe/bait play; STANDOFF becomes possible (if proj).
    if stock_diff > 0:
        weights[Stance.SLY] = weights.get(Stance.SLY, 0) + 0.5
        weights[Stance.DEFENCE] = weights.get(Stance.DEFENCE, 0) + 0.3

    # They're at kill % -> press for the kill.
    if their_pct >= KILL_HEALTH:
        weights[Stance.ATTACK] = weights.get(Stance.ATTACK, 0) + 0.7
        weights[Stance.SLY] = weights.get(Stance.SLY, 0) + 0.2

    # Opponent off-stage -> edgeguard bias (SLY is our edgeguarder).
    if is_off_stage(opp) and not is_off_stage(me):
        weights[Stance.SLY] = weights.get(Stance.SLY, 0) + 1.5
        weights[Stance.ATTACK] = weights.get(Stance.ATTACK, 0) + 0.2

    # --- Health is really bad -> stall with STANDOFF + SLY, never rush -----
    # At kill % we strip rushdown (ATTACK/ROGUE) and "wall" DEFENCE in favour
    # of stalling / zoning. STANDOFF and SLY are forced to parity so projectile
    # chars do BOTH (the brief asks for "standoff and sly"); non-projectile
    # chars will simply lose STANDOFF at the gate below and fall back to SLY.
    if our_pct >= KILL_HEALTH:
        weights[Stance.STANDOFF] = max(weights.get(Stance.STANDOFF, 0.0), 1.5)
        weights[Stance.SLY] = max(weights.get(Stance.SLY, 0.0), 1.5)
        weights[Stance.ATTACK] = max(0.0, weights.get(Stance.ATTACK, 0.0) - 0.8)
        weights[Stance.ROGUE] = max(0.0, weights.get(Stance.ROGUE, 0.0) - 0.6)
        weights[Stance.DEFENCE] = max(0.0, weights.get(Stance.DEFENCE, 0.0) - 0.4)

    # --- Nothing is happening -> default to ATTACK ----------------------
    # A neutral game (even stocks, no one in kill range, opp on-stage, not
    # already in striking range) means ATTACK is the floor -- a character's
    # disposition still nudges toward an archetype, but it can't overrule
    # "mover toward the opponent" when nothing situational is happening.
    nothing_happening = (
        abs(stock_diff) == 0
        and our_pct < KILL_HEALTH
        and their_pct < KILL_HEALTH
        and not (is_off_stage(opp) and not is_off_stage(me))
        and distance > ATTACK_RANGE
    )
    if nothing_happening:
        top = max(weights.values(), default=0.0)
        weights[Stance.ATTACK] = max(weights.get(Stance.ATTACK, 0.0), top + 0.35)

    # Within attack range -> never STANDOFF (you can't camp at point-blank).
    if distance <= ATTACK_RANGE:
        weights[Stance.STANDOFF] = 0.0

    # --- STANDOFF gate ("preferably not often") -------------------------------
    # STANDOFF is allowed when the character has a projectile AND there's
    # room to zone AND one of these survival-camp conditions holds: we're
    # ahead on stocks, the opponent is at kill % (force the approach), our
    # % is very low (we can afford to camp), OR our % is really bad (camp to
    # stall the stock -- the "health is really bad" escape valve).
    standoff_ok = (
        me.character in HAS_PROJECTILE
        and distance > STANDOFF_MIN_RANGE
        and (stock_diff > 0 or their_pct >= 80 or our_pct <= 30 or our_pct >= KILL_HEALTH)
    )
    if not standoff_ok:
        weights[Stance.STANDOFF] = 0.0
    else:
        # Gate allows STANDOFF. Keep a small baseline so the option is
        # actually pickable (without one, no weight means no chance -- the
        # disposition table omits STANDOFF by design). The bad-health boost
        # upstream already loaded the weight; the higher cap here lets it ride
        # at parity with SLY, while normal situations stay "preferably not
        # often" with a modest 0.35 baseline.
        cap = 1.5 if our_pct >= KILL_HEALTH else 0.5
        baseline = 0.35
        weights[Stance.STANDOFF] = max(baseline, min(weights.get(Stance.STANDOFF, 0.0), cap))

    # --- Choose ---------------------------------------------------------------
    nonzero = {s: w for s, w in weights.items() if w > 0}
    if not nonzero:
        chosen = Stance.ATTACK
    else:
        # Weighted random with a small jitter so the bot isn't 100% deterministic
        # given identical situations. Mostly picks the argmax.
        if random.random() < 0.10:
            # Explore: weighted-random pick across all nonzero stances.
            total = sum(nonzero.values())
            r = random.random() * total
            acc = 0.0
            for s, w in nonzero.items():
                acc += w
                if r <= acc:
                    chosen = s
                    break
            else:
                chosen = max(nonzero, key=nonzero.get)
        else:
            # Exploit: take the highest-weight stance. If several stances tie
            # for the top weight (e.g. STANDOFF and SLY both forced to parity
            # when health is really bad), pick randomly among them so the bot
            # actually oscillates between the tied archetypes instead of
            # defaulting to whichever happens to iterate first in the dict.
            top = max(nonzero.values())
            winners = [s for s, w in nonzero.items() if abs(w - top) < 0.05]
            chosen = random.choice(winners) if len(winners) > 1 else winners[0]

    bot._stance = chosen
    bot._stance_lock_until = gamestate.frame + STANCE_LOCK_FRAMES
    return chosen


# --------------------------------------------------------------------------
# Behaviour implementations
# --------------------------------------------------------------------------
# Movement is delegated to ``movement.move(bot, me, opp, gamestate, onleft,
# intent)`` which writes the MAIN stick (and jump/shield on escapes/chases)
# while enforcing ledge safety and platform navigation. Each behaviour layers
# its attack buttons (A / Z / B / c-stick) on top of the navigation inputs.

def _ctrl(bot):
    return bot.controller


def _toward(onleft: bool) -> float:
    return 1.0 if onleft else 0.0


def _away(onleft: bool) -> float:
    return 0.0 if onleft else 1.0


# ---- Behaviours ----------------------------------------------------------

def behave_attack(bot, me, opp, gamestate, onleft, distance):
    """Rushdown: move toward the opponent (chasing to platforms) and hit.

    Aggressive short-hop aerial approaches, fast-fall aerials, and
    mixups. Still defends reactively — if the opponent is in an active
    attack animation and we're in their range, we shield instead of
    eating the hit.
    """
    c = _ctrl(bot)
    if distance > APPROACH_RANGE:
        # Far -> aggressive chase with more short-hop aerial approaches.
        # Mix in short-hop aerials 30% of the time when not elevated.
        opp_elevated = opp is not None and opp.position.y > me.position.y + mv.ELEVATED_ABOVE
        if random.random() < 0.30 and me.on_ground and not opp_elevated:
            mv.move(bot, me, opp, gamestate, onleft, "chase")
            c.press_button(Button.BUTTON_X)  # short hop
            return
        mv.move(bot, me, opp, gamestate, onleft, "chase")
        c.release_button(Button.BUTTON_A)
        c.release_button(Button.BUTTON_B)
        return
    if distance > ATTACK_RANGE:
        # Closing the gap -- more aerial approaches for fancy movement.
        opp_elevated = opp is not None and opp.position.y > me.position.y + mv.ELEVATED_ABOVE
        roll = random.random()
        if roll < 0.40 and me.on_ground and not opp_elevated:
            # Short-hop aerial approach -- nair/fair/bair mixup.
            mv.move(bot, me, opp, gamestate, onleft, "chase")
            c.press_button(Button.BUTTON_X)  # short hop
            return
        elif roll < 0.55 and me.on_ground and not opp_elevated:
            # Tomahawk: short-hop then empty land into grab.
            mv.move(bot, me, opp, gamestate, onleft, "chase")
            c.press_button(Button.BUTTON_X)  # jump, will land and grab next
            return
        mv.move(bot, me, opp, gamestate, onleft, "chase")
        c.release_button(Button.BUTTON_A)
        return
    # In striking range.
    # Reactive defence: the opponent is throwing a hitbox and we're close
    # enough to get clipped -- shield rather than trade.
    if is_attacking(opp) and distance < mv.THREAT_RANGE:
        # Out of shield: shield then jump-cancel into aerial or grab.
        roll = random.random()
        if roll < 0.35:
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.press_button(Button.BUTTON_R)  # shield the hit
            return
        elif roll < 0.60:
            # OOS option: jump out of shield into aerial.
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.press_button(Button.BUTTON_X)  # jump OOS
            return
        # Or just shield.
        mv.move(bot, me, opp, gamestate, onleft, "hold")
        c.press_button(Button.BUTTON_R)
        return
    if is_shielding(opp):
        # Opponent shielding -- mix between grab, tomahawk, and pressure.
        roll = random.random()
        if roll < 0.50:
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.press_button(Button.BUTTON_Z)   # grab the shield
        elif roll < 0.70 and me.on_ground:
            # Shield pressure: short hop aerial on their shield.
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.press_button(Button.BUTTON_X)  # short hop for aerial pressure
        else:
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.tilt_analog(Button.BUTTON_C, _toward(onleft), 0.5)  # f-smash pressure
        return
    if not me.on_ground:
        # Airborne -- use c-stick for directional aerials, fast-fall.
        roll = random.random()
        if roll < 0.30:
            c.tilt_analog(Button.BUTTON_C, _toward(onleft), 1.0)  # fair (forward)
        elif roll < 0.55:
            c.tilt_analog(Button.BUTTON_C, _away(onleft), 1.0)   # bair (behind)
        elif roll < 0.70:
            c.tilt_analog(Button.BUTTON_C, 0.5, 1.0)             # uair (up)
        else:
            c.tilt_analog(Button.BUTTON_C, 0.5, 0.0)             # dair (down)
        # Fast-fall after aerial hits.
        if getattr(me, 'speed_y_self', 0.0) > 0:
            c.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.0)  # hold down to fast-fall
        return
    # Grounded -- mix between jab, tilt, smash, and dash attack.
    roll = random.random()
    if roll < 0.25:
        c.press_button(Button.BUTTON_A)  # jab
    elif roll < 0.45:
        # Up-tilt for anti-air / combo starter.
        c.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.8)  # tilt up
        c.press_button(Button.BUTTON_A)
    elif roll < 0.60:
        # Down-tilt for poke.
        c.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.2)  # tilt down
        c.press_button(Button.BUTTON_A)
    elif roll < 0.75:
        # C-stick aerial approach -- forward smash or dash attack.
        c.tilt_analog(Button.BUTTON_C, _toward(onleft), 0.5)
    elif roll < 0.88:
        # Dash attack for burst movement.
        c.tilt_analog(Button.BUTTON_MAIN, _toward(onleft), 0.5)
        c.press_button(Button.BUTTON_A)
    else:
        # Full smash attack -- commit to the kill.
        c.tilt_analog(Button.BUTTON_C, _toward(onleft), 1.0)  # c-stick full tilt = f-smash


def behave_defence(bot, me, opp, gamestate, onleft, distance):
    """Proactive defence with aggressive counter-attacks. Shields within the
    threat range *whether or not the opponent is attacking*, then punishes
    whiffs with varied options. Flashier out-of-shield and spacing tools."""
    c = _ctrl(bot)
    # Punish window: opponent is in hitlag/landing -> commit to a punish.
    if in_punish_state(opp) and distance < SPACING_RANGE * 1.5:
        roll = random.random()
        if roll < 0.30:
            # F-smash punish.
            mv.move(bot, me, opp, gamestate, onleft, "approach_walk")
            c.tilt_analog(Button.BUTTON_C, _toward(onleft), 1.0)
        elif roll < 0.50 and me.on_ground:
            # Grab punish.
            mv.move(bot, me, opp, gamestate, onleft, "approach_walk")
            c.press_button(Button.BUTTON_Z)
        elif roll < 0.70:
            # Dash attack.
            mv.move(bot, me, opp, gamestate, onleft, "approach")
            c.press_button(Button.BUTTON_A)
        else:
            # Tilt or aerial punish.
            mv.move(bot, me, opp, gamestate, onleft, "approach_walk")
            if me.on_ground:
                c.tilt_analog(Button.BUTTON_MAIN, _toward(onleft), 0.5)
                c.press_button(Button.BUTTON_A)  # f-tilt
            else:
                c.tilt_analog(Button.BUTTON_C, _toward(onleft), 1.0)  # aerial
        return
    # Within the threat range -> defend proactively (shield / spot-dodge / roll).
    # This is "regardless if attacks are coming your way" — we guard by default
    # whenever the opponent can hit us, whether or not we see an attack.
    if distance < mv.THREAT_RANGE:
        # Mix between pure defend and OOS counter-attack.
        roll = random.random()
        if roll < 0.65:
            mv.defend(bot, me, opp, gamestate, onleft, distance)
        elif roll < 0.80 and me.on_ground:
            # OOS option: jump out of shield then aerial.
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.press_button(Button.BUTTON_X)  # jump OOS
        else:
            # Shield grab.
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.press_button(Button.BUTTON_Z)
        return
    # At poke range -> varied pokes: f-tilt, d-tilt, or short-hop aerial.
    if distance <= SPACING_RANGE * 1.3:
        roll = random.random()
        if roll < 0.45:
            # Standard f-tilt poke.
            mv.move(bot, me, opp, gamestate, onleft, "approach_walk")
            c.press_button(Button.BUTTON_A)
        elif roll < 0.65:
            # D-tilt poke.
            mv.move(bot, me, opp, gamestate, onleft, "approach_walk")
            c.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.2)
            c.press_button(Button.BUTTON_A)
        elif roll < 0.85 and me.on_ground:
            # Short-hop aerial poke.
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.press_button(Button.BUTTON_X)
        else:
            # C-stick fair for spacing.
            mv.move(bot, me, opp, gamestate, onleft, "approach_walk")
            c.tilt_analog(Button.BUTTON_C, _toward(onleft), 0.5)
        return
    # Feast range -> walk cautiously toward to re-engage spacing.
    mv.move(bot, me, opp, gamestate, onleft, "approach_walk")
    c.release_button(Button.BUTTON_A)
    c.release_button(Button.BUTTON_R)


def behave_standoff(bot, me, opp, gamestate, onleft, distance):
    """Zoning from range. Can either hold in place or retreat to the far side
    of the stage; in both modes the goal is to keep the opponent at distance
    so we can throw projectiles. Cornered retreat auto-hops to a platform so
    we keep zoning from higher ground instead of walking off the stage."""
    c = _ctrl(bot)
    # Too close -- retreat (escape_up if cornered) and shield defensively.
    if distance < STANDOFF_MIN_RANGE * 0.6:
        mv.move(bot, me, opp, gamestate, onleft, "retreat")
        c.press_button(Button.BUTTON_R)
        c.release_button(Button.BUTTON_B)
        return

    # Decide whether to hold in place (already far enough) or walk further to
    # the opposite side of the stage for more breathing room.
    holding = False
    if distance >= STANDOFF_MIN_RANGE * 1.1:
        # Already at a comfortable distance -- just stand still and zone.
        mv.move(bot, me, opp, gamestate, onleft, "hold")
        holding = True
    else:
        left_safe, right_safe = mv.stage_bounds(gamestate)
        want_x = left_safe if opp.position.x > 0 else right_safe
        if abs(me.position.x - want_x) > 6:
            # Walk (not dash) to the far side so we can stop precisely.
            # ``onleft`` = me is to the left of the target -> walk right.
            onleft_want = me.position.x < want_x
            mv.move(bot, me, opp, gamestate, onleft_want, "approach_walk")
        else:
            # At the far slice -- stop and zone from here.
            c.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.5)
            holding = True

    # Layer projectiles on top of the hold-position movement. ``move('hold')``
    # leaves MAIN near-neutral which is what neutral-B wants; when walking we
    # skip the projectile this frame to preserve the walk input.
    if holding:
        if (gamestate.frame - getattr(bot, "_last_projectile_frame", -999)) > STANDOFF_PROJECTILE_EVERY:
            c.press_button(Button.BUTTON_B)
            bot._last_projectile_frame = gamestate.frame
        else:
            c.release_button(Button.BUTTON_B)
    else:
        c.release_button(Button.BUTTON_B)


def behave_rogue(bot, me, opp, gamestate, onleft, distance):
    """Flashy dash-dance, cross-ups, tomahawk grabs, and aerial mixups.
    Moves toward the opponent with unpredictable rhythm."""
    c = _ctrl(bot)
    toward_dir = 1 if onleft else -1
    # In range -> grab, cross-up, or pressure with aerials.
    if distance <= ATTACK_RANGE * 1.2:
        # Reactive defence: shield incoming attacks even while rushing.
        if is_attacking(opp) and distance < mv.THREAT_RANGE:
            # OOS option: shield or jump OOS.
            if random.random() < 0.5:
                mv.move(bot, me, opp, gamestate, onleft, "hold")
                c.press_button(Button.BUTTON_R)
            else:
                mv.move(bot, me, opp, gamestate, onleft, "hold")
                c.press_button(Button.BUTTON_X)  # jump OOS
            return
        if is_shielding(opp):
            # Shielded opponent -> grab (tomahawk) or shield pressure.
            roll = random.random()
            if roll < 0.55:
                mv.move(bot, me, opp, gamestate, onleft, "hold")
                c.press_button(Button.BUTTON_Z)  # grab the shield
            elif roll < 0.75 and me.on_ground:
                # Tomahawk: empty land grab.
                mv.move(bot, me, opp, gamestate, onleft, "hold")
                c.press_button(Button.BUTTON_Z)
            else:
                mv.move(bot, me, opp, gamestate, onleft, "hold")
                c.press_button(Button.BUTTON_X)  # short hop aerial on shield
            return
        # In range -- mix between grab, aerial, and smash.
        roll = random.random()
        if roll < 0.30:
            # Grab (tomahawk or grounded).
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.press_button(Button.BUTTON_Z)
        elif roll < 0.55 and me.on_ground:
            # Cross-up: jump over and aerial behind them.
            mv.move(bot, me, opp, gamestate, onleft, "chase")
            c.press_button(Button.BUTTON_X)
        elif roll < 0.75:
            # Aerial pressure -- c-stick directionals.
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            if not me.on_ground:
                c.tilt_analog(Button.BUTTON_C, _toward(onleft), 1.0)  # fair
            else:
                c.press_button(Button.BUTTON_X)  # short hop into aerial
        else:
            # Smash attack commitment.
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.tilt_analog(Button.BUTTON_C, _toward(onleft), 1.0)  # f-smash
        return
    # Mid/far -> fancy dash-dance: variable rhythm to look tricky,
    # but never dash off the stage. Mix in short hops and wavedash-like
    # approaches for flashier movement.
    roll = random.random()
    if roll < 0.15 and me.on_ground:
        # Short-hop aerial approach.
        mv.move(bot, me, opp, gamestate, onleft, "chase")
        c.press_button(Button.BUTTON_X)  # short hop
    elif roll < 0.30 and me.on_ground:
        # Burst dash attack.
        mv.move(bot, me, opp, gamestate, onleft, "approach")
        c.press_button(Button.BUTTON_A)  # dash attack
    else:
        # Variable-rhythm dash-dance.
        phase = (gamestate.frame // 5) % 3  # 3-phase rhythm
        if phase == 0 or mv.near_ledge(me, gamestate, -toward_dir):
            c.tilt_analog(Button.BUTTON_MAIN, _toward(onleft), 0.5)
        elif phase == 1:
            c.tilt_analog(Button.BUTTON_MAIN, _away(onleft), 0.5)
        else:
            c.tilt_analog(Button.BUTTON_MAIN, _toward(onleft), 0.5)  # double back
    c.release_button(Button.BUTTON_A)
    c.release_button(Button.BUTTON_Z)


def behave_sly(bot, me, opp, gamestate, onleft, distance):
    """Flashy bait-and-punish with varied edgeguards and aerial combos.
    Hovers just outside opponent's range, then commits to fancy punishes."""
    c = _ctrl(bot)
    # Edgeguard: opponent off-stage -> go to their ledge side and poke.
    if is_off_stage(opp) and not is_off_stage(me):
        # Position at the ledge on the opponent's side, then throw a poke.
        left_safe, right_safe = mv.stage_bounds(gamestate)
        ledge_x = right_safe if opp.position.x > 0 else left_safe
        if abs(me.position.x - ledge_x) > 4:
            onleft_ledge = me.position.x < ledge_x
            mv.move(bot, me, opp, gamestate, onleft_ledge, "approach")
            return
        # At the ledge: varied edgeguard options for fanciness.
        roll = random.random()
        if opp.position.y > -10:
            # Opponent is high -> up-smash, up-tilt, or short-hop up-air.
            if roll < 0.35:
                c.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.5)
                c.tilt_analog(Button.BUTTON_C, 0.5, 1.0)  # up-smash
            elif roll < 0.65:
                c.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.8)  # tilt up
                c.press_button(Button.BUTTON_A)  # up-tilt
            else:
                c.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.5)
                c.press_button(Button.BUTTON_X)  # short hop for up-air
        else:
            # Opponent is low -> d-tilt, down-smash, or run-off fair.
            if roll < 0.40:
                c.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.0)
                c.press_button(Button.BUTTON_A)  # d-tilt
            elif roll < 0.70:
                c.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.0)
                c.tilt_analog(Button.BUTTON_C, 0.5, 0.0)  # down-smash
            else:
                # Run off stage with a fair (risky but flashy).
                mv.move(bot, me, opp, gamestate, onleft_ledge, "approach")
                c.press_button(Button.BUTTON_X)  # jump off for aerial
        return

    # Punish: opponent committed and is in hitlag / landing lag -> commit hard.
    if in_punish_state(opp) and distance < SPACING_RANGE * 1.5:
        roll = random.random()
        if roll < 0.40:
            # Full commit: c-stick smash.
            mv.move(bot, me, opp, gamestate, onleft, "approach")
            c.tilt_analog(Button.BUTTON_C, _toward(onleft), 1.0)  # f-smash
        elif roll < 0.65 and me.on_ground:
            # Tomahawk grab punish.
            mv.move(bot, me, opp, gamestate, onleft, "approach")
            c.press_button(Button.BUTTON_Z)
        elif roll < 0.85:
            # Aerial punish -- short hop into c-stick aerial.
            mv.move(bot, me, opp, gamestate, onleft, "chase")
            c.press_button(Button.BUTTON_X)  # jump
        else:
            # Dash attack burst.
            mv.move(bot, me, opp, gamestate, onleft, "approach")
            c.press_button(Button.BUTTON_A)
        return

    # Shielded opponent -> grab mix-up or retreat with aerial.
    if is_shielding(opp) and distance < SPACING_RANGE:
        roll = random.random()
        if roll < 0.45:
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.press_button(Button.BUTTON_Z)  # grab
        elif roll < 0.70 and me.on_ground:
            # Short hop aerial on shield for pressure.
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.press_button(Button.BUTTON_X)
        else:
            mv.move(bot, me, opp, gamestate, onleft, "retreat")
        return

    # Bait at just-outside range: hover at SPACING_RANGE*1.2. SLY "can do both"
    # (advance or retreat); movement.move handles ledge clamps + escape_up.
    desired = SPACING_RANGE * 1.2
    if distance < desired * 0.85:
        mv.move(bot, me, opp, gamestate, onleft, "retreat")
    elif distance > desired * 1.15:
        # Approaching -- mix in aerials for fancier movement.
        if random.random() < 0.25 and me.on_ground:
            mv.move(bot, me, opp, gamestate, onleft, "chase")
            c.press_button(Button.BUTTON_X)  # short hop approach
        else:
            mv.move(bot, me, opp, gamestate, onleft, "approach_walk")
    else:
        # In range -- subtle bait and punish.
        if random.random() < 0.15:
            # Quick jab or tilt to bait a reaction.
            mv.move(bot, me, opp, gamestate, onleft, "hold")
            c.press_button(Button.BUTTON_A)
        else:
            mv.move(bot, me, opp, gamestate, onleft, "hold")
    c.release_button(Button.BUTTON_A)
    c.release_button(Button.BUTTON_Z)


_DISPATCH = {
    Stance.ATTACK: behave_attack,
    Stance.DEFENCE: behave_defence,
    Stance.STANDOFF: behave_standoff,
    Stance.ROGUE: behave_rogue,
    Stance.SLY: behave_sly,
}


def behave(bot, stance, me, opp, gamestate, onleft, distance):
    fn = _DISPATCH[stance]
    fn(bot, me, opp, gamestate, onleft, distance)