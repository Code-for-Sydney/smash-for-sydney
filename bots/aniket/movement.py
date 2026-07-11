"""Stage-aware movement for AniketBot.

The stance machine in ``stances.py`` decides *what* to do (approach, retreat,
hold, chase, escape). This module decides *how* the stick and jump buttons
should be pressed to achieve that intent without killing the bot.

Two hard rules, both required by the bot brief:

1. **Don't walk off the map.** Every legal stage exposes its teeter x via
   ``melee.stages.EDGE_GROUND_POSITION``. We keep a safe margin inside that
   line and clamp any intent that would push us past it. Platform
   drop-throughs are exempt -- a falling platform drop always lands back on
   the main stage floor (every platform is inset within the stage x-range),
   so "falling from platforms is OK, falling from the map is not" is
   enforced structurally.
2. **Use platforms deliberately** -- to escape a corner (go up), to gain
   higher ground (DEFENCE / STANDOFF), to chase (ATTACK), or to reset
   spacing (SLY drop-through). Platform geometry is read from
   ``melee.stages`` (top + both sides per stage); FoD's moving side
   platforms are a known TODO upstream so we only use its static top.

Recovery (actually being off-stage and below the floor) is *not* handled
here -- it's the override in ``AniketBot._recover`` that fires once
``is_off_stage`` is already true. This layer's job is to keep us from
reaching that state during normal play.
"""
import random
from typing import List, Optional, Tuple

import melee
from melee import stages
from melee.enums import Button


# Tuning ------------------------------------------------------------
SAFE_MARGIN = 8.0          # stay this far inside the teeter x on each side
LEDGE_WARN_MARGIN = 12.0   # within this of the safe line => consider us cornered
PLATFORM_Y_TOLERANCE = 5.0 # |dy| to count "standing on" a platform
JUMP_DRIFT_TOWARD = 0.4    # main-stick offset from 0.5 for air-drift (in [0, 0.5])
ELEVATED_ABOVE = 8.0       # opp y above me y by this many units => opp is "up there"
JUMP_APEX_SPEED_Y = 0.0    # me.speed_y_self <= this => at/below the apex (time to double jump)
THREAT_RANGE = 22.0       # within this, the opponent can reach us with a hit
SPOTDODGE_PROB = 0.18      # per-frame chance to spot-dodge while defending
ROLL_PROB = 0.10           # per-frame chance to roll away while shielding

Platform = Tuple[float, float, float, str]   # (height, left_x, right_x, name)
PlatList = List[Platform]


# ---------------------------------------------------------------- stage geometry

def stage_bounds(gamestate) -> Tuple[float, float]:
    """(left_safe_x, right_safe_x) -- safe ground x range for this stage.

    Falls back to a conservative default if the stage is unmapped.
    """
    stage = getattr(gamestate, "stage", None)
    try:
        edge = stages.EDGE_GROUND_POSITION[stage]
    except (KeyError, AttributeError, TypeError):
        edge = 80.0
    return (-edge + SAFE_MARGIN, edge - SAFE_MARGIN)


def platforms(gamestate) -> PlatList:
    """All static platforms on this stage as (height, left_x, right_x, name).

    FoD's moving side platforms aren't exposed by libmelee (TODO upstream),
    so for FoD we return only its top platform.
    """
    stage = getattr(gamestate, "stage", None)
    out: PlatList = []
    try:
        h, l, r = stages.top_platform_position(stage)
        if h is not None:
            out.append((float(h), float(l), float(r), "top"))
        h, l, r = stages.left_platform_position(stage)
        if h is not None:
            out.append((float(h), float(l), float(r), "left"))
        h, l, r = stages.right_platform_position(stage)
        if h is not None:
            out.append((float(h), float(l), float(r), "right"))
    except (KeyError, AttributeError, TypeError):
        pass
    return out


def on_platform(player, plat: Platform) -> bool:
    """True if ``player`` is currently standing on ``plat``."""
    h, l, r, _ = plat
    return bool(
        getattr(player, "on_ground", True)
        and abs(player.position.y - h) <= PLATFORM_Y_TOLERANCE
        and (l - 2) <= player.position.x <= (r + 2)
    )


def platform_under(me, plats: PlatList) -> Optional[Platform]:
    """The platform whose top is above us and roughly overhead (for escape_up)."""
    cand = [p for p in plats if p[0] > me.position.y + 3]
    if not cand:
        return None
    # nearest by (horizontal distance to platform centre, then lowest height)
    return min(cand, key=lambda p: (abs((p[1] + p[2]) / 2.0 - me.position.x), p[0]))


def platform_above_opponent(opp, plats: PlatList) -> Optional[Platform]:
    """The platform the opponent is standing on, if any."""
    for p in plats:
        if on_platform(opp, p):
            return p
    return None


# ---------------------------------------------------------------- ledge helpers

def near_ledge(me, gamestate, direction: int) -> bool:
    """``direction`` +1 = moving right, -1 = moving left.

    True if moving that way would push us past the safe line (we are at the
    edge in that direction).
    """
    left_safe, right_safe = stage_bounds(gamestate)
    if direction > 0:
        return me.position.x >= right_safe - LEDGE_WARN_MARGIN
    else:
        return me.position.x <= left_safe + LEDGE_WARN_MARGIN


def cornered(me, gamestate, away_dir: int) -> bool:
    """True if retreating in ``away_dir`` would walk us off (ledge behind us)."""
    return near_ledge(me, gamestate, away_dir)


# ---------------------------------------------------------------- primitives

def _ctrl(bot):
    return bot.controller


def _dash_toward(bot, onleft: bool):
    _ctrl(bot).tilt_analog(Button.BUTTON_MAIN, 1.0 if onleft else 0.0, 0.5)


def _walk_toward(bot, onleft: bool, intensity: float = 0.35):
    """Gentle walk (not dash) -- enables f-tilt, careful spacing.
    ``intensity`` is the offset from neutral; capped at 0.5 so the stick stays
    in [0, 1] (a full 0.5 offset would already be a dash)."""
    offset = max(0.0, min(0.5, intensity))
    tilt = offset * (1.0 if onleft else -1.0)
    _ctrl(bot).tilt_analog(Button.BUTTON_MAIN, 0.5 + tilt, 0.5)


def _retreat(bot, onleft: bool):
    _ctrl(bot).tilt_analog(Button.BUTTON_MAIN, 0.0 if onleft else 1.0, 0.5)


def _hold(bot, me, gamestate):
    """Near-neutral stick, clamped inside the safe line."""
    left_safe, right_safe = stage_bounds(gamestate)
    x = max(left_safe, min(right_safe, me.position.x))
    # tiny inward bias so we don't idle right at the teeter
    if me.position.x > 0:
        bias = -0.02
    else:
        bias = 0.02
    _ctrl(bot).tilt_analog(Button.BUTTON_MAIN, 0.5 + bias, 0.5)


def _jump(bot):
    _ctrl(bot).press_button(Button.BUTTON_X)


def _can_double_jump(me) -> bool:
    """True if we are airborne, still hold a jump, and have begun to fall.

    Waiting for the first jump's apex before firing the second one keeps both
    jumps from being burned on adjacent frames (you get full height out of the
    first before adding the second).
    """
    return (
        not getattr(me, "on_ground", True)
        and getattr(me, "jumps_left", 0) > 0
        and getattr(me, "speed_y_self", 0.0) <= JUMP_APEX_SPEED_Y
    )


def _drift(bot, onleft: bool, intensity: float = JUMP_DRIFT_TOWARD):
    """Air-drift toward a target. ``onleft=True`` means the target is on our
    LEFT, so push the stick left (<0.5)."""
    offset = max(0.0, min(0.5, intensity))
    stick = 0.5 - offset if onleft else 0.5 + offset
    _ctrl(bot).tilt_analog(Button.BUTTON_MAIN, stick, 0.5)


def _drop_through(bot):
    _ctrl(bot).tilt_analog(Button.BUTTON_MAIN, 0.5, 0.0)


def _shield(bot):
    _ctrl(bot).press_button(Button.BUTTON_R)


def _spot_dodge(bot):
    """Spot-dodge: shield + tap down on the MAIN stick (same frame)."""
    c = _ctrl(bot)
    c.press_button(Button.BUTTON_R)
    c.tilt_analog(Button.BUTTON_MAIN, 0.5, 0.0)


def _roll(bot, onleft, forward=True):
    """Roll: shield + tilt MAIN stick in a direction.

    ``forward=True`` rolls toward the opponent; ``False`` rolls away.
    The caller must ensure rolling ``away`` won't carry us off a ledge.
    """
    c = _ctrl(bot)
    c.press_button(Button.BUTTON_R)
    if forward:
        c.tilt_analog(Button.BUTTON_MAIN, 1.0 if onleft else 0.0, 0.5)
    else:
        c.tilt_analog(Button.BUTTON_MAIN, 0.0 if onleft else 1.0, 0.5)


def _air_dodge(bot):
    """Air-dodge: press R while airborne."""
    _ctrl(bot).press_button(Button.BUTTON_R)


# ---------------------------------------------------------------- escape

def escape_up(bot, me, gamestate) -> bool:
    """Jump to the nearest platform above us (using the double jump at the
    apex of the first jump), or shield if there is none.

    Returns True if a jump/shield was issued (caller should not also move).
    """
    plats = platforms(gamestate)
    target = platform_under(me, plats)
    if target is None:
        # No platform to escape to -- shield and hold at the line.
        _shield(bot)
        _hold(bot, me, gamestate)
        return True
    target_top = target[0]
    centre = (target[1] + target[2]) / 2.0
    onleft_plat = centre < me.position.x
    if me.on_ground:
        _jump(bot)
        _drift(bot, onleft_plat)
        return True
    if _can_double_jump(me) and me.position.y < target_top - PLATFORM_Y_TOLERANCE:
        # Ride the first jump to apex, then wax the second to actually reach
        # the platform.
        _jump(bot)
        _drift(bot, onleft_plat)
        return True
    # Already out of jumps, or already over the platform -- keep drifting in.
    _drift(bot, onleft_plat)
    return True


# ---------------------------------------------------------------- dispatcher

def defend(bot, me, opp, gamestate, onleft, distance) -> None:
    """Proactive defensive action within the opponent's threat range.

    Shields by default, with spot-dodge and roll mix-ups to avoid grabs and
    to reposition. Works whether or not the opponent is actively attacking —
    the point is to put up our guard whenever they can reach us, not just
    when we happen to see an attack coming. Airborne calls air-dodge.
    """
    if not me.on_ground:
        if distance < THREAT_RANGE * 0.8:
            _air_dodge(bot)
        else:
            # Far enough in the air -- drift away from the opponent.
            _drift(bot, not onleft, 0.3)
        return

    # Grounded: shield is the default, dice in spot-dodges and rolls.
    roll = random.random()
    if roll < SPOTDODGE_PROB:
        _spot_dodge(bot)
        return
    if roll < SPOTDODGE_PROB + ROLL_PROB:
        away_dir = -1 if onleft else 1   # away from the opponent
        if near_ledge(me, gamestate, away_dir):
            # Rolling away would carry us off -- roll inward instead.
            _roll(bot, onleft, forward=True)
        else:
            _roll(bot, onleft, forward=False)
        return
    _shield(bot)


def move(bot, me, opp, gamestate, onleft: bool, intent: str) -> None:
    """Write movement inputs for the given intent, with ledge + platform safety.

    Intents:
        'approach'       dash toward opp
        'approach_walk'  walk toward opp (for tilts / careful spacing)
        'retreat'        dash away from opp; escape_up if cornered
        'hold'           near-neutral stick at current x (bait)
        'chase'          approach; jump + double-jump toward the opponent
                         (or their platform) whenever they are elevated above
                         us; drop-through when we are above them on a platform
        'escape_up'      jump + double-jump to a platform above; shield if none

    Does not touch attack buttons (A/Z/B/C) -- the stance layers those on top.
    """
    c = _ctrl(bot)
    toward_dir = +1 if onleft else -1

    if intent == "escape_up":
        escape_up(bot, me, gamestate)
        return

    if intent == "hold":
        _hold(bot, me, gamestate)
        return

    if intent == "retreat":
        away_dir = -toward_dir
        if cornered(me, gamestate, away_dir):
            escape_up(bot, me, gamestate)
            return
        _retreat(bot, onleft)
        return

    if intent == "approach":
        if near_ledge(me, gamestate, toward_dir):
            # Don't walk off the stage. Hold at the line.
            _hold(bot, me, gamestate)
            return
        _dash_toward(bot, onleft)
        return

    if intent == "approach_walk":
        if near_ledge(me, gamestate, toward_dir):
            _hold(bot, me, gamestate)
            return
        _walk_toward(bot, onleft)
        return

    if intent == "chase":
        plats = platforms(gamestate)
        opp_plat = platform_above_opponent(opp, plats) if opp is not None else None
        opp_elevated = (
            opp is not None
            and opp.position.y > me.position.y + ELEVATED_ABOVE
        )
        # Opponent above us in any form -- jump up to reach them.
        # * If they're on a platform, drift toward the platform so we land on
        #   it. Otherwise drift toward the opponent's x directly.
        # * Use the double jump at the first jump's apex for full height.
        if opp_elevated:
            if opp_plat is not None:
                tgt_cx = (opp_plat[1] + opp_plat[2]) / 2.0
                tgt_h = opp_plat[0]
            else:
                tgt_cx = opp.position.x
                tgt_h = opp.position.y
            onleft_plat = tgt_cx < me.position.x
            if me.on_ground:
                _jump(bot)
                _drift(bot, onleft_plat)
                return
            if _can_double_jump(me) and me.position.y < tgt_h - PLATFORM_Y_TOLERANCE:
                _jump(bot)
                _drift(bot, onleft_plat)
                return
            _drift(bot, onleft_plat)
            return
        # We are on a platform above the opponent -> drop through to approach.
        my_plat = next((p for p in plats if on_platform(me, p)), None)
        if my_plat is not None and opp is not None and me.position.y > opp.position.y + PLATFORM_Y_TOLERANCE:
            _drop_through(bot)
            return
        # Otherwise: approach on the same level, but never walk off the stage.
        if near_ledge(me, gamestate, toward_dir):
            _hold(bot, me, gamestate)
            return
        _dash_toward(bot, onleft)
        return

    # Unknown intent -- safe default: hold position.
    _hold(bot, me, gamestate)