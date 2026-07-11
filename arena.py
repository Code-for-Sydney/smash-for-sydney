import melee

from fight import fight
#from bots.example import Example
from bots.reece import ReeceBot
from bots.aniket import AniketBot
# from bots.smashbot import SmashBot

import logging

logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    player1 = ReeceBot()
    # player2 = SmashBot()
    player2 = AniketBot()

    # fight(melee.Stage.RANDOM_STAGE, [player1, player2])
    fight(melee.Stage.RANDOM_STAGE, [player1, player2])
