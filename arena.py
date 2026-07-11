import melee

from fight import fight

from bots.aniket import AniketBot
from bots.smashbot import SmashBot
from bots.linyu import LinyuPikachu
from bots.masher2 import Masher2
from bots.cheesy_kirby import CheesyKirby
from bots.finn.finn import RLBot
from bots.reece import ReeceBot

import logging
logging.basicConfig(level=logging.DEBUG)

if __name__ == "__main__":
    aniketBot = AniketBot()
    smashBot = SmashBot()
    linyuPikachu = LinyuPikachu()
    masher2 = Masher2()
    cheesyKirby = CheesyKirby()
    rLBot = RLBot()
    reeceBot = ReeceBot()

    #fight(melee.Stage.RANDOM_STAGE, [masher2, cheesyKirby])
    #fight(melee.Stage.RANDOM_STAGE, [aniketBot, reeceBot])
    #fight(melee.Stage.FINAL_DESTINATION, [linyuPikachu, rLBot])

    #fight(melee.Stage.FINAL_DESTINATION, [masher2, smashBot])
    #fight(melee.Stage.RANDOM_STAGE, [linyuPikachu, reeceBot])

    #fight(melee.Stage.FINAL_DESTINATION, [linyuPikachu, smashBot])

    #fight(melee.Stage.FINAL_DESTINATION, [reeceBot, smashBot])