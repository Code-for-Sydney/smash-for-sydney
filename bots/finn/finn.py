"""
bots/finn/bot.py

RL-trained bot, following this repo's Bot interface (see bots/bot.py):
subclass Bot, implement fight(gamestate), which is called once per frame
and should only set self.controller inputs - no return value.

Usage in arena.py, same pattern as the other bots:

    from bots.finn.bot import RLBot
    player1 = RLBot()
    player2 = Example(melee.Character.KIRBY)
    fight(melee.Stage.RANDOM_STAGE, [player1, player2])

Loads weights from model_final.zip by default (see
bots/finn/train.py for how that checkpoint is produced). Pass a different path
via the checkpoint_path argument if needed.
"""

import logging
import numpy as np

from ..bot import Bot
from .actions import ACTIONS, AGENT_CHARACTER, apply_action, get_observation


class RLBot(Bot):

    def __init__(self, character=None, checkpoint_path="model_final.zip"):
        super().__init__(AGENT_CHARACTER)

        # Imported lazily so this file doesn't hard-require stable-baselines3
        # / torch just to be looked at, and so a missing checkpoint gives a
        # clear error rather than an import-time crash for anyone browsing
        # the repo without the RL deps installed.
        from stable_baselines3 import PPO
        self.model = PPO.load(checkpoint_path)
        logging.info(f"RLBot loaded weights from {checkpoint_path}")

        self._current_action = "no_op"
        self._frame_in_action = 0

    def fight(self, gamestate):
        opponent_port = next(p for p in gamestate.players if p != self.port)

        obs = get_observation(gamestate, self.port, opponent_port)
        action_idx, _ = self.model.predict(np.array(obs, dtype=np.float32), deterministic=True)
        action = ACTIONS[int(action_idx)]

        if action == self._current_action:
            self._frame_in_action += 1
        else:
            self._frame_in_action = 0
            self._current_action = action

        apply_action(self.controller, action, self._frame_in_action)
