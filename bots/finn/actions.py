"""
bots/actions.py

Shared character selection, action space, controller mapping, observation
vector, and reward function used by both bots/finn/bot.py and
bots/finn/train.py.

Kept separate so both the live bot and the trainer stay in
sync automatically.
"""

import melee

AGENT_CHARACTER = melee.Character.MARTH

# ---------------------------------------------------------------------------
# Action space: movement + attacks only.
# No shield, no dodge, no grab, no recovery specials (Up-B etc.) - by design.
# This bot cannot block and cannot recover if knocked off-stage.
#
# Side attacks are explicit left/right actions so the policy can choose a
# direction instead of only having right-facing attacks available.
# ---------------------------------------------------------------------------
ACTIONS = [
    "no_op",
    "move_left",
    "move_right",
    "short_hop",
    "attack_jab",
    "attack_ftilt_left",
    "attack_ftilt_right",
    "attack_fsmash_left",
    "attack_fsmash_right",
    "attack_nair",
]

N_ACTIONS = len(ACTIONS)

# Frames the jump button is held before release, for a short hop rather than
# a full jump. Rough placeholder - real timing is character-dependent
# (usually 1-3 frames); tune against whatever character you use.
SHORT_HOP_HOLD_FRAMES = 2


def apply_action(controller: melee.Controller, action: str, frame_in_action: int = 0) -> None:
    """
    Sets controller inputs for the given discrete action. Call once per
    frame from fight() - frame_in_action tracks how long the *same* action
    has been selected in a row, needed for multi-frame actions like short_hop.
    """
    controller.release_all()

    if action == "no_op":
        pass

    elif action == "move_left":
        controller.tilt_analog(melee.Button.BUTTON_MAIN, 0.0, 0.5)

    elif action == "move_right":
        controller.tilt_analog(melee.Button.BUTTON_MAIN, 1.0, 0.5)

    elif action == "short_hop":
        if frame_in_action < SHORT_HOP_HOLD_FRAMES:
            controller.press_button(melee.Button.BUTTON_Y)
        # else: leave released - release_all() above already handled it

    elif action == "attack_jab":
        controller.press_button(melee.Button.BUTTON_A)

    elif action == "attack_ftilt_left":
        controller.tilt_analog(melee.Button.BUTTON_MAIN, 0.0, 0.5)
        controller.press_button(melee.Button.BUTTON_A)

    elif action == "attack_ftilt_right":
        controller.tilt_analog(melee.Button.BUTTON_MAIN, 1.0, 0.5)
        controller.press_button(melee.Button.BUTTON_A)

    elif action == "attack_fsmash_left":
        # BUTTON_C is the C-stick in libmelee's enum (not BUTTON_C_STICK,
        # despite what you might expect / find in older examples).
        controller.tilt_analog(melee.Button.BUTTON_C, 0.0, 0.5)

    elif action == "attack_fsmash_right":
        controller.tilt_analog(melee.Button.BUTTON_C, 1.0, 0.5)

    elif action == "attack_nair":
        controller.press_button(melee.Button.BUTTON_A)

    else:
        raise ValueError(f"Unknown action: {action}")


# ---------------------------------------------------------------------------
# Reward: damage dealt/taken plus stock events.
#
# Percent damage gives dense feedback. Kills and deaths are much larger sparse
# signals so the learned policy optimizes for stocks, not just trades.
# ---------------------------------------------------------------------------
DAMAGE_DEALT_SCALE = 1.0
DAMAGE_TAKEN_PENALTY = 0.5
KILL_BONUS = 50.0
DEATH_PENALTY = 50.0


def compute_reward(prev_gamestate: melee.GameState, curr_gamestate: melee.GameState,
                    agent_port: int, opponent_port: int) -> float:
    prev_agent = prev_gamestate.players[agent_port]
    curr_agent = curr_gamestate.players[agent_port]
    prev_opp = prev_gamestate.players[opponent_port]
    curr_opp = curr_gamestate.players[opponent_port]

    # Percent resets to 0 on death - clamp so a KO never reads as a negative
    # damage delta.
    damage_dealt = max(0.0, curr_opp.percent - prev_opp.percent)
    damage_taken = max(0.0, curr_agent.percent - prev_agent.percent)

    stocks_taken = max(0, prev_opp.stock - curr_opp.stock)
    stocks_lost = max(0, prev_agent.stock - curr_agent.stock)

    return (
        DAMAGE_DEALT_SCALE * damage_dealt
        - DAMAGE_TAKEN_PENALTY * damage_taken
        + KILL_BONUS * stocks_taken
        - DEATH_PENALTY * stocks_lost
    )


# ---------------------------------------------------------------------------
# Observation vector - minimal by design.
# ---------------------------------------------------------------------------
OBS_SIZE = 13


def get_observation(gamestate: melee.GameState, agent_port: int, opponent_port: int):
    me = gamestate.players[agent_port]
    opp = gamestate.players[opponent_port]
    return [
        me.position.x, me.position.y, me.percent, me.stock, float(me.facing),
        opp.position.x, opp.position.y, opp.percent, opp.stock, float(opp.facing),
        me.position.x - opp.position.x, me.position.y - opp.position.y,
        gamestate.distance,
    ]
