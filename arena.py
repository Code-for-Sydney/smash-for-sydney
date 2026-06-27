import melee

from fight import fight
from bots.example import Example

import logging
logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    player1 = Example(melee.Character.JIGGLYPUFF)
    player2 = Example(melee.Character.FOX)

    fight(melee.Stage.BATTLEFIELD, [player1, player2])