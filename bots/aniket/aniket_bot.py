"""AniketBot -- a port-agnostic Smash Melee bot built on top of ``bots.bot.Bot``.

Design at a glance
------------------
1. **Roster (the "three characters and stick with it" rule).** At
   construction we sample three distinct libmelee ``Character`` enums from
   the 25 spec-list names (see ``roster.py``). We never play a character
   outside the roster -- we only *rotate within it*.

2. **Port discovery (the "find out if we are player 1 or player 2" rule).**
   libmelee assigns a port to a controller when ``create_controller`` runs
   (see ``fight.py``). Inside ``connect`` we log ``self.port``, which is only
   knowable after that assignment. Every gameplay action uses ``self.port``
   rather than a hard-coded 1 or 2, so the bot works in either slot.

3. **Opponent discovery + collision avoidance (the "let the other bot choose
   first; play a different character" rule).** libmelee exposes no direct
   inter-bot channel -- both bots' ``__init__`` runs before the CSS loads, and
   once in-game it is far too late to swap. However, every frame at the
   character-select screen each player's ``PlayerState`` carries:
       * ``character``  -- the character currently committed at the player's
                           CSS slot (it tracks the cursor before the coin is
                           dropped and locks to the coin's slot afterwards).
       * ``coin_down``  -- True once the player has physically placed their
                           token on a slot.
   ``fight.py`` calls ``MenuHelper.menu_helper_simple`` for each bot each
   frame, passing the bot's ``self.character``. libmelee re-claims our coin
   with B and walks our cursor to our requested slot -- *including after the
   coin is already down*. So the recipe is:
       a) Watch the *other* port's ``coin_down``.
       b) The first frame it is True, read its ``character`` and pick the
          first roster slot whose enum differs.
       c) Reassign ``self.character``. Next frame ``menu_helper_simple`` moves
          us there.
   Because we are the only bot that does this (Example / Masher commit at
   ``__init__`` and never react), we always end up on a different character.
   If the other bot ever also conflict-avoids we could oscillate, but the
   current arena bots don't, so this suffices. ``menu()`` is the per-frame
   hook called by ``fight.py`` immediately before ``menu_helper_simple``.

   **Fallback.** If the opponent never drops their coin within
   ``CSS_TIMEOUT_FRAMES`` (180 frames == 3 seconds at 60 fps) -- e.g. a
   misbehaving opponent or a solo CSS -- AniketBot stops waiting and picks a
   random roster slot, still avoiding the opponent's current cursor character
   if it happens to be sitting on one of ours. The per-visit timeout state
   is reset every time we leave the CSS so each match gets a fresh window.

4. **Gameplay -- stances.** A stance machine (see ``stances.py``) picks one
   of ATTACK | DEFENCE | STANDOFF | ROGUE | SLY per situational context, then
   dispatches to that stance's behaviour function to write controller inputs.
   Recovery (off-stage) overrides the stance machine. Each character's
   disposition toward the five stances is derived from ``characterdata.csv``
   and specified in ``stances.CHARACTER_DISPOSITION``; STANDOFF is gated to be
   rare (only for projectile chars, far range, ahead/low-percent).
"""
import logging
import random
from typing import Optional

import melee
from melee.enums import Button, Menu

from bots.bot import Bot
from .roster import pick_roster, first_slot_away_from, spec_names_for
from .stances import Stance, behave, is_off_stage, select_stance


# Recovery helper tuning (everything else lives in ``stances.py``).
RECOVERY_JUMP_X = 1        # full horizontal tilt toward centre during recovery

# --- CSS fallback tuning ----------------------------------------------------
# Melee runs at 60 fps, so 180 frames == 3 seconds. If the opponent still
# hasn't dropped their coin after this many CSS frames, AniketBot stops
# waiting and picks a random roster slot (still avoiding the opponent's
# current cursor character if it happens to land on one of ours).
CSS_TIMEOUT_FRAMES = 180


class AniketBot(Bot):
    """See module docstring."""

    def __init__(self, character=None):
        # character is *ignored* on purpose -- we pick our own roster.
        self.roster = pick_roster(3)
        super().__init__(self.roster[0])

        # Filled in at known points in the lifecycle.
        self._opponent_port: Optional[int] = None
        self._opponent_character: Optional[melee.Character] = None
        self._committed: bool = False
        self._port_logged: bool = False
        self._opponent_logged: bool = False
        self._repick_logged: bool = False

        # Per-CSS-visit state for the 3-second fallback. Reset every time we
        # leave the character-select screen so each match gets a fresh window.
        self._css_start_frame: Optional[int] = None
        self._fallback_used: bool = False

        # Stance-machine state. The active stance persists for
        # ``stances.STANCE_LOCK_FRAMES`` frames before re-selection.
        self._stance: Optional[Stance] = None
        self._stance_lock_until: int = -1
        self._last_projectile_frame: int = -999
        self._stance_logged: Optional[Stance] = None

        logging.info(
            "AniketBot roster: %s",
            ", ".join(
                f"{c.name} ({'/'.join(spec_names_for(c))})" for c in self.roster
            ),
        )

    # ------------------------------------------------------------------ lifecycle

    def create_controller(self, console, port):
        super().create_controller(console, port)
        logging.info("AniketBot: assigned controller port %d (pre-connect)", self.port)

    def connect(self):
        super().connect()
        # self.port is set by create_controller, so just re-iterate it here.
        logging.info("AniketBot: I am on port %d.", self.port)

    # ------------------------------------------------------------ the menu hook --
    #
    # ``fight.py`` calls this for every player, every frame, *before* it calls
    # ``MenuHelper.menu_helper_simple``. The default ``Bot`` implementation is
    # a no-op (see bots/bot.py), so Example / Masher are unaffected.

    def menu(self, gamestate):
        """Per-CSS-frame opportunity to mutate ``self.character``.

        Only meaningful at the character-select screen. ``menu_helper_simple``
        will be passed the (possibly updated) ``self.character`` immediately
        after this returns, and will walk our cursor (and re-claim our coin
        with B) to whatever slot we ask for.
        """
        if gamestate.menu_state not in (Menu.CHARACTER_SELECT, Menu.SLIPPI_ONLINE_CSS):
            # We've left the CSS (e.g. stage select, in-game, postgame). Reset
            # the per-visit fallback state so the next match gets a fresh
            # 3-second window.
            self._css_start_frame = None
            self._fallback_used = False
            return

        # First frame we notice the CSS: stamp the baseline for the timeout.
        if self._css_start_frame is None:
            self._css_start_frame = gamestate.frame
        css_elapsed = gamestate.frame - self._css_start_frame

        self._discover_opponent(gamestate)

        if self._opponent_port is None:
            # Solo CSS -- nothing to avoid. Keep our tentative first roster slot.
            return

        opp = gamestate.players.get(self._opponent_port)
        if opp is None:
            return

        # ``coin_down`` does not work in the Slippi online CSS (per libmelee).
        # In local VS -- which is what arena.py runs -- it does, and it is the
        # cleanest "the other bot has committed" signal. We only react once the
        # opponent has actually dropped their coin so we don't chase a cursor
        # that is still wandering.
        if not getattr(opp, "coin_down", False):
            # Opponent's coin isn't down yet. If they never commit, fall back
            # after CSS_TIMEOUT_FRAMES: pick a random roster slot, still
            # avoiding the opponent's current cursor character if it happens
            # to be sitting on one of ours (a courtesy -- their cursor could
            # still move, but it's the best signal we have without a coin).
            if (
                css_elapsed >= CSS_TIMEOUT_FRAMES
                and not self._fallback_used
            ):
                opp_cursor = getattr(opp, "character", None)
                candidates = [
                    c for c in self.roster if c != opp_cursor
                ]
                if not candidates:
                    candidates = list(self.roster)
                self.character = random.choice(candidates)
                self._fallback_used = True
                self._committed = True
                logging.info(
                    "AniketBot: opponent hasn't committed after %d CSS frames "
                    "(~%.1fs); falling back to random roster slot %s.",
                    css_elapsed,
                    css_elapsed / 60.0,
                    self.character.name,
                )
            return

        opp_char = opp.character
        if opp_char is None or opp_char == melee.Character.UNKNOWN_CHARACTER:
            return
        self._opponent_character = opp_char
        if not self._opponent_logged:
            logging.info(
                "AniketBot: opponent (port %d) committed %s.",
                self._opponent_port,
                opp_char.name,
            )
            self._opponent_logged = True

        target = first_slot_away_from(self.roster, opp_char)
        if target != self.character:
            if not self._repick_logged:
                logging.info(
                    "AniketBot: rotating from %s to %s to avoid %s.",
                    self.character.name,
                    target.name,
                    opp_char.name,
                )
                self._repick_logged = True
            self.character = target

        # Freeze once in-game -- handled in fight(). _committed is an
        # advisory flag the gameplay layer can read.
        self._committed = True

    def _discover_opponent(self, gamestate):
        """Populate ``self._opponent_port`` from whatever player isn't us."""
        if self._opponent_port is not None:
            return
        for port in gamestate.players:
            if port != self.port:
                self._opponent_port = port
                logging.info(
                    "AniketBot: opponent occupies port %d.", self._opponent_port
                )
                return

    # ---------------------------------------------------------------------- play

    def fight(self, gamestate):
        """Called once per in-game frame by ``fight.py``.

        Pipeline:
            1. Discover ourselves + the opponent.
            2. Recovery override (off-stage -> wiggle to centre + up-B). This
               takes precedence over the stance machine: a bot that's dead
               can't play its archetype.
            3. Select / keep a stance (locked for ``STANCE_LOCK_FRAMES``).
            4. Dispatch to the stance's behaviour function, which writes the
               controller inputs directly.
        """
        if not self._port_logged:
            logging.info("AniketBot: in-game on port %d.", self.port)
            self._port_logged = True

        self._discover_opponent(gamestate)

        me = gamestate.players.get(self.port)
        if me is None:
            return  # CSS hasn't placed us yet -- shouldn't happen in-game.
        opp = (
            gamestate.players.get(self._opponent_port)
            if self._opponent_port is not None
            else None
        )

        # Release everything first so each branch starts from a clean slate.
        # We don't do held-charge smashes in v1, so a per-frame release is
        # safe and prevents leaked button presses across stance switches.
        self.controller.release_all()

        # Recovery override.
        if self._needs_recovery(me):
            self._recover(me)
            return

        if opp is None:
            # No opponent state this frame -- idle.
            return

        stance = select_stance(self, me, opp, gamestate)
        if stance is not self._stance_logged:
            logging.info(
                "AniketBot: stance -> %s (me %s%% %d stock, opp %s%% %d stock)",
                stance.value,
                int(me.percent),
                me.stock,
                int(opp.percent),
                opp.stock,
            )
            self._stance_logged = stance

        dx = opp.position.x - me.position.x
        dy = opp.position.y - me.position.y
        distance = gamestate.distance if gamestate.distance else (dx * dx + dy * dy) ** 0.5
        onleft = me.position.x < opp.position.x  # True -> opponent is to our right

        behave(self, stance, me, opp, gamestate, onleft, distance)

    # ----------------------------------------------------------- recovery only

    @staticmethod
    def _needs_recovery(me):
        """True if we are off-stage and below the platform line (roughly)."""
        return is_off_stage(me)

    def _recover(self, me):
        """Burn jumps toward centre, then up-B. Shared by all stances.

        We wait for each jump's apex before spending the next one so both jumps
        fire at full height (instead of pressing X twice on adjacent frames
        and truncating the first jump). On the ground we jump immediately;
        airborne we only re-press X when ``speed_y_self <= 0`` (the first
        jump has crested and we can spend the second one).
        """
        # Toward stage centre (positive x). x=1 means right.
        x = RECOVERY_JUMP_X if me.position.x < 0 else 0.0
        at_apex = getattr(me, "speed_y_self", 0.0) <= 0
        if me.jumps_left > 0 and (me.on_ground or at_apex):
            self.controller.tilt_analog(Button.BUTTON_MAIN, x, 0.5)
            self.controller.press_button(Button.BUTTON_X)
        else:
            # Out of jumps (or still rising on the first) -> up-B once we're
            # out of jumps. While rising on the first jump with no second jump
            # available we hold drift toward centre rather than burning up-B.
            if me.jumps_left > 0:
                # Still rising on the first jump; drift toward centre.
                self.controller.tilt_analog(Button.BUTTON_MAIN, x, 0.5)
            else:
                # Out of jumps -> up-B (MAIN up + toward centre, hold B).
                self.controller.tilt_analog(Button.BUTTON_MAIN, x, 1.0)
                self.controller.press_button(Button.BUTTON_B)