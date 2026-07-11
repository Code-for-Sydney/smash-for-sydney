import melee

from fight import fight
#from bots.example import Example
from bots.reece import Reece
from bots.aniket import AniketBot

import logging
logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    player1 = Reece(melee.Character.GANONDORF)
    player2 = AniketBot(melee.Character.GANONDORF)

    # fight(melee.Stage.RANDOM_STAGE, [player1, player2])
    fight(melee.Stage.RANDOM_STAGE, [player1, player2])