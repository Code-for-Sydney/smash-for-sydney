import melee

from fight import fight
from bots.example import Example
from bots.linyu import LinyuPikachu
from bots.masher import Masher

import logging
logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    player1 = LinyuPikachu()
    player2 = Masher()
    # player2 = Example(melee.Character.KIRBY)

    # fight(melee.Stage.RANDOM_STAGE, [player1, player2])
    fight(melee.Stage.RANDOM_STAGE, [player1, player2])
