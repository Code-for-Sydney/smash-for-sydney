import melee

from fight import fight
from bots.example import Example
from bots.reece import Reece

import logging
logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    player1 = Example(melee.Character.MARIO)
    player2 = Reece(melee.Character.KIRBY)

    # fight(melee.Stage.RANDOM_STAGE, [player1, player2])
    fight(melee.Stage.RANDOM_STAGE, [player1, player2])