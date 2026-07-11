import os
import sys
import logging

import melee

from .bot import Bot

# SmashBot's source (vendored under bots/smashbot_src/) uses top-level absolute
# imports like `from Tactics.punish import Punish` and `from esagent import ESAgent`.
# Rather than rewrite every file, we put that folder on sys.path so those imports
# resolve unchanged. See bots/smashbot_src/VENDOR.txt for the upstream commit.
_SMASHBOT_SRC = os.path.join(os.path.dirname(__file__), "smashbot_src")
if _SMASHBOT_SRC not in sys.path:
    sys.path.insert(0, _SMASHBOT_SRC)

from esagent import ESAgent  # noqa: E402  (import after sys.path tweak above)


def _patch_libmelee_is_bmove():
    """Work around a bug in libmelee 0.47.2's FrameData.is_bmove().

    That method's first line reads ``if action == Action.UNKNOWN_ANIMATION``,
    but libmelee removed the ``UNKNOWN_ANIMATION`` member from its ``Action``
    enum without updating this reference, so *any* call raises AttributeError.
    SmashBot calls is_bmove() every frame (via the Punish/Juggle tactics), so
    without this it crashes on the first in-game frame.

    We only patch when the member is genuinely missing, so a future fixed
    libmelee is left untouched. The replacement is libmelee's own logic with
    the dangling sentinel check dropped (an unrecognized action can't equal a
    non-existent enum member anyway).
    """
    from melee.enums import Action, Character
    from melee.framedata import FrameData

    if hasattr(Action, "UNKNOWN_ANIMATION"):
        return  # libmelee is fixed; nothing to do.

    def is_bmove(self, character, action):
        if character == Character.PEACH and action in [
            Action.LASER_GUN_PULL, Action.NEUTRAL_B_CHARGING, Action.NEUTRAL_B_ATTACKING,
        ]:
            return False
        if character == Character.PEACH and action in [
            Action.SWORD_DANCE_2_MID, Action.SWORD_DANCE_1, Action.SWORD_DANCE_2_HIGH,
        ]:
            return False
        try:
            return Action.LASER_GUN_PULL.value <= action.value
        except AttributeError:
            return False

    FrameData.is_bmove = is_bmove
    logging.info("Patched libmelee FrameData.is_bmove (0.47.2 UNKNOWN_ANIMATION bug)")


def _patch_libmelee_stage_args():
    """Bridge a libmelee API change SmashBot's vendored code predates.

    libmelee changed ``project_hit_location`` and ``roll_end_position`` to take a
    ``Stage`` enum where they used to take the whole ``GameState``. SmashBot's
    juggle/punish tactics still pass ``gamestate``, which then gets used as a dict
    key into a stage table and raises ``TypeError: unhashable type: 'GameState'``.

    We wrap both methods so a ``GameState`` passed positionally is transparently
    replaced with its ``.stage``. Anything already passing a ``Stage`` is untouched,
    so this is a no-op against a libmelee that matches SmashBot's original.
    """
    from melee.framedata import FrameData
    from melee.gamestate import GameState

    def _coerce_stage(method):
        def wrapper(self, character_state, stage, *args, **kwargs):
            if isinstance(stage, GameState):
                stage = stage.stage
            return method(self, character_state, stage, *args, **kwargs)
        wrapper.__name__ = getattr(method, "__name__", "wrapped")
        return wrapper

    for name in ("project_hit_location", "roll_end_position"):
        original = getattr(FrameData, name)
        if getattr(original, "_smashbot_stage_shim", False):
            continue
        wrapped = _coerce_stage(original)
        wrapped._smashbot_stage_shim = True
        setattr(FrameData, name, wrapped)
    logging.info("Patched libmelee stage-argument methods for SmashBot compatibility")


def _patch_playerstate_xy():
    """Restore ``PlayerState.x`` / ``.y`` aliases for libmelee's own framedata.

    libmelee moved a player's coordinates from ``state.x`` / ``state.y`` onto
    ``state.position``, but its ``FrameData.in_range`` still reads ``defender.y``
    on line 325 (right next to a correct ``defender.position.x``), so the method
    raises ``AttributeError: 'PlayerState' object has no attribute 'y'``. Adding
    read-only aliases that proxy to ``.position`` fixes libmelee's leftover
    references without touching SmashBot. No-op if libmelee ever restores them.
    """
    from melee.gamestate import PlayerState

    if not hasattr(PlayerState, "x"):
        PlayerState.x = property(lambda self: self.position.x)
    if not hasattr(PlayerState, "y"):
        PlayerState.y = property(lambda self: self.position.y)
    logging.info("Patched PlayerState.x/.y aliases for libmelee framedata compatibility")


_patch_libmelee_is_bmove()
_patch_libmelee_stage_args()
_patch_playerstate_xy()


class SmashBot(Bot):
    """Adapter that plugs altf4's SmashBot into this repo's Bot interface.

    SmashBot is an expert-system Fox AI. Its per-frame entry point is
    ``ESAgent.act(gamestate)``, which maps directly onto our ``fight()``.

    SmashBot only plays Fox, so the character is forced regardless of what is
    passed in. ``opponent_port`` may be left as None for a standard two-player
    match (we infer "the other port"); for 3+ players SmashBot re-derives the
    nearest opponent itself every frame.

    ``difficulty`` follows SmashBot's own scale:
        -1  auto-adjust based on stocks remaining
        1-4 increasing skill (4 = full strength)
        5   training/debug mode (takes hits, DIs, recovers, but won't attack)
    """

    def __init__(self, opponent_port=None, difficulty=4):
        super().__init__(melee.Character.FOX)
        self.opponent_port = opponent_port
        self.difficulty = difficulty
        self.agent = None

    def create_controller(self, console, port):
        super().create_controller(console, port)

        opponent_port = self.opponent_port
        if opponent_port is None:
            # Standard 1v1: the opponent is simply the other port.
            opponent_port = 2 if port == 1 else 1

        # ESAgent only reads `.logger` off the console object it's handed, and
        # melee.Console exposes that attribute (None unless a logger was set).
        self.agent = ESAgent(
            console,
            port,
            opponent_port,
            self.controller,
            self.difficulty,
        )
        logging.info(
            f"SmashBot on port {port} (opponent {opponent_port}, "
            f"difficulty {self.difficulty})"
        )

    def fight(self, gamestate):
        self.agent.act(gamestate)
