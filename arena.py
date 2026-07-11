import melee

from fight import fight
from bots.example import Example
from bots.masher import Masher
from bots.aniket import AniketBot
from bots.smashbot import SmashBot

import logging
logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    player1 = Masher(melee.Character.MARIO)
    player2 = Example(melee.Character.KIRBY)

    # fight(melee.Stage.RANDOM_STAGE, [player1, player2])
    fight(melee.Stage.RANDOM_STAGE, [player1, player2])
